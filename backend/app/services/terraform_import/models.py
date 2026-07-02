"""Typed models + command builders for automatic Terraform import recovery.

The import recovery turns a failed ``terraform apply`` (because resources already
exist) into the deterministic sequence::

    detect → import → refresh → plan → apply

This module holds the value types shared across the parser, the safety layer and
the service, plus the SINGLE source of truth for every terraform command the
service runs (so flags never drift). Nothing here performs I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ── Supported resource types (the detection + import allow-list) ─────────────
# Importing is REFUSED for any type not in this set — a hard safety boundary.
SUPPORTED_RESOURCE_TYPES: frozenset[str] = frozenset({
    "aws_ecr_repository",
    "aws_iam_role",
    "aws_eks_cluster",
    "aws_eks_node_group",
    "aws_ecs_cluster",
    "aws_s3_bucket",
    "aws_security_group",
    "aws_lb",
    "aws_lb_target_group",
    "aws_subnet",
    "aws_vpc",
    "aws_internet_gateway",
    "aws_route_table",
})


# ── Per-resource import outcome statuses ─────────────────────────────────────
IMPORTED = "imported"
SKIPPED_ALREADY_MANAGED = "skipped_already_managed"
FAILED = "failed"
ABORTED_VALIDATION = "aborted_validation"


# ── Overall recovery statuses ────────────────────────────────────────────────
STATUS_RECOVERED = "recovered"   # imports done (or all already managed) + apply ok
STATUS_PARTIAL = "partial"       # some imports failed; apply NOT attempted
STATUS_FAILED = "failed"         # imports/init/apply failed
STATUS_NOOP = "noop"             # nothing importable detected
STATUS_ABORTED = "aborted"       # a global safety violation (wrong account/region)


@dataclass(frozen=True)
class ImportableResource:
    """One resource Terraform must adopt into state before re-applying."""

    terraform_address: str   # e.g. "aws_ecr_repository.app"
    resource_type: str       # e.g. "aws_ecr_repository"
    resource_name: str       # the local name part of the address, e.g. "app"
    aws_identifier: str      # the terraform import ID (repo name / arn / vpc-id …)
    raw: Optional[str] = None  # the matched error snippet (for transparency)


@dataclass(frozen=True)
class SafetyViolation:
    """Why a resource (or the whole recovery) must not be imported."""

    category: str  # "unsupported_type" | "malformed_address" | "invalid_identifier"
    #              | "account_mismatch" | "region_mismatch" | "ownership"
    message: str


@dataclass
class CommandResult:
    """The result of one terraform invocation (runner-agnostic)."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()


@dataclass
class ImportOutcome:
    """The result of attempting to import ONE resource."""

    resource: ImportableResource
    status: str                       # one of IMPORTED / SKIPPED_* / FAILED / ABORTED_*
    command: Optional[str] = None     # the import command run (or None if not run)
    message: str = ""
    duration_ms: int = 0


@dataclass
class ImportRecoveryResult:
    """The structured outcome of one import-recovery attempt."""

    status: str                                   # one of STATUS_*
    imported: List[ImportOutcome] = field(default_factory=list)
    skipped: List[ImportOutcome] = field(default_factory=list)
    failed: List[ImportOutcome] = field(default_factory=list)
    aborted: List[ImportOutcome] = field(default_factory=list)
    refresh_ok: Optional[bool] = None
    plan_ok: Optional[bool] = None
    apply_ok: Optional[bool] = None
    imported_count: int = 0
    duration_ms: int = 0
    logs: List[dict] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def recovered(self) -> bool:
        return self.status == STATUS_RECOVERED

    def to_dict(self) -> dict:
        def _outcome(o: ImportOutcome) -> dict:
            return {
                "terraform_address": o.resource.terraform_address,
                "resource_type": o.resource.resource_type,
                "aws_identifier": o.resource.aws_identifier,
                "status": o.status,
                "command": o.command,
                "message": o.message,
                "duration_ms": o.duration_ms,
            }

        return {
            "status": self.status,
            "imported": [_outcome(o) for o in self.imported],
            "skipped": [_outcome(o) for o in self.skipped],
            "failed": [_outcome(o) for o in self.failed],
            "aborted": [_outcome(o) for o in self.aborted],
            "refresh_ok": self.refresh_ok,
            "plan_ok": self.plan_ok,
            "apply_ok": self.apply_ok,
            "imported_count": self.imported_count,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "logs": self.logs,
        }


# ── Terraform command argument sequences (single source of truth) ────────────
#
# IMPORTANT: the import sequence uses the REAL backend (no ``-backend=false``):
# importing and applying must read/write the project's remote S3 state, which is
# exactly what makes the recovery durable + idempotent across runs.

INIT_ARGS: List[str] = ["init", "-input=false", "-no-color"]
STATE_LIST_ARGS: List[str] = ["state", "list"]
REFRESH_ARGS: List[str] = ["apply", "-refresh-only", "-auto-approve", "-input=false", "-no-color"]
PLAN_ARGS: List[str] = ["plan", "-input=false", "-no-color"]
APPLY_ARGS: List[str] = ["apply", "-auto-approve", "-input=false", "-no-color"]


def import_args(address: str, identifier: str) -> List[str]:
    """``terraform import [opts] ADDR ID`` — ADDR and ID are always the last two."""
    return ["import", "-input=false", "-no-color", address, identifier]


def import_command_str(address: str, identifier: str) -> str:
    """Human-readable import command (for logs / the report)."""
    return f"terraform import {address} {identifier}"
