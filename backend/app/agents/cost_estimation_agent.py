"""
CostEstimationAgent — AWS-inspired deterministic cloud cost estimator.

Architecture
------------
• Core pricing engine is fully deterministic — no external API calls, no
  randomness.  Numbers are derived from AWS public pricing documentation
  (simplified model, not a billing engine).

• LLM is invoked once (via the ReAct loop inherited from EnhancedBaseAgent) to
  produce human-readable, context-aware optimization tips.  Falls back to a
  rule-based tip generator if the LLM call fails.

• Future-proof design: all price constants live in ``_AwsPricingModel`` so
  region-specific or real-time pricing can be plugged in without changing any
  estimation logic.

AWS Pricing References (simplified model)
------------------------------------------
EC2:           https://aws.amazon.com/ec2/pricing/on-demand/
EKS:           https://aws.amazon.com/eks/pricing/
RDS:           https://aws.amazon.com/rds/pricing/
S3:            https://aws.amazon.com/s3/pricing/
Data Transfer: https://aws.amazon.com/ec2/pricing/on-demand/#Data_Transfer

Input
-----
``run(plan, application_profile)``

  plan                — dict produced by PlannerAgent.run(); must contain
                        an ``infrastructure_blueprint`` key.
  application_profile — optional dict from ApplicationProfilerService used to
                        refine instance sizing and node counts.

Output
------
{
  "cost_estimation": {
    "monthly_cost": float,
    "breakdown": {"compute": ..., "database": ..., ...},
    "cost_profile": "startup" | "small_production" | "medium_production" | "enterprise",
    "assumptions": [...],
    "optimization_tips": [...],
    "pricing_model_version": str
  }
}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.app.agents.base_agent import EnhancedBaseAgent
from backend.app.services.core.llm_service import LLMService

logger = logging.getLogger(__name__)

_HOURS_PER_MONTH: int = 730  # AWS standard: 730 hours/month


# ── AWS-inspired pricing tables ───────────────────────────────────────────────


class _AwsPricingModel:
    """
    Simplified AWS pricing constants (us-east-1, on-demand, Linux).

    All prices in USD.  Future extension: swap class attributes for a
    real-time pricing client or inject region-specific overrides without
    touching the estimation logic.

    References
    ----------
    EC2 on-demand: https://aws.amazon.com/ec2/pricing/on-demand/
    EKS:           https://aws.amazon.com/eks/pricing/
    RDS:           https://aws.amazon.com/rds/pricing/
    S3:            https://aws.amazon.com/s3/pricing/
    ElastiCache:   https://aws.amazon.com/elasticache/pricing/
    """

    # ── EC2 (on-demand, Linux, us-east-1) ─────────────────────────────────────
    EC2_HOURLY: Dict[str, float] = {
        "t3.micro":   0.0116,
        "t3.small":   0.0208,
        "t3.medium":  0.0416,
        "t3.large":   0.0832,
        "t3.xlarge":  0.1664,
        "m5.large":   0.0960,
        "m5.xlarge":  0.1920,
        "m5.2xlarge": 0.3840,
        "c5.large":   0.0850,
        "c5.xlarge":  0.1700,
        "r5.large":   0.1260,
        "r5.xlarge":  0.2520,
    }
    EC2_DEFAULT_INSTANCE = "t3.medium"

    # ── RDS (on-demand, Multi-AZ doubles instance cost) ────────────────────────
    RDS_HOURLY: Dict[str, float] = {
        "db.t3.micro":   0.017,
        "db.t3.small":   0.034,
        "db.t3.medium":  0.068,
        "db.t3.large":   0.136,
        "db.r5.large":   0.240,
        "db.r5.xlarge":  0.480,
    }
    RDS_DEFAULT_INSTANCE = "db.t3.medium"
    RDS_STORAGE_PER_GB_MONTH: float = 0.115   # gp2 SSD
    RDS_BACKUP_PER_GB_MONTH: float = 0.095

    # ── EKS ───────────────────────────────────────────────────────────────────
    EKS_CONTROL_PLANE_HOURLY: float = 0.10   # ~$73/month per cluster

    # ── Lambda (serverless compute) ───────────────────────────────────────────
    LAMBDA_REQUEST_PER_MILLION: float = 0.20
    LAMBDA_DURATION_PER_GB_SEC: float = 0.0000166667
    LAMBDA_FREE_GB_SECONDS: int = 400_000    # free tier per month

    # ── S3 (Standard storage, us-east-1) ─────────────────────────────────────
    S3_STORAGE_PER_GB_MONTH: float = 0.023
    S3_PUT_PER_1000: float = 0.005
    S3_GET_PER_1000: float = 0.0004

    # ── Load Balancer (ALB) ───────────────────────────────────────────────────
    ALB_HOURLY: float = 0.008         # base per hour
    ALB_LCU_HOURLY: float = 0.008     # one LCU assumed for low-to-medium traffic

    # ── API Gateway ───────────────────────────────────────────────────────────
    API_GATEWAY_PER_MILLION_REQUESTS: float = 3.50

    # ── ElastiCache (Redis, on-demand) ────────────────────────────────────────
    ELASTICACHE_HOURLY: Dict[str, float] = {
        "cache.t3.micro":  0.017,
        "cache.t3.small":  0.034,
        "cache.t3.medium": 0.068,
    }
    ELASTICACHE_DEFAULT_INSTANCE = "cache.t3.micro"

    # ── DynamoDB (provisioned mode) ───────────────────────────────────────────
    DYNAMODB_RCU_MONTH: float = 0.25    # per RCU/month
    DYNAMODB_WCU_MONTH: float = 1.25    # per WCU/month
    DYNAMODB_STORAGE_PER_GB: float = 0.25

    # ── Aurora Serverless v2 ──────────────────────────────────────────────────
    AURORA_SERVERLESS_ACU_HOUR: float = 0.06    # per ACU-hour

    # ── Data transfer (outbound to internet, after 100 GB/month free) ─────────
    DATA_TRANSFER_PER_GB: float = 0.09

    # Flat monthly data transfer estimates by scalability tier (practical model:
    # includes cross-AZ + outbound traffic; first 100 GB free tier not deducted
    # to avoid underestimating real-world bills).
    DATA_TRANSFER_MONTHLY: Dict[str, float] = {
        "low":    2.00,
        "medium": 8.00,
        "high":  22.00,
    }

    # ── CloudWatch (standard monitoring + log ingestion) ─────────────────────
    CLOUDWATCH_FLAT: float = 7.50

    # ── Convenience factory methods ───────────────────────────────────────────

    @classmethod
    def ec2_monthly(cls, instance_type: str, count: int = 1) -> float:
        hourly = cls.EC2_HOURLY.get(instance_type, cls.EC2_HOURLY[cls.EC2_DEFAULT_INSTANCE])
        return round(hourly * _HOURS_PER_MONTH * count, 2)

    @classmethod
    def rds_monthly(
        cls,
        instance_type: str,
        multi_az: bool = False,
        storage_gb: int = 20,
        backup_gb: int = 10,
    ) -> float:
        hourly = cls.RDS_HOURLY.get(instance_type, cls.RDS_HOURLY[cls.RDS_DEFAULT_INSTANCE])
        multiplier = 2 if multi_az else 1
        instance_cost = hourly * _HOURS_PER_MONTH * multiplier
        storage_cost = storage_gb * cls.RDS_STORAGE_PER_GB_MONTH
        backup_cost = backup_gb * cls.RDS_BACKUP_PER_GB_MONTH
        return round(instance_cost + storage_cost + backup_cost, 2)

    @classmethod
    def eks_control_plane_monthly(cls) -> float:
        return round(cls.EKS_CONTROL_PLANE_HOURLY * _HOURS_PER_MONTH, 2)

    @classmethod
    def alb_monthly(cls) -> float:
        return round((cls.ALB_HOURLY + cls.ALB_LCU_HOURLY) * _HOURS_PER_MONTH, 2)

    @classmethod
    def api_gateway_monthly(cls, million_requests: float = 1.0) -> float:
        return round(cls.API_GATEWAY_PER_MILLION_REQUESTS * million_requests, 2)

    @classmethod
    def elasticache_monthly(cls, instance_type: str = "") -> float:
        key = instance_type or cls.ELASTICACHE_DEFAULT_INSTANCE
        hourly = cls.ELASTICACHE_HOURLY.get(key, cls.ELASTICACHE_HOURLY[cls.ELASTICACHE_DEFAULT_INSTANCE])
        return round(hourly * _HOURS_PER_MONTH, 2)

    @classmethod
    def s3_monthly(
        cls,
        storage_gb: float = 10.0,
        put_k_requests: float = 10.0,
        get_k_requests: float = 50.0,
    ) -> float:
        storage = storage_gb * cls.S3_STORAGE_PER_GB_MONTH
        requests = put_k_requests * cls.S3_PUT_PER_1000 + get_k_requests * cls.S3_GET_PER_1000
        return round(storage + requests, 2)

    @classmethod
    def lambda_monthly(
        cls,
        million_requests: float = 0.5,
        avg_duration_ms: float = 300,
        memory_mb: float = 256,
    ) -> float:
        request_cost = million_requests * cls.LAMBDA_REQUEST_PER_MILLION
        total_gb_seconds = (
            million_requests * 1_000_000
            * (avg_duration_ms / 1000)
            * (memory_mb / 1024)
        )
        billable_gb_seconds = max(0.0, total_gb_seconds - cls.LAMBDA_FREE_GB_SECONDS)
        duration_cost = billable_gb_seconds * cls.LAMBDA_DURATION_PER_GB_SEC
        return round(request_cost + duration_cost, 2)


# ── Agent ─────────────────────────────────────────────────────────────────────


class CostEstimationAgent(EnhancedBaseAgent):
    """
    Produces AWS-inspired monthly cost estimations from an infrastructure
    blueprint generated by PlannerAgent.

    Inherits EnhancedBaseAgent — gains:
    • ``self.memory``  (AgentMemory — caches results per blueprint hash)
    • ``self.validation`` (ValidationService)
    • ``react_loop()`` (used for LLM-enhanced optimization tips)

    The cost breakdown itself is always deterministic: identical blueprints
    always produce identical numbers, making the agent fully testable without
    any LLM or network calls.
    """

    PRICING_MODEL_VERSION = "aws-simplified-v1"

    def __init__(self) -> None:
        super().__init__(name="CostEstimationAgent", max_react_iterations=2)
        self.llm = LLMService()

    # ── Public interface ──────────────────────────────────────────────────────

    def run(
        self,
        plan: Dict[str, Any],
        application_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Estimate monthly AWS cloud cost for the given plan.

        Parameters
        ----------
        plan:
            Output of ``PlannerAgent.run()`` — must contain
            ``infrastructure_blueprint``.
        application_profile:
            Optional output of ``ApplicationProfilerService.build_profile()``
            — used to refine instance sizing and auto-scaling node counts.

        Returns
        -------
        dict with a single ``"cost_estimation"`` key whose value matches the
        schema documented at the top of this module.
        """
        blueprint: Dict[str, Any] = plan.get("infrastructure_blueprint") or {}
        profile: Dict[str, Any] = application_profile or {}

        # Step 1 — deterministic pricing (no LLM, always succeeds)
        breakdown, assumptions = self._compute_cost_breakdown(blueprint, profile)
        monthly_total = round(sum(breakdown.values()), 2)
        cost_profile = self._classify_cost_profile(monthly_total)
        rule_tips = self._rule_based_tips(blueprint, breakdown, profile)

        # Step 2 — optional LLM enrichment for contextualized tips
        optimization_tips = self._get_llm_optimization_tips(
            blueprint=blueprint,
            breakdown=breakdown,
            monthly_total=monthly_total,
            cost_profile=cost_profile,
            fallback_tips=rule_tips,
        )

        cost_estimation = {
            "monthly_cost": monthly_total,
            "breakdown": breakdown,
            "cost_profile": cost_profile,
            "assumptions": assumptions,
            "optimization_tips": optimization_tips,
            "pricing_model_version": self.PRICING_MODEL_VERSION,
        }

        self._log.info(
            "[CostEstimationAgent] Estimated cost: $%.2f/month (%s, architecture=%s)",
            monthly_total,
            cost_profile,
            blueprint.get("architecture_style", "unknown"),
        )

        return {"cost_estimation": cost_estimation}

    # ── Deterministic pricing engine ──────────────────────────────────────────

    def _compute_cost_breakdown(
        self,
        blueprint: Dict[str, Any],
        profile: Dict[str, Any],
    ) -> Tuple[Dict[str, float], List[str]]:
        """
        Pure arithmetic cost breakdown — no LLM, no side effects.

        Returns
        -------
        (breakdown, assumptions)
            breakdown   — ``{service_name: usd_per_month}``
            assumptions — list of human-readable calculation notes
        """
        arch = blueprint.get("architecture_style") or "monolith"
        compute = blueprint.get("compute") or {}
        database = blueprint.get("database") or {}
        networking = blueprint.get("networking") or {}
        storage = blueprint.get("storage") or {}
        cache = blueprint.get("cache")
        scaling = blueprint.get("scaling") or {}
        scalability = profile.get("scalability_level") or "medium"

        breakdown: Dict[str, float] = {}
        assumptions: List[str] = [
            "Based on AWS public pricing documentation (simplified model)",
            f"Assuming {_HOURS_PER_MONTH} hours/month (AWS standard)",
            "Using on-demand pricing baseline (no Reserved Instances or Savings Plans applied)",
            "Region: us-east-1 (N. Virginia)",
            "Prices in USD, taxes excluded",
        ]

        if arch == "serverless":
            self._add_serverless_costs(breakdown, assumptions, compute, database, networking)
        elif arch == "microservices":
            self._add_microservices_costs(
                breakdown, assumptions, compute, database, networking, cache, scaling, scalability
            )
        else:
            # monolith / unknown
            self._add_monolith_costs(breakdown, assumptions, compute, database, networking, scalability)

        # S3 — present in all architectures
        s3_gb = 10.0
        breakdown["s3"] = _AwsPricingModel.s3_monthly(storage_gb=s3_gb)
        assumptions.append(f"S3: {s3_gb:.0f} GB standard storage + typical PUT/GET volume")

        # CloudWatch — always included
        breakdown["cloudwatch"] = _AwsPricingModel.CLOUDWATCH_FLAT
        assumptions.append("CloudWatch: standard metrics + log ingestion (flat ~$7.50/month)")

        return breakdown, assumptions

    # ── Architecture-specific cost builders ───────────────────────────────────

    def _add_monolith_costs(
        self,
        breakdown: Dict[str, float],
        assumptions: List[str],
        compute: Dict[str, Any],
        database: Dict[str, Any],
        networking: Dict[str, Any],
        scalability: str,
    ) -> None:
        # ECS on EC2 — single instance
        instance_type = compute.get("instance_type") or (
            "t3.small" if scalability == "low" else "t3.medium"
        )
        breakdown["compute"] = _AwsPricingModel.ec2_monthly(instance_type, count=1)
        assumptions.append(
            f"Compute (ECS/EC2): 1x {instance_type} running {_HOURS_PER_MONTH}h/month"
        )

        # RDS
        self._add_rds_cost(breakdown, assumptions, database, scalability)

        # ALB
        if networking.get("load_balancer") in ("ALB", "NLB"):
            breakdown["load_balancer"] = _AwsPricingModel.alb_monthly()
            assumptions.append("Load Balancer: 1x ALB (~1 LCU average traffic)")

        # Data transfer
        dt_cost = _AwsPricingModel.DATA_TRANSFER_MONTHLY.get(scalability, 8.00)
        breakdown["data_transfer"] = dt_cost
        assumptions.append(
            f"Data Transfer: flat estimate for '{scalability}' scalability tier "
            f"(includes cross-AZ + outbound)"
        )

    def _add_microservices_costs(
        self,
        breakdown: Dict[str, float],
        assumptions: List[str],
        compute: Dict[str, Any],
        database: Dict[str, Any],
        networking: Dict[str, Any],
        cache: Optional[Dict[str, Any]],
        scaling: Dict[str, Any],
        scalability: str,
    ) -> None:
        # EKS control plane — always required
        breakdown["eks_control_plane"] = _AwsPricingModel.eks_control_plane_monthly()
        assumptions.append(
            "EKS: control plane at $0.10/hour = "
            f"${_AwsPricingModel.eks_control_plane_monthly():.2f}/month"
        )

        # Worker nodes
        node_type = compute.get("node_type") or "t3.medium"
        min_nodes: int = int(compute.get("min_nodes") or (3 if scalability == "high" else 2))
        breakdown["eks_worker_nodes"] = _AwsPricingModel.ec2_monthly(node_type, count=min_nodes)
        assumptions.append(
            f"EKS workers: {min_nodes}x {node_type} (minimum cluster size, on-demand)"
        )

        # RDS
        self._add_rds_cost(breakdown, assumptions, database, scalability)

        # ALB (microservices ingress)
        if networking.get("load_balancer") == "ALB":
            breakdown["load_balancer"] = _AwsPricingModel.alb_monthly()
            assumptions.append("Load Balancer: 1x ALB (microservices ingress controller)")

        # ElastiCache (Redis)
        if cache:
            engine = str(cache.get("engine") or "").lower()
            if engine in ("redis", "memcached"):
                breakdown["elasticache"] = _AwsPricingModel.elasticache_monthly()
                assumptions.append(
                    f"ElastiCache: 1x {_AwsPricingModel.ELASTICACHE_DEFAULT_INSTANCE} "
                    f"({engine}) node"
                )

        # Data transfer — higher for microservices (service mesh + inter-AZ)
        dt_cost = _AwsPricingModel.DATA_TRANSFER_MONTHLY.get(scalability, 8.00)
        # Add networking overhead for microservices inter-service traffic
        dt_cost_with_overhead = round(dt_cost * 1.5, 2)
        breakdown["data_transfer"] = dt_cost_with_overhead
        assumptions.append(
            f"Data Transfer: '{scalability}' tier + 50% microservices networking overhead "
            f"(inter-service + outbound)"
        )

    def _add_serverless_costs(
        self,
        breakdown: Dict[str, float],
        assumptions: List[str],
        compute: Dict[str, Any],
        database: Dict[str, Any],
        networking: Dict[str, Any],
    ) -> None:
        # Lambda
        breakdown["lambda"] = _AwsPricingModel.lambda_monthly(
            million_requests=0.5,
            avg_duration_ms=300,
            memory_mb=256,
        )
        assumptions.append(
            "Lambda: ~500k requests/month, 300ms avg duration, 256MB memory "
            f"(400k GB-sec free tier applied)"
        )

        # API Gateway
        lb = str(networking.get("load_balancer") or "API Gateway")
        if "gateway" in lb.lower():
            breakdown["api_gateway"] = _AwsPricingModel.api_gateway_monthly(million_requests=0.5)
            assumptions.append("API Gateway: ~500k API calls/month at $3.50/million")

        # Database
        engine = str(database.get("engine") or "DynamoDB").lower()
        if "aurora" in engine and "serverless" in engine:
            avg_acu = 4
            acu_cost = avg_acu * _AwsPricingModel.AURORA_SERVERLESS_ACU_HOUR * _HOURS_PER_MONTH
            breakdown["database"] = round(acu_cost, 2)
            assumptions.append(
                f"Aurora Serverless v2: avg {avg_acu} ACU x "
                f"$0.06/ACU-hour x {_HOURS_PER_MONTH}h"
            )
        else:
            # DynamoDB minimal provisioned capacity
            rcu, wcu, storage = 5, 5, 5
            db_cost = (
                rcu * _AwsPricingModel.DYNAMODB_RCU_MONTH
                + wcu * _AwsPricingModel.DYNAMODB_WCU_MONTH
                + storage * _AwsPricingModel.DYNAMODB_STORAGE_PER_GB
            )
            breakdown["database"] = round(db_cost, 2)
            assumptions.append(
                f"DynamoDB: {rcu} RCU + {wcu} WCU (provisioned) + {storage} GB storage"
            )

        # Data transfer (minimal for serverless)
        breakdown["data_transfer"] = _AwsPricingModel.DATA_TRANSFER_MONTHLY["low"]
        assumptions.append("Data Transfer: minimal outbound (serverless low-traffic baseline)")

    def _add_rds_cost(
        self,
        breakdown: Dict[str, float],
        assumptions: List[str],
        database: Dict[str, Any],
        scalability: str,
    ) -> None:
        if not database:
            return

        deployment = str(database.get("deployment") or "").lower()
        multi_az = "multi-az" in deployment or "multi_az" in deployment

        # Instance type driven by scalability
        instance_type_map = {
            "high":   "db.r5.large",
            "medium": "db.t3.medium",
            "low":    "db.t3.small",
        }
        instance_type = instance_type_map.get(scalability, "db.t3.medium")
        storage_gb = 50 if scalability == "high" else 20

        breakdown["database"] = _AwsPricingModel.rds_monthly(
            instance_type=instance_type,
            multi_az=multi_az,
            storage_gb=storage_gb,
        )

        engine = database.get("engine") or "PostgreSQL"
        az_label = "Multi-AZ" if multi_az else "Single-AZ"
        assumptions.append(
            f"RDS {engine}: {instance_type} {az_label}, {storage_gb} GB gp2 storage"
            + (" (instance cost x2 for Multi-AZ)" if multi_az else "")
        )

    # ── Cost profile classifier ───────────────────────────────────────────────

    @staticmethod
    def _classify_cost_profile(monthly_total: float) -> str:
        if monthly_total < 100:
            return "startup"
        if monthly_total < 500:
            return "small_production"
        if monthly_total < 2_000:
            return "medium_production"
        return "enterprise"

    # ── Rule-based optimization tips ──────────────────────────────────────────

    @staticmethod
    def _rule_based_tips(
        blueprint: Dict[str, Any],
        breakdown: Dict[str, float],
        profile: Dict[str, Any],
    ) -> List[str]:
        tips: List[str] = []
        arch = blueprint.get("architecture_style") or "monolith"
        scalability = profile.get("scalability_level") or "medium"
        total = sum(breakdown.values()) or 1.0

        db_cost = breakdown.get("database", 0.0)
        compute_cost = (
            breakdown.get("compute")
            or breakdown.get("eks_worker_nodes")
            or breakdown.get("lambda")
            or 0.0
        )

        # Architecture-specific tips
        if arch == "microservices":
            tips.append(
                "Consider 1-year Reserved Instances for EKS worker nodes — "
                "RI pricing reduces EC2 costs by ~40% vs on-demand for stable workloads."
            )
            tips.append(
                "Use Cluster Autoscaler + EC2 Spot Instances for fault-tolerant pods "
                "to reduce worker node costs by up to 70%."
            )

        elif arch == "serverless":
            tips.append(
                "Monitor Lambda cold-start frequency. Apply Provisioned Concurrency only "
                "to latency-sensitive functions — over-provisioning adds unnecessary cost."
            )
            tips.append(
                "Use DynamoDB on-demand mode for uneven traffic patterns; switch to "
                "provisioned with Auto Scaling once traffic is predictable."
            )

        else:  # monolith
            if scalability == "high":
                tips.append(
                    "High-scalability monolith: consider Graviton2 instances (t4g/m6g) "
                    "for a ~20% cost reduction at equivalent performance."
                )

        # Database tips
        if db_cost > 0 and arch != "serverless":
            tips.append(
                "Evaluate RDS 1-year Reserved Instances for steady-state workloads — "
                "RI pricing saves 30-40% compared to on-demand RDS."
            )
            if (blueprint.get("database") or {}).get("deployment", "").lower().find("multi") != -1:
                tips.append(
                    "RDS Multi-AZ doubles instance cost. For non-production environments, "
                    "switch to Single-AZ to cut database spend in half."
                )

        # Compute dominates the bill
        if compute_cost / total > 0.45:
            tips.append(
                "Compute represents >45% of the total bill. Run AWS Compute Optimizer "
                "to identify right-sizing opportunities before committing to Reserved Instances."
            )

        # Universal tips
        tips.append(
            "Enable S3 Intelligent-Tiering for objects not accessed daily — "
            "can reduce S3 storage costs by up to 40% at no operational overhead."
        )
        tips.append(
            "Set CloudWatch log retention policies (e.g., 30 days) to cap log "
            "storage costs as application log volume grows."
        )

        return tips

    # ── LLM-enhanced optimization tips via ReAct ──────────────────────────────

    def _get_llm_optimization_tips(
        self,
        blueprint: Dict[str, Any],
        breakdown: Dict[str, float],
        monthly_total: float,
        cost_profile: str,
        fallback_tips: List[str],
    ) -> List[str]:
        """
        Call the LLM (via the inherited ReAct loop) to generate contextualized
        FinOps recommendations.  Returns ``fallback_tips`` on any failure.
        """
        system_prompt = (
            "You are a senior FinOps cloud engineer specializing in AWS cost optimization. "
            "Given an infrastructure blueprint and its cost breakdown, produce 4-5 actionable, "
            "specific cost optimization tips that reference the actual services and numbers. "
            'Respond with ONLY a valid JSON object: {"optimization_tips": ["tip1", "tip2", ...]}. '
            "No markdown, no prose, no code fences."
        )

        breakdown_summary = ", ".join(
            f"{k}: ${v:.2f}"
            for k, v in sorted(breakdown.items(), key=lambda x: -x[1])
        )
        compute_info = blueprint.get("compute") or {}
        db_info = blueprint.get("database") or {}

        user_prompt = (
            f"Architecture style: {blueprint.get('architecture_style', 'monolith')}\n"
            f"Monthly total: ${monthly_total:.2f} ({cost_profile})\n"
            f"Cost breakdown (highest first): {breakdown_summary}\n"
            f"Compute: type={compute_info.get('type', 'EC2')}, "
            f"instance={compute_info.get('instance_type') or compute_info.get('node_type', 'N/A')}\n"
            f"Database: engine={db_info.get('engine', 'N/A')}, "
            f"deployment={db_info.get('deployment', 'N/A')}\n\n"
            "Provide 4-5 AWS-specific, actionable cost optimization tips for this setup."
        )

        try:
            response = self.react_loop(
                llm=self.llm,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                evaluate_fn=self._evaluate_tips_quality,
                temperature=0.2,
                max_tokens=600,
            )
            tips = response.get("optimization_tips") or []
            if isinstance(tips, list) and len(tips) >= 2:
                return [str(t) for t in tips]
        except Exception as exc:
            self._log.warning(
                "[CostEstimationAgent] LLM optimization tips failed (%s) — using rule-based tips.",
                exc,
            )

        return fallback_tips

    # ── ReAct quality evaluator ───────────────────────────────────────────────

    def _evaluate_tips_quality(self, response: Dict[str, Any]) -> List[str]:
        """Validate that the LLM returned a well-formed optimization_tips array."""
        issues = self._default_evaluate(response)
        tips = response.get("optimization_tips")
        if not tips or not isinstance(tips, list):
            issues.append("Response must contain 'optimization_tips' as a non-empty JSON array")
        elif len(tips) < 2:
            issues.append("At least 2 optimization tips are required")
        return issues
