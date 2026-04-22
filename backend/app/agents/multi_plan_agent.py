"""
MultiPlanAgent — derives three infrastructure plan variants from a single
PlannerAgent blueprint: low_cost, balanced, and high_performance.

Each variant mutates the original ``infrastructure_blueprint`` deterministically
(no LLM calls) and delegates cost re-estimation to the existing
CostEstimationAgent so no pricing logic is duplicated.

Input
-----
plan             — PlannerAgent output dict (must contain ``infrastructure_blueprint``)
cost_estimation  — pre-computed baseline cost dict (from OrchestratorAgent's
                   cost_estimation node).  Used as-is for the balanced variant.
prompt           — original user prompt; drives the recommendation heuristic.
application_profile — optional ApplicationProfilerService dict forwarded to
                      CostEstimationAgent for instance-sizing refinement.

Output
------
{
  "plans": [
    {
      "plan_id": "low_cost",
      "architecture": {...},
      "cost_estimation": {...},
      "tradeoffs": [...],
      "score": {"cost_efficiency": float, "scalability": float, "reliability": float}
    },
    {"plan_id": "balanced",         ...},
    {"plan_id": "high_performance", ...}
  ],
  "recommended_plan": "balanced" | "low_cost" | "high_performance"
}
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from backend.app.agents.base_agent import BaseAgent
from backend.app.agents.cost_estimation_agent import CostEstimationAgent

logger = logging.getLogger(__name__)


# ── Instance-type transition tables ──────────────────────────────────────────
# Keys match the types accepted by _AwsPricingModel in CostEstimationAgent.

_EC2_DOWNGRADE: Dict[str, str] = {
    "t3.micro":   "t3.micro",
    "t3.small":   "t3.micro",
    "t3.medium":  "t3.small",
    "t3.large":   "t3.small",
    "t3.xlarge":  "t3.medium",
    "m5.large":   "t3.medium",
    "m5.xlarge":  "t3.large",
    "m5.2xlarge": "m5.large",
    "c5.large":   "t3.medium",
    "c5.xlarge":  "t3.large",
    "r5.large":   "t3.medium",
    "r5.xlarge":  "m5.large",
}

_EC2_UPGRADE: Dict[str, str] = {
    "t3.micro":   "t3.small",
    "t3.small":   "t3.medium",
    "t3.medium":  "m5.large",
    "t3.large":   "m5.xlarge",
    "t3.xlarge":  "m5.2xlarge",
    "m5.large":   "m5.xlarge",
    "m5.xlarge":  "m5.2xlarge",
    "m5.2xlarge": "m5.2xlarge",
    "c5.large":   "c5.xlarge",
    "c5.xlarge":  "m5.2xlarge",
    "r5.large":   "r5.xlarge",
    "r5.xlarge":  "r5.xlarge",
}

_RDS_DOWNGRADE: Dict[str, str] = {
    "db.t3.micro":  "db.t3.micro",
    "db.t3.small":  "db.t3.micro",
    "db.t3.medium": "db.t3.small",
    "db.t3.large":  "db.t3.small",
    "db.r5.large":  "db.t3.medium",
    "db.r5.xlarge": "db.r5.large",
}

_RDS_UPGRADE: Dict[str, str] = {
    "db.t3.micro":  "db.t3.small",
    "db.t3.small":  "db.t3.medium",
    "db.t3.medium": "db.r5.large",
    "db.t3.large":  "db.r5.large",
    "db.r5.large":  "db.r5.xlarge",
    "db.r5.xlarge": "db.r5.xlarge",
}

# Keyword sets for the recommendation heuristic
_LOW_COST_SIGNALS = frozenset({
    "cheap", "budget", "low cost", "low-cost", "minimal", "save money",
    "frugal", "cost-effective", "affordable",
})
_HIGH_PERF_SIGNALS = frozenset({
    "high traffic", "high-traffic", "scalable", "performance", "enterprise",
    "mission critical", "resilient", "ha ", "high availability",
    "large scale", "heavy load",
})


class MultiPlanAgent(BaseAgent):
    """
    Generates three deterministic infrastructure plan variants from a base
    PlannerAgent blueprint and recomputes AWS cost for each variant using
    the existing CostEstimationAgent.

    No LLM calls are made — behaviour is fully deterministic and testable
    without any network access.
    """

    def __init__(self) -> None:
        super().__init__(name="MultiPlanAgent")
        self._cost_agent = CostEstimationAgent()

    # ── Public interface ──────────────────────────────────────────────────────

    def run(
        self,
        plan: Dict[str, Any],
        cost_estimation: Optional[Dict[str, Any]] = None,
        prompt: str = "",
        application_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Derive three plan variants and return them with costs, tradeoffs, and
        scores.

        Parameters
        ----------
        plan:
            PlannerAgent output — must contain ``infrastructure_blueprint``.
        cost_estimation:
            Pre-computed baseline cost dict (inner dict, not wrapped).  Reused
            for the balanced variant to skip a redundant CostEstimationAgent
            call.  Falls back to a fresh estimation when None.
        prompt:
            Original user prompt — drives the recommendation heuristic.
        application_profile:
            Forwarded to CostEstimationAgent for node-count / sizing hints.

        Returns
        -------
        {"plans": [...], "recommended_plan": str}
        """
        base_blueprint: Dict[str, Any] = plan.get("infrastructure_blueprint") or {}

        # Build three variant blueprints
        low_cost_bp   = self._build_low_cost_blueprint(base_blueprint)
        balanced_bp   = copy.deepcopy(base_blueprint)
        high_perf_bp  = self._build_high_performance_blueprint(base_blueprint)

        # Estimate cost — reuse pre-computed baseline for balanced
        low_cost_ce  = self._estimate_cost(low_cost_bp,  application_profile)
        balanced_ce  = cost_estimation or self._estimate_cost(balanced_bp, application_profile)
        high_perf_ce = self._estimate_cost(high_perf_bp, application_profile)

        logger.info(
            "[MultiPlanAgent] Plans generated — "
            "low_cost=$%.2f  balanced=$%.2f  high_performance=$%.2f",
            (low_cost_ce  or {}).get("monthly_cost", 0.0),
            (balanced_ce  or {}).get("monthly_cost", 0.0),
            (high_perf_ce or {}).get("monthly_cost", 0.0),
        )

        plans: List[Dict[str, Any]] = [
            self._build_plan_entry(
                plan_id="low_cost",
                base_plan=plan,
                blueprint=low_cost_bp,
                cost_estimation=low_cost_ce,
                tradeoffs=[
                    "Lower monthly cost through reduced instance sizes and node counts",
                    "Single-AZ database — availability reduced to ~99.5% SLA",
                    "No Redis cache — increased database read pressure under load",
                    "Limited horizontal scalability under traffic spikes",
                    "Best suited for development, staging, or low-traffic production",
                ],
                score={
                    "cost_efficiency": 0.9,
                    "scalability":     0.3,
                    "reliability":     0.3,
                },
            ),
            self._build_plan_entry(
                plan_id="balanced",
                base_plan=plan,
                blueprint=balanced_bp,
                cost_estimation=balanced_ce,
                tradeoffs=[
                    "Good compromise between cost and performance",
                    "Baseline architecture as specified in the original plan",
                    "Moderate scaling capacity — handles typical production workloads",
                    "Standard reliability without premium HA overhead",
                ],
                score={
                    "cost_efficiency": 0.6,
                    "scalability":     0.6,
                    "reliability":     0.6,
                },
            ),
            self._build_plan_entry(
                plan_id="high_performance",
                base_plan=plan,
                blueprint=high_perf_bp,
                cost_estimation=high_perf_ce,
                tradeoffs=[
                    "Higher monthly cost — premium instances and expanded node pool",
                    "Multi-AZ database for ~99.95% availability SLA",
                    "Redis cache layer reduces read latency and database pressure",
                    "Aggressive auto-scaling handles high-traffic bursts gracefully",
                    "Best suited for business-critical or high-throughput production workloads",
                ],
                score={
                    "cost_efficiency": 0.2,
                    "scalability":     0.9,
                    "reliability":     0.9,
                },
            ),
        ]

        recommended = self._select_recommendation(prompt)
        logger.info("[MultiPlanAgent] Recommended plan: '%s'", recommended)

        return {"plans": plans, "recommended_plan": recommended}

    # ── Blueprint mutation ────────────────────────────────────────────────────

    def _build_low_cost_blueprint(self, base: Dict[str, Any]) -> Dict[str, Any]:
        """
        Produce a cost-minimised blueprint:
        - Downsize EC2 / node instance types by one tier
        - Reduce node count to 1 (or current - 1, whichever is larger)
        - Remove Redis / ElastiCache cache
        - Force Single-AZ database
        - Minimal auto-scaling policy
        """
        bp = copy.deepcopy(base)

        compute = bp.get("compute") or {}
        for key in ("instance_type", "node_type"):
            if key in compute:
                compute[key] = _EC2_DOWNGRADE.get(compute[key], compute[key])
        if "min_nodes" in compute:
            compute["min_nodes"] = max(1, int(compute["min_nodes"]) - 1)
        if "max_nodes" in compute:
            compute["max_nodes"] = max(
                int(compute.get("min_nodes", 1)),
                int(compute["max_nodes"]) - 1,
            )
        bp["compute"] = compute

        database = bp.get("database") or {}
        if database:
            for key in ("instance_type", "instance_class"):
                if key in database:
                    database[key] = _RDS_DOWNGRADE.get(database[key], database[key])
            database["deployment"] = "single-az"
            database.pop("read_replicas", None)
            bp["database"] = database

        bp["cache"] = None

        bp["scaling"] = {
            "strategy":     "minimal",
            "min_replicas": 1,
            "max_replicas": 2,
            "cpu_threshold": 80,
        }

        return bp

    def _build_high_performance_blueprint(self, base: Dict[str, Any]) -> Dict[str, Any]:
        """
        Produce a performance-optimised blueprint:
        - Upgrade EC2 / node instance types by one tier
        - Increase node count by 2 (min) and 4 (max)
        - Enable Redis cache
        - Force Multi-AZ database with one read replica
        - Aggressive auto-scaling policy
        """
        bp = copy.deepcopy(base)

        compute = bp.get("compute") or {}
        for key in ("instance_type", "node_type"):
            if key in compute:
                compute[key] = _EC2_UPGRADE.get(compute[key], compute[key])
        if "min_nodes" in compute:
            compute["min_nodes"] = int(compute["min_nodes"]) + 2
        if "max_nodes" in compute:
            compute["max_nodes"] = int(compute["max_nodes"]) + 4
        bp["compute"] = compute

        database = bp.get("database") or {}
        if database:
            for key in ("instance_type", "instance_class"):
                if key in database:
                    database[key] = _RDS_UPGRADE.get(database[key], database[key])
            database["deployment"] = "multi-az"
            database["read_replicas"] = 1
            bp["database"] = database

        bp["cache"] = {"engine": "redis", "instance_type": "cache.t3.micro"}

        base_scaling = base.get("scaling") or {}
        bp["scaling"] = {
            "strategy":           "aggressive",
            "min_replicas":       int(base_scaling.get("min_replicas", 2)),
            "max_replicas":       20,
            "cpu_threshold":      50,
            "scale_up_cooldown":  60,
            "scale_down_cooldown": 300,
        }

        return bp

    # ── Cost estimation helper ────────────────────────────────────────────────

    def _estimate_cost(
        self,
        blueprint: Dict[str, Any],
        application_profile: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Wrap blueprint in a minimal plan dict and delegate to CostEstimationAgent."""
        try:
            result = self._cost_agent.run(
                plan={"infrastructure_blueprint": blueprint},
                application_profile=application_profile,
            )
            return result.get("cost_estimation") or {}
        except Exception as exc:
            logger.warning("[MultiPlanAgent] CostEstimationAgent failed: %s", exc)
            return {}

    # ── Plan entry builder ────────────────────────────────────────────────────

    @staticmethod
    def _build_plan_entry(
        plan_id: str,
        base_plan: Dict[str, Any],
        blueprint: Dict[str, Any],
        cost_estimation: Dict[str, Any],
        tradeoffs: List[str],
        score: Dict[str, float],
    ) -> Dict[str, Any]:
        """Assemble a complete plan variant dict compatible with OrchestratorState."""
        return {
            **base_plan,
            "plan_id":                plan_id,
            "plan_variant":           plan_id,
            "infrastructure_blueprint": blueprint,
            "architecture":           blueprint,
            "cost_estimation":        cost_estimation,
            "tradeoffs":              tradeoffs,
            "score":                  score,
        }

    # ── Recommendation heuristic ──────────────────────────────────────────────

    @staticmethod
    def _select_recommendation(prompt: str) -> str:
        """
        Rule-based plan recommendation derived from prompt keywords.

        Priority:
        1. Low-cost signals (budget / cheap) → "low_cost"
        2. High-performance signals (enterprise / high traffic) → "high_performance"
        3. Default → "balanced"
        """
        lower = (prompt or "").lower()

        if any(sig in lower for sig in _LOW_COST_SIGNALS):
            return "low_cost"
        if any(sig in lower for sig in _HIGH_PERF_SIGNALS):
            return "high_performance"
        return "balanced"
