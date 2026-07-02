"""Parse a failed ``terraform apply`` blob into importable resources.

Terraform groups each failure into a diagnostic block that carries both the
Terraform resource address (``with aws_ecr_repository.app,``) and the AWS error
message (``RepositoryAlreadyExistsException: ... 'app' ...``). This module pairs
the two: for every ``with <address>`` it takes the preceding message text and
extracts the AWS identifier that ``terraform import`` needs.

It only yields a resource when the block shows an "already exists" condition — we
never import on an unrelated error — and only for supported resource types.
"""

from __future__ import annotations

import re
from typing import List, Optional

from backend.app.services.terraform_import.models import (
    SUPPORTED_RESOURCE_TYPES,
    ImportableResource,
)

# Markers that mean "the resource already exists" → an import candidate.
_ALREADY_EXISTS_MARKERS = (
    "already exists",
    "alreadyexists",
    "entityalreadyexists",
    "resourcealreadyexists",
    "repositoryalreadyexistsexception",
    "bucketalreadyownedbyyou",
    "bucketalreadyexists",
    "resourceinuseexception",
    "already in use",
    "already owned by you",
)

# `with <address>,` — captures the full address, the type, and the local name.
_WITH_ADDRESS_RE = re.compile(
    r"with\s+("
    r"(?:module\.[A-Za-z0-9_\-]+\.)*"       # optional module path
    r"(aws_[a-z0-9_]+)\.([A-Za-z0-9_\-]+)"  # type + local name
    r"(?:\[[^\]]+\])?"                       # optional count/for_each index
    r")\s*,",
    re.IGNORECASE,
)

# Generic AWS-provider format: "creating ECR Repository (my-app):".
_CREATING_PARENS_RE = re.compile(r"creating\s+[A-Za-z0-9 /]+?\s*\(([^)]+)\)", re.IGNORECASE)

# Resource types whose terraform import ID is the resource NAME (not an AWS id).
_NAME_BASED_TYPES = {
    "aws_ecr_repository",
    "aws_iam_role",
    "aws_eks_cluster",
    "aws_eks_node_group",
    "aws_ecs_cluster",
    "aws_s3_bucket",
}

# Per-type extraction patterns (tried in order). Each captures the import ID.
_TYPE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "aws_ecr_repository": (
        re.compile(r"repository with name ['\"]?([A-Za-z0-9._/\-]+)", re.I),
    ),
    "aws_iam_role": (
        re.compile(r"[Rr]ole with name ([A-Za-z0-9_+=,.@\-]+)", re.I),
        re.compile(r"arn:aws:iam::\d+:role/([A-Za-z0-9_+=,.@\-/]+)", re.I),
    ),
    "aws_eks_cluster": (
        re.compile(r"[Cc]luster ['\"]?([A-Za-z0-9_\-]+)['\"]? already", re.I),
    ),
    "aws_ecs_cluster": (
        re.compile(r"[Cc]luster ['\"]?([A-Za-z0-9_\-]+)['\"]? already", re.I),
    ),
    "aws_s3_bucket": (
        re.compile(r"bucket (?:named )?['\"]?([a-z0-9.\-]{3,63})", re.I),
    ),
    "aws_vpc": (re.compile(r"(vpc-[0-9a-f]+)", re.I),),
    "aws_subnet": (re.compile(r"(subnet-[0-9a-f]+)", re.I),),
    "aws_security_group": (re.compile(r"(sg-[0-9a-f]+)", re.I),),
    "aws_internet_gateway": (re.compile(r"(igw-[0-9a-f]+)", re.I),),
    "aws_route_table": (re.compile(r"(rtb-[0-9a-f]+)", re.I),),
    "aws_lb": (
        re.compile(r"(arn:aws:elasticloadbalancing:[^\s\"']+:loadbalancer/[^\s\"']+)", re.I),
    ),
    "aws_lb_target_group": (
        re.compile(r"(arn:aws:elasticloadbalancing:[^\s\"']+:targetgroup/[^\s\"']+)", re.I),
    ),
}


def _extract_identifier(resource_type: str, message: str) -> Optional[str]:
    """Extract the terraform import ID for ``resource_type`` from ``message``."""
    for pattern in _TYPE_PATTERNS.get(resource_type, ()):
        m = pattern.search(message)
        if m:
            return m.group(1).strip().strip("'\"")
    # Name-based resources fall back to the provider's "creating X (NAME)" form.
    if resource_type in _NAME_BASED_TYPES:
        m = _CREATING_PARENS_RE.search(message)
        if m:
            return m.group(1).strip().strip("'\"")
    return None


def parse_failure(text: Optional[str]) -> List[ImportableResource]:
    """Return the importable resources detected in a terraform failure blob.

    Pairs each ``with <address>`` with the message text immediately preceding it
    (the diagnostic body Terraform prints above the address), keeps only blocks
    that show an "already exists" condition for a supported type, and extracts the
    AWS import identifier. De-duplicates by terraform address.
    """
    blob = (text or "").strip()
    if not blob:
        return []

    matches = list(_WITH_ADDRESS_RE.finditer(blob))
    resources: List[ImportableResource] = []
    seen: set[str] = set()
    prev_end = 0
    for m in matches:
        # The message for this address is everything since the previous address.
        message = blob[prev_end:m.start()]
        prev_end = m.end()

        address = m.group(1)
        resource_type = m.group(2).lower()
        resource_name = m.group(3)

        if resource_type not in SUPPORTED_RESOURCE_TYPES:
            continue
        if address in seen:
            continue
        if not any(marker in message.lower() for marker in _ALREADY_EXISTS_MARKERS):
            continue

        identifier = _extract_identifier(resource_type, message)
        if not identifier:
            continue

        seen.add(address)
        resources.append(ImportableResource(
            terraform_address=address,
            resource_type=resource_type,
            resource_name=resource_name,
            aws_identifier=identifier,
            raw=message.strip()[-300:] or None,
        ))
    return resources
