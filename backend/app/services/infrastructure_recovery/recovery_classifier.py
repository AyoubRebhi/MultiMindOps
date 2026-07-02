"""Infrastructure failure classifier — pure, deterministic, read-only.

Maps a Terraform/AWS failure blob (the error text from a failed
``terraform apply``) onto a structured classification + recovery recommendation.
It is a pure function of its input text — no I/O, no AWS, no Terraform — so it is
trivially testable and can never have a side effect.

Marker ordering matters: a single failure blob can contain several signatures
(e.g. a permission error that also mentions a resource name), so the most
specific / most actionable class is matched first and wins.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from backend.app.schemas.infrastructure_recovery_phase import (
    FAILURE_AWS_API_ERROR,
    FAILURE_EXISTING_RESOURCE,
    FAILURE_INVALID_CREDENTIALS,
    FAILURE_MISSING_PERMISSIONS,
    FAILURE_MISSING_STATE,
    FAILURE_PROVIDER_ERROR,
    FAILURE_TERRAFORM_SYNTAX,
    FAILURE_UNKNOWN,
)

# ── Recommended-action codes + human labels ──────────────────────────────────
ACTION_IMPORT = "import_existing_resource"
ACTION_REBUILD_STATE = "rebuild_state_or_import"
ACTION_UPDATE_CREDENTIALS = "update_credentials"
ACTION_REVIEW_IAM = "review_iam_permissions"
ACTION_FIX_TERRAFORM = "fix_terraform_configuration"
ACTION_RETRY = "retry"
ACTION_MANUAL = "manual_investigation"

_ACTION_LABELS = {
    ACTION_IMPORT: "Import existing resource",
    ACTION_REBUILD_STATE: "Rebuild state or import resources",
    ACTION_UPDATE_CREDENTIALS: "Update credentials",
    ACTION_REVIEW_IAM: "Review IAM permissions",
    ACTION_FIX_TERRAFORM: "Fix Terraform configuration and re-run",
    ACTION_RETRY: "Retry the run",
    ACTION_MANUAL: "Manual investigation required",
}


@dataclass(frozen=True)
class DetectedResourceDC:
    resource_type: str
    identifier: Optional[str] = None
    raw: Optional[str] = None


@dataclass(frozen=True)
class FailureClassification:
    failure_type: str
    recommended_action: str
    recommended_action_label: str
    recoverable: bool
    confidence: str  # "high" | "medium" | "low"
    root_cause: str
    explanation: str
    detected_resources: List[DetectedResourceDC] = field(default_factory=list)
    matched_marker: Optional[str] = None


# ── Per-class metadata: action, recoverability, base confidence, root cause ──
#
# ``base_confidence`` is the confidence when a class-specific marker matched. The
# service downgrades it to "low" when the source text was empty/weak (we only
# know the run failed, not why).
_CLASS_META = {
    FAILURE_EXISTING_RESOURCE: dict(
        action=ACTION_IMPORT, recoverable=True, base_confidence="high",
        root_cause="An AWS resource Terraform tried to create already exists.",
        explanation=(
            "Terraform attempted to create a resource that already exists in AWS "
            "(a previous partial apply, or a resource created outside this "
            "workflow). Terraform does not own it in state, so it errored instead "
            "of adopting it. The safe recovery is to import the existing resource "
            "into Terraform state so a subsequent apply reconciles it — no resource "
            "is recreated or deleted."
        ),
    ),
    FAILURE_MISSING_STATE: dict(
        action=ACTION_REBUILD_STATE, recoverable=True, base_confidence="high",
        root_cause="The Terraform remote state could not be found or loaded.",
        explanation=(
            "Terraform could not read its remote state (the S3 state object or "
            "backend was missing/unreadable). Any resources a previous apply "
            "created are now untracked. Recovery is to restore/rebuild the state "
            "backend and import the live resources back into state before applying "
            "again — never a blind re-apply, which would try to recreate them."
        ),
    ),
    FAILURE_INVALID_CREDENTIALS: dict(
        action=ACTION_UPDATE_CREDENTIALS, recoverable=True, base_confidence="high",
        root_cause="The AWS credentials are missing, invalid, or expired.",
        explanation=(
            "AWS rejected the request because the credentials were invalid, "
            "expired, or absent. No infrastructure change was made. Recovery is to "
            "update the AWS credentials (access key / secret / session token) and "
            "re-run — there is nothing to import or destroy."
        ),
    ),
    FAILURE_MISSING_PERMISSIONS: dict(
        action=ACTION_REVIEW_IAM, recoverable=True, base_confidence="high",
        root_cause="The IAM principal lacks permission for a required action.",
        explanation=(
            "The credentials are valid but the IAM principal is not authorized to "
            "perform a required action (an explicit deny or a missing allow). "
            "Recovery is to grant the missing IAM permissions to the principal and "
            "re-run. Some resources may have been partially created before the "
            "denial — review the run before re-applying."
        ),
    ),
    FAILURE_TERRAFORM_SYNTAX: dict(
        action=ACTION_FIX_TERRAFORM, recoverable=True, base_confidence="high",
        root_cause="The Terraform configuration has a syntax or schema error.",
        explanation=(
            "Terraform rejected the configuration itself (an invalid argument, "
            "block, or reference). No AWS change was made. Recovery is to fix the "
            "Terraform configuration (regenerate the Terraform phase) and re-run — "
            "there is nothing to import or destroy."
        ),
    ),
    FAILURE_PROVIDER_ERROR: dict(
        action=ACTION_RETRY, recoverable=True, base_confidence="medium",
        root_cause="Terraform could not install or initialize a provider.",
        explanation=(
            "Terraform failed to download/initialize a provider plugin (registry "
            "unreachable, version constraint, or checksum). This is an environment "
            "issue, not a configuration or AWS-resource defect. Recovery is to "
            "re-run once provider connectivity is restored."
        ),
    ),
    FAILURE_AWS_API_ERROR: dict(
        action=ACTION_RETRY, recoverable=True, base_confidence="medium",
        root_cause="A transient AWS API error interrupted the apply.",
        explanation=(
            "AWS returned a throttling/availability/transient error during the "
            "apply. Part of the infrastructure may have been created before the "
            "interruption. Recovery is to re-run — Terraform will continue from "
            "the current state. If the same error recurs, inspect the run logs."
        ),
    ),
    FAILURE_UNKNOWN: dict(
        action=ACTION_MANUAL, recoverable=False, base_confidence="low",
        root_cause="The failure could not be classified from the available signal.",
        explanation=(
            "The provisioning failed but the error did not match a known recovery "
            "pattern (or the detailed error could not be read from here). Open the "
            "GitHub Actions run logs to inspect the failure before deciding on a "
            "recovery action."
        ),
    ),
}


# ── Marker tables (lower-cased substrings), ordered most-specific first ───────
# Each entry: (failure_type, (markers...)). The first group with a hit wins.
_MARKER_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (FAILURE_EXISTING_RESOURCE, (
        "already exists",
        "alreadyexists",
        "entityalreadyexists",
        "resourcealreadyexistsexception",
        "repositoryalreadyexistsexception",
        "bucketalreadyexists",
        "bucketalreadyownedbyyou",
        "already exists in stack",
        "a resource with the id",
        "name already in use",
    )),
    (FAILURE_INVALID_CREDENTIALS, (
        "invalidclienttokenid",
        "signaturedoesnotmatch",
        "unrecognizedclientexception",
        "the security token included in the request is invalid",
        "the security token included in the request is expired",
        "no valid credential sources",
        "unable to locate credentials",
        "could not load credentials",
        "incomplete signature",
        "expiredtoken",
        "auth failure",
        "authfailure",
    )),
    (FAILURE_MISSING_PERMISSIONS, (
        "accessdenied",
        "access denied",
        "unauthorizedoperation",
        "is not authorized to perform",
        "you are not authorized",
        "not authorized to perform",
        "explicit deny",
        "with an explicit deny",
        "user is not authorized",
    )),
    (FAILURE_MISSING_STATE, (
        "nosuchbucket",
        "nosuchkey",
        "failed to get existing workspaces",
        "no state file was found",
        "error loading state",
        "failed to load state",
        "error refreshing state",
        "backend initialization required",
        "state snapshot was created by",
        "state data in s3 does not have",
    )),
    (FAILURE_TERRAFORM_SYNTAX, (
        "unsupported argument",
        "unsupported block type",
        "invalid block definition",
        "argument or block definition required",
        "missing required argument",
        "reference to undeclared",
        "invalid resource type",
        "unclosed configuration block",
        "invalid expression",
        "a reference to a resource type must be followed",
    )),
    (FAILURE_PROVIDER_ERROR, (
        "failed to query available provider packages",
        "failed to install provider",
        "could not retrieve the list of available versions",
        "failed to load plugin schemas",
        "error while installing",
        "checksum",
        "provider registry",
        "no available releases match",
    )),
    (FAILURE_AWS_API_ERROR, (
        "throttling",
        "throttlingexception",
        "requestlimitexceeded",
        "serviceunavailable",
        "service unavailable",
        "internalfailure",
        "internal error",
        "requesterror",
        "operationaborted",
        "503 service unavailable",
        "502 bad gateway",
        "504 gateway",
        "connection reset",
        "i/o timeout",
    )),
)


# ── Resource extraction (best-effort, for detected_resources) ────────────────
# Each: (resource_type, compiled regex with one capture group = identifier).
_RESOURCE_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("ecr_repository", re.compile(
        r"repository\s+with\s+name\s+'([^']+)'\s+already\s+exists", re.I)),
    ("s3_bucket", re.compile(
        r"bucket(?:\s+named?|\s+with\s+name)?\s+['\"]?([a-z0-9.\-]{3,63})['\"]?\s+already\s+exists",
        re.I)),
    ("iam_role", re.compile(
        r"role\s+with\s+name\s+([A-Za-z0-9_+=,.@\-]+)\s+already\s+exists", re.I)),
    ("iam_policy", re.compile(
        r"policy\s+([A-Za-z0-9_+=,.@\-]+)\s+already\s+exists", re.I)),
    # Terraform's own import hint: "with aws_ecr_repository.app,"
    ("terraform_address", re.compile(
        r"with\s+(aws_[a-z0-9_]+\.[A-Za-z0-9_\-\[\]\"]+)\s*,", re.I)),
    # Generic AWS "creating X: ... : <Name> already exists".
    ("aws_resource", re.compile(
        r"creating\s+([A-Za-z0-9 ]+?)\s*[:(]", re.I)),
)


def extract_detected_resources(text: str) -> List[DetectedResourceDC]:
    """Best-effort parse of resource identities from a failure blob."""
    found: List[DetectedResourceDC] = []
    seen: set[Tuple[str, Optional[str]]] = set()
    for resource_type, pattern in _RESOURCE_PATTERNS:
        for match in pattern.finditer(text):
            identifier = (match.group(1) or "").strip().strip("\"'")
            if not identifier:
                continue
            key = (resource_type, identifier)
            if key in seen:
                continue
            seen.add(key)
            found.append(DetectedResourceDC(
                resource_type=resource_type,
                identifier=identifier,
                raw=match.group(0).strip()[:200],
            ))
    return found


def _match_failure_type(lowered: str) -> Tuple[str, Optional[str]]:
    """Return (failure_type, matched_marker) for the first group that hits."""
    for failure_type, markers in _MARKER_GROUPS:
        for marker in markers:
            if marker in lowered:
                return failure_type, marker
    return FAILURE_UNKNOWN, None


def classify_failure(text: Optional[str]) -> FailureClassification:
    """Classify a Terraform/AWS failure blob into a recovery recommendation.

    Pure function: no I/O. An empty/whitespace blob classifies as ``unknown``
    with ``low`` confidence (we cannot see why the run failed from here).
    """
    blob = (text or "").strip()
    if not blob:
        meta = _CLASS_META[FAILURE_UNKNOWN]
        return FailureClassification(
            failure_type=FAILURE_UNKNOWN,
            recommended_action=meta["action"],
            recommended_action_label=_ACTION_LABELS[meta["action"]],
            recoverable=meta["recoverable"],
            confidence="low",
            root_cause=meta["root_cause"],
            explanation=meta["explanation"],
            detected_resources=[],
            matched_marker=None,
        )

    lowered = blob.lower()
    failure_type, marker = _match_failure_type(lowered)
    meta = _CLASS_META[failure_type]

    detected: List[DetectedResourceDC] = []
    if failure_type in (FAILURE_EXISTING_RESOURCE, FAILURE_MISSING_STATE):
        detected = extract_detected_resources(blob)

    return FailureClassification(
        failure_type=failure_type,
        recommended_action=meta["action"],
        recommended_action_label=_ACTION_LABELS[meta["action"]],
        recoverable=meta["recoverable"],
        confidence=meta["base_confidence"],
        root_cause=meta["root_cause"],
        explanation=meta["explanation"],
        detected_resources=detected,
        matched_marker=marker,
    )
