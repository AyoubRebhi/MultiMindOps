"""
Typed Infrastructure Blueprint contract.

Single source of truth for the data structure that flows:

    PlannerAgent
        ──► ArchitectureDecisionAgent
                ──► resume_with_selected_plan (orchestrator)
                        ──► TerraformAgent
                        ──► KubernetesAgent

Prior to this module, every agent passed a free-form ``Dict[str, Any]`` and
each consumer used a different shape — PlannerAgent emits ``compute.type``
but TerraformAgent was reading top-level ``compute_type``; PlannerAgent never
populated ``aws_region``/``min_nodes``/``max_nodes`` yet TerraformAgent
treated them as required.  Silent ``.get(default)`` masked every drift.

This module enforces the shape with Pydantic v2. Agents call
``InfrastructureBlueprint.model_validate(payload)`` at every boundary and
raise ``BlueprintContractError`` on failure rather than emitting fallbacks.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ── Enums (typed Literals) ────────────────────────────────────────────────────

ArchitectureStyle = Literal["monolith", "microservices", "serverless"]

# Common LLM synonyms for the three canonical architecture styles. Lowercase
# keys, dashes and underscores normalized to underscores at lookup time.
# Keep additions conservative — anything not in this map falls through to the
# Literal validator and raises (which is what we want for genuinely unknown
# values; we only want to absorb harmless paraphrases).
_ARCHITECTURE_STYLE_SYNONYMS: Dict[str, str] = {
    # → monolith
    "monolithic":          "monolith",
    "layered":             "monolith",
    "n_tier":              "monolith",
    "n-tier":              "monolith",
    "multi_tier":          "monolith",
    "multi-tier":          "monolith",
    "three_tier":          "monolith",
    "three-tier":          "monolith",
    "single_tier":         "monolith",
    "single-tier":         "monolith",
    "mvc":                 "monolith",
    "client_server":       "monolith",
    "client-server":       "monolith",
    # → microservices
    "microservice":        "microservices",
    "micro_services":      "microservices",
    "micro-services":      "microservices",
    "distributed":         "microservices",
    "event_driven":        "microservices",
    "event-driven":        "microservices",
    "soa":                 "microservices",
    "service_oriented":    "microservices",
    "service-oriented":    "microservices",
    # → serverless
    "faas":                "serverless",
    "function":            "serverless",
    "functions":           "serverless",
    "function_as_a_service": "serverless",
    "function-as-a-service": "serverless",
    "lambda":              "serverless",
}


def _normalize_architecture_style(raw: Any) -> Any:
    """Map common LLM paraphrases onto the strict ArchitectureStyle Literal.

    Pass-through for anything that already matches the canonical set, or for
    non-string inputs (let the Literal validator generate the error). The
    point is to absorb harmless naming variation without widening the type.
    """
    if not isinstance(raw, str):
        return raw
    key = raw.strip().lower()
    if key in ("monolith", "microservices", "serverless"):
        return key
    return _ARCHITECTURE_STYLE_SYNONYMS.get(key, raw)
ComputeType = Literal["ECS", "EKS", "Lambda", "EC2"]
StrategyTier = Literal["low_cost", "balanced", "high_performance"]
ScalingStrategy = Literal[
    "vertical",
    "horizontal",
    "vertical+horizontal",
    "fully_managed",
]
LoadBalancerType = Literal["ALB", "NLB", "API Gateway", "none"]

# AWS region pattern — coarse but enough to reject obvious typos like "us_east_1".
_AWS_REGION_RE = re.compile(r"^[a-z]{2}-[a-z]+-\d+$")


# ── Sub-models ────────────────────────────────────────────────────────────────


class ComputeConfig(BaseModel):
    """
    Compute layer. Field set depends on ``type``:

    * ECS / EC2   → ``instance_type`` required
    * EKS         → ``node_type`` + ``min_nodes`` + ``max_nodes`` required
    * Lambda      → ``runtime`` required, sizing fields ignored
    """

    model_config = ConfigDict(extra="allow")  # tolerate legacy keys without raising

    type: ComputeType
    instance_type: Optional[str] = None
    node_type: Optional[str] = None
    min_nodes: Optional[int] = Field(default=None, ge=1, le=100)
    max_nodes: Optional[int] = Field(default=None, ge=1, le=500)
    runtime: Optional[str] = None

    @model_validator(mode="after")
    def _enforce_type_shape(self) -> "ComputeConfig":
        if self.type in ("ECS", "EC2"):
            if not self.instance_type:
                raise ValueError(
                    f"ComputeConfig(type={self.type}) requires 'instance_type'"
                )
        elif self.type == "EKS":
            if not self.node_type:
                raise ValueError("ComputeConfig(type=EKS) requires 'node_type'")
            if self.min_nodes is None or self.max_nodes is None:
                raise ValueError(
                    "ComputeConfig(type=EKS) requires 'min_nodes' and 'max_nodes'"
                )
            if self.min_nodes > self.max_nodes:
                raise ValueError("min_nodes must be <= max_nodes")
        elif self.type == "Lambda":
            if not self.runtime:
                raise ValueError("ComputeConfig(type=Lambda) requires 'runtime'")
        return self

    @property
    def effective_instance_type(self) -> str:
        """Single accessor that TerraformAgent should use — never falls back silently."""
        if self.type == "EKS":
            if not self.node_type:
                raise ValueError("EKS compute is missing node_type")
            return self.node_type
        if self.type in ("ECS", "EC2"):
            if not self.instance_type:
                raise ValueError(f"{self.type} compute is missing instance_type")
            return self.instance_type
        if self.type == "Lambda":
            return "lambda"
        raise ValueError(f"Unknown compute type {self.type}")


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    engine: str
    deployment: str
    read_replicas: bool = False


class NetworkingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    vpc: bool = True
    multi_az: bool
    load_balancer: LoadBalancerType = "ALB"


class CacheConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    engine: str
    deployment: str


class ScalingConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    strategy: ScalingStrategy
    auto_scaling: bool


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    object_storage: str = "S3"
    block_storage: Optional[str] = None


# ── Root model ────────────────────────────────────────────────────────────────


class InfrastructureBlueprint(BaseModel):
    """
    Strict typed contract. Every agent boundary must validate against this.

    Two new fields the legacy free-form dict lacked:

    * ``aws_region`` — was implicitly defaulted by TerraformAgent. Now mandatory
      with a safe default so the contract is satisfied without silent magic.
    * ``strategy_tier`` — was lost in ``resume_with_selected_plan``. Now part
      of the blueprint itself so downstream agents do not depend on the plan
      wrapper carrying it.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    architecture_style: ArchitectureStyle
    compute: ComputeConfig
    database: Optional[DatabaseConfig] = None
    networking: NetworkingConfig
    scaling: ScalingConfig
    storage: StorageConfig = Field(default_factory=StorageConfig)
    cache: Optional[CacheConfig] = None

    # NEW — make formerly-implicit fields explicit & required.
    aws_region: str = "us-east-1"
    strategy_tier: Optional[StrategyTier] = None  # set by ArchitectureDecisionAgent

    @field_validator("architecture_style", mode="before")
    @classmethod
    def _normalize_architecture_style(cls, value: Any) -> Any:
        # Runs BEFORE the Literal validator so we can fold synonyms like
        # 'layered' or 'event-driven' into the three canonical values
        # without weakening the downstream type contract.
        return _normalize_architecture_style(value)

    @field_validator("aws_region")
    @classmethod
    def _validate_aws_region(cls, value: str) -> str:
        if not _AWS_REGION_RE.match(value):
            raise ValueError(
                f"aws_region '{value}' is not a valid AWS region identifier "
                "(expected pattern: {two-letter}-{name}-{digit}, e.g. us-east-1)"
            )
        return value

    @model_validator(mode="after")
    def _enforce_style_compute_consistency(self) -> "InfrastructureBlueprint":
        style = self.architecture_style
        ctype = self.compute.type
        valid = {
            "monolith": {"ECS", "EC2"},
            "microservices": {"EKS"},
            "serverless": {"Lambda"},
        }[style]
        if ctype not in valid:
            raise ValueError(
                f"architecture_style='{style}' is incompatible with compute.type='{ctype}' "
                f"(allowed: {sorted(valid)})"
            )
        return self

    # ── Convenience accessors used by TerraformAgent ─────────────────────────

    @property
    def is_multi_az(self) -> bool:
        """
        Single truth function. Replaces the substring search
        ``"high_performance" in plan.get("plan_id")`` that always returned False.
        """
        return bool(self.networking.multi_az)

    @property
    def needs_rds(self) -> bool:
        return self.database is not None

    @property
    def needs_redis(self) -> bool:
        return self.cache is not None

    @property
    def terraform_architecture_type(self) -> Literal["eks", "ecs", "serverless"]:
        """Folder selector for the upcoming template engine."""
        if self.compute.type == "EKS":
            return "eks"
        if self.compute.type == "Lambda":
            return "serverless"
        return "ecs"


# ── Helpers ────────────────────────────────────────────────────────────────────


def parse_blueprint(payload: Dict[str, Any]) -> InfrastructureBlueprint:
    """
    Validate ``payload`` against InfrastructureBlueprint.

    Raises BlueprintContractError (imported lazily to avoid a circular import)
    with the full Pydantic error list attached as metadata.
    """
    # Lazy import — errors module also imports from this file for typing.
    from backend.app.agents.errors import BlueprintContractError

    try:
        return InfrastructureBlueprint.model_validate(payload)
    except Exception as exc:  # ValidationError or anything else
        # Pull the structured error list out of pydantic if available.
        errors: List[Dict[str, Any]] = []
        if hasattr(exc, "errors") and callable(getattr(exc, "errors")):
            try:
                errors = exc.errors()  # type: ignore[assignment]
            except Exception:
                errors = []
        raise BlueprintContractError(
            message=f"Invalid InfrastructureBlueprint: {exc}",
            metadata={"validation_errors": errors, "raw_payload_keys": sorted(payload.keys())},
        ) from exc
