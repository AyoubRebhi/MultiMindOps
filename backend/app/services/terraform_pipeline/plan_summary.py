"""
Terraform plan → human-readable Infrastructure Summary.

After ``terraform plan -out=tfplan`` succeeds, this module turns the opaque
binary plan into something a non-Terraform user can read:

  1. :func:`generate_plan_json` — runs ``terraform show -json tfplan`` and
     returns the machine-readable plan as a JSON string.
  2. :func:`parse_resource_counts` — reads ``resource_changes`` and counts the
     resources that will be **created**, grouped by resource type.
  3. :func:`categorize_resources` — groups those types into human categories
     (Networking / Compute / Database / Storage / Security / Other).
  4. :func:`build_infrastructure_summary` — convenience wrapper over the three.

Deliberately out of scope (do NOT add here): cost estimation, drift analysis,
dependency graphs, security analysis. This module only answers the question
"what AWS infrastructure will be created?".
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Reuse the single source of truth for the plan filename so it can never drift
# from what ``terraform plan -out=...`` actually wrote.
from backend.app.services.terraform_pipeline.pipeline_service import (
    PLAN_OUTPUT_FILE,
    terraform_subprocess_env,
)

logger = logging.getLogger(__name__)


# ── plan.json generation ─────────────────────────────────────────────────────


async def generate_plan_json(
    artifact_dir: Path,
    *,
    timeout: int = 120,
) -> Optional[str]:
    """Run ``terraform show -json tfplan`` and return its stdout (the plan JSON).

    Returns ``None`` if the ``tfplan`` file is absent or ``terraform show``
    exits non-zero (e.g. a corrupt/partial plan). Raises :class:`RuntimeError`
    only if the ``terraform`` binary itself is missing — the same contract as
    the streaming runner, so the handler can treat env errors uniformly.
    """
    artifact_dir = Path(artifact_dir)
    plan_path = artifact_dir / PLAN_OUTPUT_FILE
    if not plan_path.exists():
        logger.warning("[PlanSummary] no %s in %s — nothing to show", PLAN_OUTPUT_FILE, artifact_dir)
        return None

    binary = shutil.which("terraform")
    if not binary:
        raise RuntimeError(
            "The 'terraform' binary was not found on PATH. "
            "Install Terraform to generate the plan summary."
        )

    proc = await asyncio.create_subprocess_exec(
        binary,
        "show",
        "-json",
        "-no-color",
        PLAN_OUTPUT_FILE,
        cwd=str(artifact_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=terraform_subprocess_env(),
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        logger.warning("[PlanSummary] terraform show timed out after %ss", timeout)
        return None

    if proc.returncode != 0:
        logger.warning(
            "[PlanSummary] terraform show exited %s: %s",
            proc.returncode,
            stderr_b.decode("utf-8", errors="replace")[:500],
        )
        return None

    return stdout_b.decode("utf-8", errors="replace")


# ── Resource type → (category, human label) catalog ──────────────────────────
#
# Singular labels only — the UI pluralises against the count. Unknown types
# fall back to :func:`_humanize` and land in the "Other" category, so the
# parser degrades gracefully rather than dropping resources.

_RESOURCE_CATALOG: Dict[str, Tuple[str, str]] = {
    # Networking
    "aws_vpc": ("Networking", "VPC"),
    "aws_subnet": ("Networking", "Subnet"),
    "aws_nat_gateway": ("Networking", "NAT Gateway"),
    "aws_internet_gateway": ("Networking", "Internet Gateway"),
    "aws_route_table": ("Networking", "Route Table"),
    "aws_route_table_association": ("Networking", "Route Table Association"),
    "aws_route": ("Networking", "Route"),
    "aws_eip": ("Networking", "Elastic IP"),
    "aws_vpc_endpoint": ("Networking", "VPC Endpoint"),
    "aws_lb": ("Networking", "Load Balancer"),
    "aws_alb": ("Networking", "Load Balancer"),
    "aws_lb_target_group": ("Networking", "Target Group"),
    "aws_alb_target_group": ("Networking", "Target Group"),
    "aws_lb_listener": ("Networking", "Load Balancer Listener"),
    "aws_alb_listener": ("Networking", "Load Balancer Listener"),
    "aws_apigatewayv2_api": ("Networking", "API Gateway"),
    "aws_apigatewayv2_stage": ("Networking", "API Gateway Stage"),
    "aws_apigatewayv2_integration": ("Networking", "API Gateway Integration"),
    "aws_apigatewayv2_route": ("Networking", "API Gateway Route"),
    "aws_api_gateway_rest_api": ("Networking", "API Gateway"),
    "aws_route53_zone": ("Networking", "DNS Zone"),
    "aws_route53_record": ("Networking", "DNS Record"),
    # Compute
    "aws_eks_cluster": ("Compute", "EKS Cluster"),
    "aws_eks_node_group": ("Compute", "EKS Node Group"),
    "aws_ecs_cluster": ("Compute", "ECS Cluster"),
    "aws_ecs_service": ("Compute", "ECS Service"),
    "aws_ecs_task_definition": ("Compute", "ECS Task Definition"),
    "aws_instance": ("Compute", "EC2 Instance"),
    "aws_launch_template": ("Compute", "Launch Template"),
    "aws_autoscaling_group": ("Compute", "Auto Scaling Group"),
    "aws_lambda_function": ("Compute", "Lambda Function"),
    "aws_lambda_permission": ("Compute", "Lambda Permission"),
    "aws_cloudwatch_log_group": ("Compute", "CloudWatch Log Group"),
    # Database
    "aws_db_instance": ("Database", "RDS Instance"),
    "aws_db_subnet_group": ("Database", "DB Subnet Group"),
    "aws_rds_cluster": ("Database", "Aurora Cluster"),
    "aws_rds_cluster_instance": ("Database", "Aurora Instance"),
    "aws_elasticache_cluster": ("Database", "ElastiCache Cluster"),
    "aws_elasticache_subnet_group": ("Database", "ElastiCache Subnet Group"),
    "aws_dynamodb_table": ("Database", "DynamoDB Table"),
    # Storage
    "aws_s3_bucket": ("Storage", "S3 Bucket"),
    "aws_s3_bucket_versioning": ("Storage", "S3 Bucket Versioning"),
    "aws_s3_bucket_policy": ("Storage", "S3 Bucket Policy"),
    "aws_s3_bucket_public_access_block": ("Storage", "S3 Public Access Block"),
    "aws_ebs_volume": ("Storage", "EBS Volume"),
    "aws_efs_file_system": ("Storage", "EFS File System"),
    "aws_ecr_repository": ("Storage", "ECR Repository"),
    # Security
    "aws_security_group": ("Security", "Security Group"),
    "aws_security_group_rule": ("Security", "Security Group Rule"),
    "aws_iam_role": ("Security", "IAM Role"),
    "aws_iam_policy": ("Security", "IAM Policy"),
    "aws_iam_role_policy": ("Security", "IAM Role Policy"),
    "aws_iam_role_policy_attachment": ("Security", "IAM Policy Attachment"),
    "aws_iam_instance_profile": ("Security", "Instance Profile"),
    "aws_kms_key": ("Security", "KMS Key"),
    "aws_kms_alias": ("Security", "KMS Alias"),
    "aws_secretsmanager_secret": ("Security", "Secrets Manager Secret"),
    "aws_secretsmanager_secret_version": ("Security", "Secret Version"),
}

# Stable display order. "Other" always renders last.
_CATEGORY_ORDER = ["Networking", "Compute", "Database", "Storage", "Security", "Other"]

# Provider prefixes stripped when humanising an unknown resource type.
_PROVIDER_PREFIXES = {
    "aws", "google", "azurerm", "azuread", "kubernetes",
    "helm", "null", "random", "tls", "local", "archive",
}


def _humanize(resource_type: str) -> str:
    """Turn ``aws_msk_cluster`` into ``Msk Cluster`` for unknown types."""
    name = resource_type
    if "_" in name:
        prefix, rest = name.split("_", 1)
        if prefix in _PROVIDER_PREFIXES:
            name = rest
    return name.replace("_", " ").title()


# ── Parsing ──────────────────────────────────────────────────────────────────


def parse_resource_counts(plan: Dict[str, Any]) -> Dict[str, int]:
    """Count resources to be **created**, grouped by resource type.

    Reads the top-level ``resource_changes`` array of ``terraform show -json``
    output. A resource counts if its ``change.actions`` includes ``"create"``
    (this captures plain creates and the create half of a replace). Deletes and
    no-ops are ignored — the goal is "what will be created".
    """
    counts: Dict[str, int] = {}
    for change in plan.get("resource_changes") or []:
        if not isinstance(change, dict):
            continue
        actions = ((change.get("change") or {}).get("actions")) or []
        if "create" not in actions:
            continue
        rtype = change.get("type")
        if not rtype:
            continue
        counts[rtype] = counts.get(rtype, 0) + 1
    return counts


def categorize_resources(counts: Dict[str, int]) -> Dict[str, Any]:
    """Group raw ``{resource_type: count}`` into human-readable categories.

    Returns::

        {
            "total_resources": 13,
            "resource_counts": {"aws_vpc": 1, ...},   # Phase 2 raw counts
            "categories": [                            # Phase 3 model
                {"name": "Networking", "items": [
                    {"type": "aws_vpc", "label": "VPC", "count": 1}, ...
                ]},
                ...
            ],
        }
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for rtype, count in counts.items():
        category, label = _RESOURCE_CATALOG.get(rtype, ("Other", _humanize(rtype)))
        buckets.setdefault(category, []).append(
            {"type": rtype, "label": label, "count": count}
        )

    ordered: List[Dict[str, Any]] = []
    seen = set()
    for name in _CATEGORY_ORDER:
        items = buckets.get(name)
        if items:
            ordered.append({"name": name, "items": sorted(items, key=lambda i: i["label"])})
            seen.add(name)
    # Any category not in the canonical order (defensive) — append alphabetically.
    for name in sorted(buckets):
        if name not in seen:
            ordered.append({"name": name, "items": sorted(buckets[name], key=lambda i: i["label"])})

    return {
        "total_resources": sum(counts.values()),
        "resource_counts": counts,
        "categories": ordered,
    }


def build_infrastructure_summary(plan_json_text: str) -> Optional[Dict[str, Any]]:
    """Parse raw ``terraform show -json`` text → categorized summary dict.

    Returns ``None`` if the text is not valid JSON. Never raises on a
    well-formed-but-empty plan — it returns a summary with zero resources.
    """
    try:
        plan = json.loads(plan_json_text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("[PlanSummary] plan JSON was not parseable")
        return None
    counts = parse_resource_counts(plan)
    return categorize_resources(counts)
