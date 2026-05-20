"""
Variable context builder.

Converts a typed ``InfrastructureBlueprint`` into a flat ``dict`` consumed by
Jinja2 templates. This is the ONLY place where blueprint fields are mapped to
HCL variable names — keep it small and explicit so a reviewer can audit the
full surface in one screenful.

Why a separate module
---------------------
Templates must remain dumb. They cannot perform conditional defaulting (e.g.
"use t3.medium if compute.instance_type is empty") because that hides bugs
behind silent fallbacks — the exact pathology the audit eliminated. All
defaulting/coercion happens here, in one auditable place.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from backend.app.schemas.blueprint import InfrastructureBlueprint


_SAFE_NAME_RE = re.compile(r"[^a-z0-9-]")


def _normalize_project_name(raw: Optional[str], task_id: Optional[str]) -> str:
    """
    AWS resource names must be lowercase, alphanumeric + hyphens, 3-63 chars.
    Fall back to the task_id if no name is provided. Never raises — bad
    characters are stripped, not rejected, because this is naming, not policy.
    """
    candidate = (raw or task_id or "devsecops-app").lower()
    candidate = _SAFE_NAME_RE.sub("-", candidate).strip("-")
    if len(candidate) < 3:
        candidate = (candidate + "-app")[:32]
    return candidate[:32]  # AWS resource name ceilings vary; 32 is universally safe.


def _allocate_subnet_cidrs(
    vpc_cidr: str,
    az_count: int,
) -> tuple[List[str], List[str]]:
    """
    Deterministic /24 allocation inside a /16 VPC.

    Public subnets occupy 10.0.0.0/24 .. 10.0.(az_count-1)/24,
    private subnets occupy 10.0.10.0/24 .. 10.0.(10+az_count-1)/24.

    The /16 assumption matches the default we hand templates. If a caller
    overrides vpc_cidr to a non-/16, they assume responsibility for the
    subnet allocation themselves.
    """
    base = vpc_cidr.split("/")[0].rsplit(".", 2)[0]  # "10.0"
    public = [f"{base}.{i}.0/24" for i in range(az_count)]
    private = [f"{base}.{10 + i}.0/24" for i in range(az_count)]
    return public, private


def build_variable_context(
    blueprint: InfrastructureBlueprint,
    *,
    task_id: Optional[str] = None,
    project_name: Optional[str] = None,
    environment: str = "dev",
    container_port: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Build the flat dict passed to Jinja2 templates.

    Every key in the returned dict is documented and consumed by at least one
    template. Adding a new key here without a template consumer is a code
    smell — keep this surface minimal.
    """
    project = _normalize_project_name(project_name, task_id)

    # Multi-AZ: 2 AZs when enabled, 1 AZ otherwise. Keeps the topology
    # deterministic across renders.
    multi_az = blueprint.is_multi_az or blueprint.strategy_tier == "high_performance"
    az_count = 2 if multi_az else 1

    vpc_cidr = "10.0.0.0/16"
    public_cidrs, private_cidrs = _allocate_subnet_cidrs(vpc_cidr, az_count)

    # Compute sizing (typed accessor — no .get fallbacks).
    instance_type = blueprint.compute.effective_instance_type
    min_nodes = blueprint.compute.min_nodes or 1
    max_nodes = blueprint.compute.max_nodes or 1
    desired_count = max(min_nodes, 1)

    # Database (typed; None when blueprint did not request one).
    db = blueprint.database
    db_engine = (db.engine.lower() if db and db.engine else None)
    # Map blueprint engine name → AWS RDS engine string.
    rds_engine_map = {
        "postgresql": "postgres",
        "postgres": "postgres",
        "mysql": "mysql",
        "mariadb": "mariadb",
        "aurora": "aurora-postgresql",
    }
    rds_engine = rds_engine_map.get(db_engine, "postgres") if db else None
    # Conservative size; tier-aware in templates if desired.
    rds_instance_class = {
        "low_cost": "db.t3.micro",
        "balanced": "db.t3.small",
        "high_performance": "db.t3.medium",
    }.get(blueprint.strategy_tier or "balanced", "db.t3.small")

    redis_node_type = {
        "low_cost": "cache.t3.micro",
        "balanced": "cache.t3.small",
        "high_performance": "cache.t3.medium",
    }.get(blueprint.strategy_tier or "balanced", "cache.t3.small")

    return {
        # ── Naming / environment ─────────────────────────────────────────
        "project_name": project,
        "environment": environment,
        "aws_region": blueprint.aws_region,
        "strategy_tier": blueprint.strategy_tier or "balanced",
        "architecture_style": blueprint.architecture_style,

        # ── Networking ───────────────────────────────────────────────────
        "vpc_cidr": vpc_cidr,
        "az_count": az_count,
        "multi_az": multi_az,
        "public_subnet_cidrs": public_cidrs,
        "private_subnet_cidrs": private_cidrs,

        # ── Compute ──────────────────────────────────────────────────────
        "compute_type": blueprint.compute.type,
        "instance_type": instance_type,
        "min_nodes": min_nodes,
        "max_nodes": max_nodes,
        "desired_count": desired_count,
        "container_port": container_port or 8080,

        # ── Database ─────────────────────────────────────────────────────
        "enable_rds": db is not None,
        "rds_engine": rds_engine,
        "rds_instance_class": rds_instance_class,
        "rds_multi_az": multi_az,
        "rds_read_replicas": bool(db and db.read_replicas),

        # ── Cache ────────────────────────────────────────────────────────
        "enable_redis": blueprint.cache is not None,
        "redis_node_type": redis_node_type,

        # ── Scaling ──────────────────────────────────────────────────────
        "auto_scaling": blueprint.scaling.auto_scaling,
        "scaling_strategy": blueprint.scaling.strategy,

        # ── Load balancer ────────────────────────────────────────────────
        "load_balancer_type": blueprint.networking.load_balancer,
    }
