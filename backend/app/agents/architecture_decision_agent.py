"""
ArchitectureDecisionAgent — unified planning + cost estimation phase.

Replaces the sequential PLAN → COST_ESTIMATION flow with a single atomic phase
that generates 1–3 deployment strategies, each enriched with AWS cost estimates,
tradeoffs, and infrastructure blueprints.

Design principles
-----------------
* One LLM call (via PlannerAgent) produces the base plan and infrastructure
  blueprint.  Three cost-differentiated variants are derived deterministically
  from that blueprint — no extra LLM calls needed.
* CostEstimationAgent runs once per variant (pure arithmetic + optional LLM tips).
* Returns a self-contained ``architecture_decision`` dict that the orchestrator
  persists atomically before surfacing to the user.
* Handles missing application_profile gracefully via a safe default.

Output shape
------------
{
  "plans": [
    {
      "id":                   str,        # "low_cost" | "balanced" | "high_performance"
      "title":                str,
      "description":          str,
      "tradeoffs":            [str, ...],
      "scalability_tier":     str,
      "availability_level":   str,
      "monthly_cost":         float,
      "yearly_cost":          float,
      "cost_breakdown":       {str: float},
      "cost_profile":         str,
      "optimization_tips":    [str, ...],
      "assumptions":          [str, ...],
      "pricing_model_version":str,
      "infrastructure":       dict,       # AWS blueprint
      "plan":                 dict,       # Full PlannerAgent output for this variant
    },
    ...
  ],
  "recommended_plan": str   # "balanced"
}
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.app.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# ── Default profile used when no repository was analysed ─────────────────────

_DEFAULT_APPLICATION_PROFILE: Dict[str, Any] = {
    "application_type": "monolith",
    "scalability_level": "medium",
    "statefulness": "stateless",
    "workload_profile": "io_bound",
    "detected_services": [],
}


# ── Strategy metadata ─────────────────────────────────────────────────────────

_STRATEGIES: List[Dict[str, Any]] = [
    {
        "id":                 "low_cost",
        "title":              "Low Cost",
        "scalability_override": "low",
        "scalability_tier":   "Low",
        "availability_level": "Single-AZ",
        "description": (
            "Minimal infrastructure optimised for development, staging, or "
            "low-traffic production workloads."
        ),
        "tradeoffs_monolith": [
            "Single-AZ deployment — no high availability",
            "t3.small compute — suitable for <50 concurrent users",
            "No autoscaling — manual instance resizing required",
            "Single-AZ RDS — risk of data-layer downtime during AZ failure",
            "No Redis cache layer — all reads hit the database",
        ],
        "tradeoffs_microservices": [
            "Single-AZ EKS workers — no HA across availability zones",
            "Minimum 2 worker nodes t3.small — limited pod capacity",
            "No ElastiCache — inter-service latency not buffered",
            "Single-AZ RDS — potential data-layer downtime",
            "Pod autoscaling limited by small node pool",
        ],
        "tradeoffs_serverless": [
            "Lambda cold starts may affect latency (<500ms warm-up)",
            "DynamoDB provisioned capacity — over-provisioning risk",
            "API Gateway rate limits apply",
            "No dedicated VPC — lower network isolation",
            "Monitoring costs lower but debugging more complex",
        ],
    },
    {
        "id":                 "balanced",
        "title":              "Balanced",
        "scalability_override": "medium",
        "scalability_tier":   "Medium",
        "availability_level": "Multi-AZ",
        "description": (
            "Production-ready with cost-performance balance. "
            "Recommended for most teams shipping to production."
        ),
        "tradeoffs_monolith": [
            "Multi-AZ deployment — basic HA with automatic failover",
            "t3.medium compute — handles ~200 concurrent users",
            "Vertical + horizontal autoscaling enabled",
            "Multi-AZ RDS — automatic standby failover (~30s RTO)",
            "Good balance between cost and reliability",
        ],
        "tradeoffs_microservices": [
            "Multi-AZ EKS cluster — pods distributed across AZs",
            "2–3 worker nodes t3.medium — good pod density",
            "Multi-AZ RDS — automatic standby failover",
            "Optional ElastiCache based on detected services",
            "Horizontal pod autoscaling for traffic spikes",
        ],
        "tradeoffs_serverless": [
            "Lambda scales automatically to thousands of requests",
            "Aurora Serverless v2 — auto-scales database ACUs",
            "API Gateway handles request routing and throttling",
            "Pay-per-use model — cost scales with actual traffic",
            "Minimal operational overhead — fully managed services",
        ],
    },
    {
        "id":                 "high_performance",
        "title":              "High Performance",
        "scalability_override": "high",
        "scalability_tier":   "High",
        "availability_level": "Multi-AZ + Read Replicas",
        "description": (
            "Enterprise-grade infrastructure for high-traffic workloads, "
            "strict SLA requirements, and large-scale production systems."
        ),
        "tradeoffs_monolith": [
            "Multi-AZ with Redis cache — sub-millisecond read latency",
            "m5.large compute — handles 1000+ concurrent users",
            "Aggressive horizontal autoscaling",
            "Multi-AZ RDS + read replicas — zero read-path SPOF",
            "Higher monthly cost — justified for production SLAs >99.9%",
        ],
        "tradeoffs_microservices": [
            "Multi-AZ EKS with 3+ worker nodes t3.large",
            "ElastiCache Redis always included — reduces DB read load by ~60%",
            "RDS Multi-AZ + read replicas — scales read throughput",
            "Aggressive HPA + Cluster Autoscaler for traffic bursts",
            "Highest monthly cost — justified for enterprise SLAs",
        ],
        "tradeoffs_serverless": [
            "Lambda with Provisioned Concurrency — eliminates cold starts",
            "Aurora Serverless scales to very high ACU counts",
            "API Gateway with WAF integration for security",
            "Cost scales significantly at high request volumes",
            "Fully managed — no cluster or instance management",
        ],
    },
]


# ── Agent ─────────────────────────────────────────────────────────────────────


class ArchitectureDecisionAgent(BaseAgent):
    """
    Orchestrates the unified architecture-decision phase.

    Parameters (injected by OrchestratorAgent)
    ------------------------------------------
    planner_agent      — PlannerAgent instance
    cost_agent         — CostEstimationAgent instance
    """

    def __init__(self, planner_agent: Any, cost_agent: Any) -> None:
        super().__init__(name="ArchitectureDecisionAgent")
        self.planner_agent = planner_agent
        self.cost_agent = cost_agent

    # ── Public interface ──────────────────────────────────────────────────────

    def run(
        self,
        prompt: str,
        planner_context: Optional[Dict[str, Any]],
        application_profile: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Generate multiple architecture strategies with enriched cost estimates.

        1. Derive application_profile (use default when none available).
        2. Call PlannerAgent once to get the base plan + blueprint.
        3. Build three blueprint variants (low_cost / balanced / high_performance).
        4. Run CostEstimationAgent on each variant.
        5. Return enriched plans + recommended_plan.
        """
        profile = application_profile or _DEFAULT_APPLICATION_PROFILE.copy()
        arch_style = self._detect_arch_style(profile)

        logger.info(
            "[ArchitectureDecisionAgent] Starting — arch_style=%s scalability=%s",
            arch_style,
            profile.get("scalability_level"),
        )

        # ── Step 1: Single base plan from PlannerAgent ────────────────────────
        base_plan = self.planner_agent.run(prompt, planner_context)
        base_blueprint: Dict[str, Any] = base_plan.get("infrastructure_blueprint") or {}

        logger.info(
            "[ArchitectureDecisionAgent] Base plan generated — complexity=%s",
            base_plan.get("estimated_complexity"),
        )

        # ── Step 2: Build 3 blueprint variants + cost-estimate each ──────────
        # TASK 3 — never surface a (architecture, tier) the renderer cannot
        # build. With the balanced-baseline fallback in place this only drops a
        # strategy when an architecture lacks even a baseline template set (a
        # packaging error), but it guarantees the user is never offered a plan
        # that would hard-fail at the Terraform generation phase.
        renderable = self._renderable_strategies(arch_style)
        dropped = [s["id"] for s in _STRATEGIES if s["id"] not in renderable]
        if dropped:
            logger.warning(
                "[ArchitectureDecisionAgent] Architecture '%s' cannot render "
                "tiers %s (no template set and no balanced baseline) — these "
                "strategies will not be offered.",
                arch_style, dropped,
            )

        enriched_plans: List[Dict[str, Any]] = []
        for strategy in _STRATEGIES:
            if strategy["id"] not in renderable:
                continue
            variant_profile = dict(profile)
            variant_profile["scalability_level"] = strategy["scalability_override"]

            variant_blueprint = self._adapt_blueprint(
                base=base_blueprint,
                scalability=strategy["scalability_override"],
                arch_style=arch_style,
            )

            # Stamp the strategy tier directly into the blueprint so it
            # survives every downstream handoff (resume_with_selected_plan
            # → TerraformAgent). Previously this was carried only on the
            # outer strategy dict and got dropped on plan promotion.
            variant_blueprint["strategy_tier"] = strategy["id"]

            # Validate the adapted variant before persisting. Catches any
            # blueprint mutation that produced an invalid shape (e.g. EKS
            # without min_nodes) before the user ever sees it.
            from backend.app.schemas.blueprint import parse_blueprint
            validated_variant = parse_blueprint(variant_blueprint)
            variant_blueprint = validated_variant.model_dump(mode="json", exclude_none=True)

            variant_plan = dict(base_plan)
            variant_plan["infrastructure_blueprint"] = variant_blueprint
            # Carry the strategy id on the plan too — downstream code that
            # only sees state["plan"] (not the strategy wrapper) can read it.
            variant_plan["plan_id"] = strategy["id"]
            variant_plan["strategy_tier"] = strategy["id"]

            cost_result = self._run_cost_estimation(variant_plan, variant_profile, strategy["id"])
            cost = cost_result.get("cost_estimation") or {}

            tradeoff_key = f"tradeoffs_{arch_style}"
            tradeoffs = strategy.get(tradeoff_key) or strategy.get("tradeoffs_monolith", [])

            aws_services = self._extract_aws_services(variant_blueprint)

            enriched: Dict[str, Any] = {
                "id":                   strategy["id"],
                "title":                strategy["title"],
                "description":          strategy["description"],
                "tradeoffs":            tradeoffs,
                "scalability_tier":     strategy["scalability_tier"],
                "availability_level":   strategy["availability_level"],
                "monthly_cost":         cost.get("monthly_cost", 0.0),
                "yearly_cost":          round(cost.get("monthly_cost", 0.0) * 12, 2),
                "cost_breakdown":       cost.get("breakdown") or {},
                "cost_profile":         cost.get("cost_profile", "unknown"),
                "optimization_tips":    cost.get("optimization_tips") or [],
                "assumptions":          cost.get("assumptions") or [],
                "pricing_model_version": cost.get("pricing_model_version", "aws-simplified-v1"),
                "infrastructure":       variant_blueprint,
                "aws_services":         aws_services,
                "plan":                 variant_plan,
                "required_artifacts":   base_plan.get("required_artifacts") or [],
                "reasoning_summary":    base_plan.get("reasoning_summary") or "",
                "estimated_complexity": base_plan.get("estimated_complexity") or "medium",
                "steps":                base_plan.get("steps") or [],
            }
            enriched_plans.append(enriched)
            logger.info(
                "[ArchitectureDecisionAgent] Strategy '%s' — $%.2f/month (%s)",
                strategy["id"],
                enriched["monthly_cost"],
                enriched["cost_profile"],
            )

        if not enriched_plans:
            # Unreachable while every shipped architecture has a balanced
            # baseline. Fail loudly rather than return an empty decision the
            # user cannot act on.
            from backend.app.agents.errors import AgentError
            raise AgentError(
                f"No renderable deployment strategy for architecture "
                f"'{arch_style}'.",
                metadata={"renderable_matrix": self._renderable_matrix_summary(arch_style)},
            )

        # recommended_plan must be one we actually kept.
        recommended = (
            "balanced"
            if any(p["id"] == "balanced" for p in enriched_plans)
            else enriched_plans[0]["id"]
        )
        return {
            "plans": enriched_plans,
            "recommended_plan": recommended,
        }

    # ── Renderable-combination guards (TASK 3) ────────────────────────────────

    @staticmethod
    def _renderable_strategies(arch_style: str) -> set:
        """Subset of strategy ids the Terraform renderer can build for this
        architecture (exact template set OR balanced-baseline fallback)."""
        from backend.app.services.terraform_generation.renderers.template_renderer import (
            TerraformTemplateRenderer,
        )
        return {
            s["id"]
            for s in _STRATEGIES
            if TerraformTemplateRenderer.is_renderable(arch_style, s["id"])
        }

    @staticmethod
    def _renderable_matrix_summary(arch_style: str) -> Dict[str, str]:
        from backend.app.services.terraform_generation.renderers.template_renderer import (
            TerraformTemplateRenderer,
        )
        return TerraformTemplateRenderer.renderable_matrix().get(arch_style, {})

    # ── Blueprint adaptation ──────────────────────────────────────────────────

    def _adapt_blueprint(
        self,
        base: Dict[str, Any],
        scalability: str,
        arch_style: str,
    ) -> Dict[str, Any]:
        """
        Return a deep-copied blueprint with scalability-level adjustments.
        Serverless blueprints are returned unchanged (Lambda scales automatically).
        """
        bp = copy.deepcopy(base)

        if arch_style == "serverless":
            return bp

        compute  = bp.setdefault("compute", {})
        database = bp.setdefault("database", {})
        networking = bp.setdefault("networking", {})
        scaling  = bp.setdefault("scaling", {})

        if arch_style == "microservices":
            self._adapt_microservices(bp, compute, database, scaling, scalability)
        else:
            # monolith / unknown
            self._adapt_monolith(bp, compute, database, networking, scaling, scalability)

        return bp

    @staticmethod
    def _adapt_microservices(
        bp: Dict[str, Any],
        compute: Dict[str, Any],
        database: Dict[str, Any],
        scaling: Dict[str, Any],
        scalability: str,
    ) -> None:
        if scalability == "low":
            compute["node_type"]  = "t3.small"
            compute["min_nodes"]  = 2
            compute["max_nodes"]  = 4
            database["deployment"] = "RDS Single-AZ"
            database.pop("read_replicas", None)
            bp.pop("cache", None)
            scaling["strategy"]    = "horizontal"
            scaling["auto_scaling"] = True

        elif scalability == "high":
            compute["node_type"]  = "t3.large"
            compute["min_nodes"]  = 3
            compute["max_nodes"]  = 10
            database["deployment"] = "RDS Multi-AZ"
            database["read_replicas"] = True
            bp.setdefault("cache", {"engine": "Redis", "deployment": "ElastiCache"})
            scaling["strategy"]    = "horizontal"
            scaling["auto_scaling"] = True

        else:  # medium / balanced — keep base blueprint
            pass

    @staticmethod
    def _adapt_monolith(
        bp: Dict[str, Any],
        compute: Dict[str, Any],
        database: Dict[str, Any],
        networking: Dict[str, Any],
        scaling: Dict[str, Any],
        scalability: str,
    ) -> None:
        if scalability == "low":
            compute["instance_type"]   = "t3.small"
            networking["multi_az"]     = False
            database["deployment"]     = "RDS Single-AZ"
            scaling["auto_scaling"]    = False
            scaling["strategy"]        = "vertical"
            bp.pop("cache", None)

        elif scalability == "high":
            compute["instance_type"]   = "m5.large"
            networking["multi_az"]     = True
            database["deployment"]     = "RDS Multi-AZ"
            database["read_replicas"]  = True
            scaling["auto_scaling"]    = True
            scaling["strategy"]        = "horizontal"
            bp.setdefault("cache", {"engine": "Redis", "deployment": "ElastiCache"})

        else:  # medium / balanced — keep base blueprint
            pass

    # ── Cost estimation wrapper ───────────────────────────────────────────────

    def _run_cost_estimation(
        self,
        plan: Dict[str, Any],
        profile: Dict[str, Any],
        strategy_id: str,
    ) -> Dict[str, Any]:
        try:
            return self.cost_agent.run(plan=plan, application_profile=profile)
        except Exception as exc:
            logger.warning(
                "[ArchitectureDecisionAgent] CostEstimationAgent failed for strategy '%s' (%s) — using zeros.",
                strategy_id,
                exc,
            )
            return {"cost_estimation": {"monthly_cost": 0.0, "breakdown": {}, "cost_profile": "unknown"}}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_arch_style(profile: Dict[str, Any]) -> str:
        app_type = (profile.get("application_type") or "monolith").lower()
        if app_type in ("serverless",):
            return "serverless"
        if app_type in ("microservices",):
            return "microservices"
        return "monolith"

    @staticmethod
    def _extract_aws_services(blueprint: Dict[str, Any]) -> List[str]:
        """Derive human-readable AWS service names from a blueprint dict."""
        services: List[str] = []
        arch = blueprint.get("architecture_style", "monolith")
        compute_type = (blueprint.get("compute") or {}).get("type", "")
        db_engine = (blueprint.get("database") or {}).get("engine", "")
        lb = (blueprint.get("networking") or {}).get("load_balancer", "")
        has_cache = bool(blueprint.get("cache"))

        if compute_type == "EKS":
            services += ["Amazon EKS", "Amazon EC2 (Worker Nodes)"]
        elif compute_type == "Lambda":
            services.append("AWS Lambda")
        elif compute_type == "ECS":
            services += ["Amazon ECS", "Amazon EC2"]
        else:
            services.append("Amazon EC2")

        if db_engine:
            if "aurora" in db_engine.lower():
                services.append("Amazon Aurora")
            elif "dynamo" in db_engine.lower():
                services.append("Amazon DynamoDB")
            else:
                services.append(f"Amazon RDS ({db_engine})")

        if lb == "ALB":
            services.append("Application Load Balancer")
        elif "gateway" in lb.lower():
            services.append("Amazon API Gateway")

        if has_cache:
            services.append("Amazon ElastiCache (Redis)")

        services += ["Amazon S3", "Amazon CloudWatch", "AWS VPC"]

        if arch == "microservices" or compute_type == "EKS":
            services.append("Amazon ECR")

        return list(dict.fromkeys(services))  # preserve order, deduplicate
