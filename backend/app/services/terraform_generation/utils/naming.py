"""
Centralized AWS resource-name sanitization.

Several AWS resource ``name``/``identifier`` arguments have hard, *short* length
ceilings — an ALB or Target Group name may be at most 32 characters. The
Terraform templates derive those names from the project identifier by suffixing
it (``"${project_name}-alb"``, ``"${project_name}-tg"``). Project identifiers are
UUIDs (~36 chars), so even after the project name itself is capped at 32, the
suffixed names overflow the 32-char ALB/TG limit — exactly the
``"name" cannot be longer than 32 characters`` failure ``terraform plan``
surfaced.

This module is the ONE place that turns an arbitrary base string + an optional
suffix into a name that is valid *and* fits within a resource's ceiling. It is
intentionally tiny and pure (no I/O, no AWS calls) so a reviewer can audit the
whole rule-set in one screenful, and so it is trivially unit-testable.

Guarantees of :func:`sanitize_aws_name` / :func:`sanitize_resource_name`:

  • only ``[a-z0-9-]``, lowercased
  • starts with a letter        — ALB/RDS/ECR names reject a leading digit/hyphen
  • no consecutive hyphens, no leading/trailing hyphen
  • ``len(base+suffix) <= max_length`` ALWAYS — the suffix is reserved first,
    then the base is fitted into the remaining room
  • uniqueness preserved on truncation — when the base must be shortened to fit,
    a deterministic 6-char hash of the *full* base is appended, so two distinct
    long bases cannot collapse onto the same name
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

_INVALID_NAME_CHARS_RE = re.compile(r"[^a-z0-9-]")
_MULTI_HYPHEN_RE = re.compile(r"-{2,}")
_LEADING_NON_ALPHA_RE = re.compile(r"^[^a-z]+")

# Tightest common AWS resource-name ceiling (ALB / Target Group). Used as the
# default so an un-annotated call is safe for the strictest consumer.
TERRAFORM_NAME_MAX_LENGTH = 32

# AWS ``name``/``identifier`` length ceilings per resource family. These are the
# documented hard limits — the sanitizer guarantees the rendered name fits.
AWS_NAME_LIMITS = {
    "alb": 32,             # aws_lb (application/network) name
    "target_group": 32,    # aws_lb_target_group name
    "elb": 32,             # classic ELB name
    "iam_role": 64,        # aws_iam_role name
    "iam_policy": 128,     # aws_iam_policy name
    "ecs_cluster": 255,    # aws_ecs_cluster name
    "ecs_service": 255,    # aws_ecs_service name
    "ecs_task_family": 255,  # aws_ecs_task_definition family
    "ecr_repository": 256,   # aws_ecr_repository name
    "eks_cluster": 100,    # aws_eks_cluster name
    "eks_node_group": 63,  # aws_eks_node_group node_group_name
    "rds_instance": 63,    # aws_db_instance identifier
    "db_subnet_group": 255,  # aws_db_subnet_group name
    "elasticache": 50,     # aws_elasticache_cluster cluster_id
    "lambda_function": 64,  # aws_lambda_function function_name
    "apigateway": 128,     # aws_apigatewayv2_api name
    "s3_bucket": 63,       # aws_s3_bucket bucket
    "security_group": 255,  # aws_security_group name
}

# Length of the deterministic disambiguating hash appended on truncation.
_HASH_LEN = 6


def _clean_token(text: Optional[str]) -> str:
    """Coerce an arbitrary string into the AWS name character-set.

    Lowercase; every illegal character → ``-``; collapse hyphen runs; trim end
    hyphens; drop any leading non-letter. Returns ``""`` when nothing survives
    (caller substitutes a fallback). No length enforcement here — that is the
    caller's concern, because the ceiling depends on the suffix.
    """
    candidate = (text or "").strip().lower()
    candidate = _INVALID_NAME_CHARS_RE.sub("-", candidate)
    candidate = _MULTI_HYPHEN_RE.sub("-", candidate).strip("-")
    candidate = _LEADING_NON_ALPHA_RE.sub("", candidate)
    return candidate


def sanitize_aws_name(
    base: Optional[str],
    suffix: str = "",
    max_length: int = TERRAFORM_NAME_MAX_LENGTH,
    *,
    fallback: str = "app",
) -> str:
    """Build a valid AWS resource name ``base[-truncated][-hash]+suffix``.

    The ``suffix`` (e.g. ``"-alb"``) is reserved FIRST, then the cleaned base is
    fitted into the remaining ``max_length - len(suffix)`` characters. When the
    base does not fit, it is truncated and a deterministic 6-char hash of the
    full base is appended so distinct long bases stay distinct.

    Never raises: malformed input is coerced, not rejected — this is naming, not
    policy. The result always satisfies ``len(result) <= max_length`` and the
    AWS naming character rules.

    >>> sanitize_aws_name("d052a-f714-4f90-9bf8-43e53dd685d", "-alb", 32)  # <= 32
    """
    # Clean the suffix to the legal charset. A leading hyphen ("-alb") is
    # intentional and preserved (it only sits *between* base and suffix).
    clean_suffix = _MULTI_HYPHEN_RE.sub(
        "-", _INVALID_NAME_CHARS_RE.sub("-", (suffix or "").lower())
    )

    base_clean = _clean_token(base) or _clean_token(fallback) or "app"

    available = max_length - len(clean_suffix)
    if available < 1:
        # Degenerate: the suffix alone meets/exceeds the ceiling. We cannot honour
        # it; emit a valid, deterministic hash-only name within the ceiling.
        digest = hashlib.sha1((base_clean + clean_suffix).encode()).hexdigest()
        return ("a" + digest)[:max_length]

    if len(base_clean) <= available:
        prefix = base_clean
    else:
        # Truncate, reserving room for a deterministic hash (uniqueness).
        digest = hashlib.sha1(base_clean.encode()).hexdigest()[:_HASH_LEN]
        keep = available - (_HASH_LEN + 1)  # +1 for the '-' before the hash
        if keep < 1:
            prefix = ("a" + digest)[:available]
        else:
            prefix = f"{base_clean[:keep].rstrip('-')}-{digest}"

    name = f"{prefix}{clean_suffix}"
    # Final guards: must start with a letter, must not exceed the ceiling, must
    # not end on a hyphen.
    name = _LEADING_NON_ALPHA_RE.sub("", name)[:max_length].rstrip("-")
    return name or (_clean_token(fallback) or "app")


def sanitize_resource_name(
    base: Optional[str],
    max_length: int = TERRAFORM_NAME_MAX_LENGTH,
    *,
    fallback: str = "app",
) -> str:
    """Convenience wrapper for the no-suffix case (``sanitize_aws_name(base, "")``)."""
    return sanitize_aws_name(base, "", max_length, fallback=fallback)
