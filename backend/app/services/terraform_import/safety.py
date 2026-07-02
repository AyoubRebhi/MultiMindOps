"""Pre-import safety checks — never import a resource outside this project/account.

Every resource is validated BEFORE any ``terraform import`` runs. Two failure
classes exist:

* GLOBAL aborts (``account_mismatch`` / ``region_mismatch``) — the recovery is
  pointed at the wrong AWS account or region, which is categorically unsafe, so
  the WHOLE recovery aborts and nothing is imported.
* per-resource aborts (unsupported type, malformed address, invalid identifier,
  ownership) — that one resource is skipped; the rest proceed.

Pure functions — no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from backend.app.services.terraform_import.models import (
    SUPPORTED_RESOURCE_TYPES,
    ImportableResource,
    SafetyViolation,
)

# Categories that abort the ENTIRE recovery (wrong cloud target).
GLOBAL_ABORT_CATEGORIES = frozenset({"account_mismatch", "region_mismatch"})

_ADDRESS_RE = re.compile(
    r"^(?:module\.[A-Za-z0-9_\-]+\.)*aws_[a-z0-9_]+\.[A-Za-z0-9_\-]+(?:\[[^\]]+\])?$"
)
# A sane terraform import ID: AWS names, ids, and ARNs — bounded, no whitespace
# or shell metacharacters (defence in depth; commands are run argv-style, never
# through a shell).
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_+=,.@:/\-]{1,2048}$")


@dataclass(frozen=True)
class ImportSafetyContext:
    """The trust boundary an import must stay inside.

    ``expected_account_id`` / ``expected_region`` gate ARN-bearing identifiers.
    ``allowed_name_prefix`` (the sanitized project name) gates resource ownership
    so a resource belonging to another project is never adopted.
    """

    project_id: str
    expected_account_id: Optional[str] = None
    expected_region: Optional[str] = None
    allowed_name_prefix: Optional[str] = None


def _parse_arn(identifier: str) -> Optional[tuple[str, str]]:
    """Return (region, account_id) for an ARN identifier, else None.

    ARN format: ``arn:partition:service:region:account-id:resource``.
    """
    if not identifier.startswith("arn:"):
        return None
    parts = identifier.split(":")
    if len(parts) < 6:
        return None
    return parts[3], parts[4]  # region, account (either may be empty)


def validate_resource(
    resource: ImportableResource,
    ctx: ImportSafetyContext,
) -> Optional[SafetyViolation]:
    """Return the first :class:`SafetyViolation` for ``resource``, or None if safe."""
    # 1. Type must be in the supported allow-list.
    if resource.resource_type not in SUPPORTED_RESOURCE_TYPES:
        return SafetyViolation(
            "unsupported_type",
            f"Resource type '{resource.resource_type}' is not importable.",
        )

    # 2. Terraform address must be well-formed.
    if not _ADDRESS_RE.match(resource.terraform_address):
        return SafetyViolation(
            "malformed_address",
            f"Malformed terraform address '{resource.terraform_address}'.",
        )

    # 3. Identifier must be present and within a safe charset.
    ident = (resource.aws_identifier or "").strip()
    if not ident or not _IDENTIFIER_RE.match(ident):
        return SafetyViolation(
            "invalid_identifier",
            f"Invalid AWS identifier '{resource.aws_identifier}'.",
        )

    # 4. ARN account / region must match the project's cloud target (GLOBAL).
    arn = _parse_arn(ident)
    if arn is not None:
        region, account = arn
        if ctx.expected_region and region and region != ctx.expected_region:
            return SafetyViolation(
                "region_mismatch",
                f"Resource region '{region}' != project region "
                f"'{ctx.expected_region}'.",
            )
        if ctx.expected_account_id and account and account != ctx.expected_account_id:
            return SafetyViolation(
                "account_mismatch",
                f"Resource account '{account}' != project account "
                f"'{ctx.expected_account_id}'.",
            )

    # 5. Ownership — the resource must belong to THIS project.
    if ctx.allowed_name_prefix:
        prefix = ctx.allowed_name_prefix.lower()
        haystack = f"{resource.resource_name} {ident}".lower()
        if prefix not in haystack:
            return SafetyViolation(
                "ownership",
                f"Resource '{ident}' does not match project prefix "
                f"'{ctx.allowed_name_prefix}' — refusing to import a foreign resource.",
            )

    return None
