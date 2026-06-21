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
from backend.app.services.terraform_generation.utils.naming import (
    AWS_NAME_LIMITS,
    sanitize_aws_name,
)


_INVALID_NAME_CHARS_RE = re.compile(r"[^a-z0-9-]")
_MULTI_HYPHEN_RE = re.compile(r"-{2,}")
_LEADING_NON_ALPHA_RE = re.compile(r"^[^a-z]+")

# Tightest common AWS resource-name ceiling. ALB names cap at 32 chars, RDS
# identifiers at 63 — 32 is the universally safe bound for a name that the
# templates suffix into "${project_name}-alb", "${project_name}-db", etc.
TERRAFORM_NAME_MAX_LENGTH = 32


def sanitize_terraform_name(
    raw: Optional[str],
    *,
    fallback: str = "app",
    max_length: int = TERRAFORM_NAME_MAX_LENGTH,
) -> str:
    """
    Coerce an arbitrary repo/project string into an AWS-safe resource name.

    The result satisfies the *union* of the ALB, RDS, ECS and ELB naming rules,
    so it is a safe prefix for every name the Terraform templates derive from it
    (ALB ``${project_name}-alb``, RDS ``${project_name}-db``, …):

      • lowercased
      • only ``[a-z0-9-]``
      • starts with a letter      — RDS identifiers and ALB names reject a
                                    leading digit or hyphen
      • no consecutive hyphens    — RDS rejects ``--``
      • no leading/trailing hyphen
      • 1..``max_length`` chars    — default 32, the tightest common ceiling (ALB)

    Never raises: malformed input is coerced, not rejected — this is naming, not
    policy. When nothing usable survives sanitization, ``fallback`` is used.
    """
    candidate = (raw or "").strip().lower()
    # 1. Replace every illegal character with a hyphen, collapse runs, trim ends.
    candidate = _INVALID_NAME_CHARS_RE.sub("-", candidate)
    candidate = _MULTI_HYPHEN_RE.sub("-", candidate).strip("-")
    # 2. Must start with a letter — drop any leading digits/hyphens.
    candidate = _LEADING_NON_ALPHA_RE.sub("", candidate)
    # 3. If nothing usable remains, derive from the fallback (same rules).
    if not candidate:
        candidate = _INVALID_NAME_CHARS_RE.sub("-", (fallback or "app").lower())
        candidate = _MULTI_HYPHEN_RE.sub("-", candidate).strip("-")
        candidate = _LEADING_NON_ALPHA_RE.sub("", candidate) or "app"
    # 4. Enforce the length ceiling, re-stripping any hyphen the cut exposed.
    candidate = candidate[:max_length].rstrip("-")
    return candidate or "app"


def _normalize_project_name(raw: Optional[str], task_id: Optional[str]) -> str:
    """
    Derive a safe project name from project metadata, falling back to task_id.

    Delegates to :func:`sanitize_terraform_name` so every consumer (templates
    and any LLM injection) sees an ALB/RDS-compliant name.
    """
    return sanitize_terraform_name(raw or task_id, fallback="devsecops-app")


def _build_resource_names(project: str) -> Dict[str, str]:
    """Pre-compute every length-constrained AWS resource name from ``project``.

    Templates must NOT build constrained names by string-suffixing
    ``var.project_name`` in HCL — Terraform has no awareness of the per-resource
    length ceilings, so ``"${project_name}-alb"`` happily overflows ALB's 32-char
    limit at plan time. Instead we resolve each name HERE, bounded to its
    resource's ceiling via :func:`sanitize_aws_name` (suffix reserved first,
    base truncated with a uniqueness hash when needed), and inject the result as
    a literal the template renders verbatim.

    Keys are a superset across architectures (monolith / microservices /
    serverless); a template only references the ones it needs, and unused keys
    are harmless extra context.
    """
    return {
        # ── Hard 32-char ceilings — the ALB/Target-Group plan failure ──────────
        "alb_name": sanitize_aws_name(project, "-alb", AWS_NAME_LIMITS["alb"]),
        "target_group_name": sanitize_aws_name(
            project, "-tg", AWS_NAME_LIMITS["target_group"]
        ),
        # ── ECS / ECR / IAM (monolith) — generous ceilings, bounded defensively ─
        "ecr_repository_name": sanitize_aws_name(
            project, "", AWS_NAME_LIMITS["ecr_repository"]
        ),
        "ecs_cluster_name": sanitize_aws_name(
            project, "-cluster", AWS_NAME_LIMITS["ecs_cluster"]
        ),
        "ecs_service_name": sanitize_aws_name(
            project, "-service", AWS_NAME_LIMITS["ecs_service"]
        ),
        "ecs_task_family": sanitize_aws_name(
            project, "", AWS_NAME_LIMITS["ecs_task_family"]
        ),
        "ecs_task_execution_role_name": sanitize_aws_name(
            project, "-ecs-task-execution", AWS_NAME_LIMITS["iam_role"]
        ),
        # ── RDS (63-char identifier) + DB subnet group (monolith/balanced) ─────
        "rds_identifier": sanitize_aws_name(
            project, "-db", AWS_NAME_LIMITS["rds_instance"]
        ),
        "db_subnet_group_name": sanitize_aws_name(
            project, "-db-subnet", AWS_NAME_LIMITS["db_subnet_group"]
        ),
        # ── EKS (microservices) — cluster (100), IAM roles (64), node group (63)
        "eks_cluster_name": sanitize_aws_name(
            project, "", AWS_NAME_LIMITS["eks_cluster"]
        ),
        "eks_cluster_role_name": sanitize_aws_name(
            project, "-eks-cluster", AWS_NAME_LIMITS["iam_role"]
        ),
        "eks_node_role_name": sanitize_aws_name(
            project, "-eks-node", AWS_NAME_LIMITS["iam_role"]
        ),
        "eks_node_group_name": sanitize_aws_name(
            project, "-ng", AWS_NAME_LIMITS["eks_node_group"]
        ),
        # ── Lambda + API Gateway + S3 (serverless) — 64 / 128 / 63 ─────────────
        "lambda_function_name": sanitize_aws_name(
            project, "", AWS_NAME_LIMITS["lambda_function"]
        ),
        "lambda_role_name": sanitize_aws_name(
            project, "-lambda-role", AWS_NAME_LIMITS["iam_role"]
        ),
        "apigw_name": sanitize_aws_name(project, "-api", AWS_NAME_LIMITS["apigateway"]),
        "lambda_code_bucket_name": sanitize_aws_name(
            project, "-lambda-code", AWS_NAME_LIMITS["s3_bucket"]
        ),
    }


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

    # Pre-resolved, length-bounded resource names (ALB/TG/IAM/ECS/ECR/RDS/EKS/
    # Lambda/S3). Computed once here so HCL never suffixes project_name past an
    # AWS ceiling. See _build_resource_names.
    resource_names = _build_resource_names(project)

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
        # ── Pre-resolved AWS resource names (length-bounded) ─────────────
        **resource_names,

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
