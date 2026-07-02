"""Infrastructure Recovery phase — read-only diagnostic response schema.

After a failed infrastructure provisioning (``bootstrap.yml`` → ``terraform
apply`` fails on GitHub Actions), this surface provides a STRUCTURED, PURELY
DIAGNOSTIC recovery layer. It never touches AWS and never runs Terraform:

    observe the failed bootstrap run (read-only, exactly like monitoring)
    → inspect the persisted Terraform artifacts + state backend
    → classify the failure
    → produce a RecoveryReport with recommendations

The engineer decides what to do. The ``available_actions`` are disabled
placeholders — there is no backend execution behind them yet.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from backend.app.schemas.workflow_monitoring_phase import PipelineRunView


# ── Phase status (persisted in phases_state[INFRASTRUCTURE_RECOVERY].status) ──
# A diagnostic marker only — it carries NO execution semantics and never gates
# the generation lifecycle.
RECOVERY_AVAILABLE = "recovery_available"      # a failure was diagnosed; a report exists
NO_FAILURE_DETECTED = "no_failure_detected"    # bootstrap did not fail (nothing to recover)


# ── Failure classification labels (mirror recovery_classifier) ───────────────
FAILURE_EXISTING_RESOURCE = "existing_aws_resource"
FAILURE_MISSING_STATE = "missing_terraform_state"
FAILURE_INVALID_CREDENTIALS = "invalid_credentials"
FAILURE_MISSING_PERMISSIONS = "missing_permissions"
FAILURE_TERRAFORM_SYNTAX = "terraform_syntax_error"
FAILURE_PROVIDER_ERROR = "provider_error"
FAILURE_AWS_API_ERROR = "aws_api_error"
FAILURE_UNKNOWN = "unknown"


class DetectedResource(BaseModel):
    """An AWS resource inferred from the failure text (best-effort, read-only).

    Carrying the resource identity lets the UI show "ECR repository 'app' already
    exists" and is the input a future, human-approved ``terraform import`` would
    use. Detection is heuristic — the list may be empty.
    """

    resource_type: str                      # e.g. "ecr_repository", "s3_bucket", "iam_role"
    identifier: Optional[str] = None        # the name/arn parsed from the message
    raw: Optional[str] = None               # the matched snippet (for transparency)


class RecoveryAction(BaseModel):
    """A recovery action offered to the engineer. DISABLED placeholder for now.

    ``enabled`` is always False in this phase — the platform performs no recovery
    execution yet. The buttons exist so the operator sees the intended options.
    """

    id: str                                 # "retry" | "import" | "destroy"
    label: str
    description: str
    enabled: bool = False
    recommended: bool = False


class RecoveryReport(BaseModel):
    """Structured, read-only diagnosis of a failed infrastructure provisioning."""

    status: str                             # RECOVERY_AVAILABLE | NO_FAILURE_DETECTED
    failure_type: str                       # one of the FAILURE_* labels
    root_cause: str                         # one-line human root cause
    terraform_state_available: bool         # a remote S3 state backend is configured
    terraform_outputs_available: bool = False  # terraform outputs were generated
    recoverable: bool                       # is there a known recovery path?
    recommended_action: str                 # machine code, e.g. "import_existing_resource"
    recommended_action_label: str           # human label, e.g. "Import existing resource"
    confidence: str                         # "high" | "medium" | "low"
    detected_resources: List[DetectedResource] = Field(default_factory=list)
    explanation: str                        # full operator-facing explanation
    available_actions: List[RecoveryAction] = Field(default_factory=list)
    generated_at: Optional[str] = None


class InfrastructureRecoveryPhaseResponse(BaseModel):
    """ONE response → the whole Infrastructure Recovery surface (read-only)."""

    workflow_id: str
    project_id: str
    task_id: Optional[str] = None
    current_phase: Optional[str] = None
    status: Optional[str] = None            # Workflow.status
    phase_status: Optional[str] = None      # RECOVERY_AVAILABLE | NO_FAILURE_DETECTED | None

    # Is a structured recovery available (a failure was diagnosed + persisted)?
    recovery_available: bool = False
    failed: bool = False                    # the bootstrap run concluded failure

    # Inputs the diagnosis observed (read-only).
    has_repo_url: bool = False
    has_github_token: bool = False
    has_terraform: bool = False

    # Live (read-only) observation of the failed bootstrap run + the report.
    monitoring_available: bool = False
    run: Optional[PipelineRunView] = None
    report: Optional[RecoveryReport] = None

    error: Optional[str] = None
