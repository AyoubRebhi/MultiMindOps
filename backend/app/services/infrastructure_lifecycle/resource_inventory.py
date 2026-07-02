"""Build the managed-resource inventory from the generated Terraform.

The inventory is derived from the Terraform CONFIGURATION (the ``.tf`` artifacts
in the DB) — the set of resources Terraform manages. The backend never reads the
remote S3 state directly because it never runs Terraform/AWS (GitHub Actions is
the only execution engine), so the declared resource set is the authoritative,
execution-free source for "what this project manages".

Pure functions — no I/O.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from backend.app.schemas.infrastructure_lifecycle_phase import (
    ResourceItem,
    ServiceGroup,
)

# `resource "aws_xxx" "name" {` — the managed-resource declarations.
_RESOURCE_RE = re.compile(
    r'resource\s+"(aws_[a-z0-9_]+)"\s+"([A-Za-z0-9_\-]+)"', re.IGNORECASE
)

# `backend "s3" { bucket = "..." key = "..." }` — for the state location.
_BACKEND_S3_RE = re.compile(r'backend\s+"s3"\s*\{', re.IGNORECASE)
_BUCKET_RE = re.compile(r'bucket\s*=\s*"([^"]+)"', re.IGNORECASE)
_KEY_RE = re.compile(r'key\s*=\s*"([^"]+)"', re.IGNORECASE)


# Resource-type prefix → human AWS service group. Order matters (first match).
_SERVICE_RULES: Tuple[Tuple[str, str], ...] = (
    ("aws_ecr_", "Amazon ECR"),
    ("aws_eks_", "Amazon EKS"),
    ("aws_ecs_", "Amazon ECS"),
    ("aws_lambda_", "AWS Lambda"),
    ("aws_apigatewayv2_", "API Gateway"),
    ("aws_api_gateway_", "API Gateway"),
    ("aws_iam_", "IAM"),
    ("aws_s3_", "Amazon S3"),
    ("aws_db_", "Database"),
    ("aws_rds_", "Database"),
    ("aws_elasticache_", "Database"),
    ("aws_cloudwatch_", "Observability"),
    # Networking — explicit set (these don't share a single prefix).
    ("aws_vpc", "Networking"),
    ("aws_subnet", "Networking"),
    ("aws_internet_gateway", "Networking"),
    ("aws_nat_gateway", "Networking"),
    ("aws_route_table", "Networking"),
    ("aws_route", "Networking"),
    ("aws_security_group", "Networking"),
    ("aws_lb", "Networking"),
    ("aws_eip", "Networking"),
)

# Stable display order for the groups.
_GROUP_ORDER = [
    "Amazon ECR", "Amazon EKS", "Amazon ECS", "AWS Lambda", "API Gateway",
    "Networking", "IAM", "Amazon S3", "Database", "Observability", "Other",
]


def _service_for(resource_type: str) -> str:
    rt = resource_type.lower()
    for prefix, service in _SERVICE_RULES:
        if rt == prefix or rt.startswith(prefix):
            return service
    return "Other"


def build_inventory(tf_files: Dict[str, str]) -> Tuple[List[ServiceGroup], int]:
    """Parse the Terraform files into ``(grouped_inventory, total_count)``.

    De-duplicates by terraform address across files and groups by AWS service.
    """
    seen: set[str] = set()
    by_service: Dict[str, List[ResourceItem]] = {}

    for content in (tf_files or {}).values():
        if not isinstance(content, str):
            continue
        for match in _RESOURCE_RE.finditer(content):
            resource_type, name = match.group(1).lower(), match.group(2)
            address = f"{resource_type}.{name}"
            if address in seen:
                continue
            seen.add(address)
            service = _service_for(resource_type)
            by_service.setdefault(service, []).append(
                ResourceItem(resource_type=resource_type, name=name, terraform_address=address)
            )

    groups: List[ServiceGroup] = []
    for service in _GROUP_ORDER:
        items = by_service.pop(service, None)
        if items:
            groups.append(ServiceGroup(service=service, resources=sorted(items, key=lambda r: r.terraform_address)))
    # Any service not in the predefined order (defensive) appended alphabetically.
    for service in sorted(by_service):
        groups.append(ServiceGroup(service=service, resources=by_service[service]))

    return groups, len(seen)


def parse_state_location(tf_files: Dict[str, str]) -> Tuple[bool, str | None, str | None]:
    """Return ``(backend_configured, bucket, key)`` from backend.tf.

    ``backend_configured`` is True only for a real (non-placeholder) S3 backend.
    """
    backend = (tf_files or {}).get("backend.tf") or ""
    if not backend or "placeholder" in backend.lower() or not _BACKEND_S3_RE.search(backend):
        return False, None, None
    bucket = _BUCKET_RE.search(backend)
    key = _KEY_RE.search(backend)
    bucket_v = bucket.group(1) if bucket else None
    key_v = key.group(1) if key else None
    return bool(bucket_v), bucket_v, key_v
