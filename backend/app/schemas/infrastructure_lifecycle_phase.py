"""Infrastructure Lifecycle phase — the operational dashboard payload (read) +
the action request/response schemas.

This is the FINAL operational phase, shown after Monitoring. It aggregates
capabilities the platform already has — destroy (GitHub Actions), monitoring
(read-only observation), recovery + automatic import — into one control surface,
and adds an immutable lifecycle history. The backend never runs Terraform:
actions dispatch GitHub Actions workflows, exactly like bootstrap/deploy/destroy.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from backend.app.schemas.workflow_monitoring_phase import PipelineRunView


# ── Lifecycle event types (immutable history) ────────────────────────────────
EVENT_BOOTSTRAP_RETRY = "BOOTSTRAP_RETRY"
EVENT_BOOTSTRAP_RETRY_FAILED = "BOOTSTRAP_RETRY_FAILED"
EVENT_DESTROY_REQUESTED = "DESTROY_REQUESTED"
EVENT_DESTROY_COMPLETED = "DESTROY_COMPLETED"
EVENT_DESTROY_FAILED = "DESTROY_FAILED"
EVENT_IMPORT_COMPLETED = "IMPORT_COMPLETED"
EVENT_RECOVERY_COMPLETED = "RECOVERY_COMPLETED"

# ── Aggregate infrastructure status ──────────────────────────────────────────
INFRA_HEALTHY = "Healthy"
INFRA_FAILED = "Failed"
INFRA_DESTROYED = "Destroyed"
INFRA_PENDING = "Pending"


class LifecycleEventView(BaseModel):
    """One immutable lifecycle history record."""

    id: str
    event_type: str
    status: str               # success | failure | requested | info
    summary: str = ""
    duration_ms: Optional[int] = None
    actor_id: Optional[str] = None
    created_at: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class RecoveryAttemptView(BaseModel):
    """A recovery/import attempt, as shown in the Recovery History table."""

    timestamp: Optional[str] = None
    detected_issue: Optional[str] = None
    action_taken: Optional[str] = None
    status: str = "info"          # success | failure | info
    duration_ms: Optional[int] = None
    source: str = "lifecycle"     # lifecycle | recovery | import


class TerraformStateView(BaseModel):
    """The Terraform State section.

    Derived from the generated Terraform configuration + observed runs — the
    backend never reads remote S3 state directly (it never runs Terraform/AWS).
    """

    backend_configured: bool = False
    backend_type: Optional[str] = None       # "s3"
    state_bucket: Optional[str] = None
    state_key: Optional[str] = None
    workspace: str = "default"
    last_apply: Optional[str] = None         # last successful bootstrap run finish
    last_destroy: Optional[str] = None
    managed_resources_count: int = 0
    imported_resources_count: int = 0
    drift_status: str = "unavailable"        # unavailable unless a plan is observed


class ResourceItem(BaseModel):
    resource_type: str                       # e.g. "aws_ecr_repository"
    name: str                                # the terraform local name
    terraform_address: str                   # "aws_ecr_repository.app"


class ServiceGroup(BaseModel):
    """Managed resources grouped by AWS service (e.g. 'Amazon EKS')."""

    service: str
    resources: List[ResourceItem] = Field(default_factory=list)


class LifecycleActionView(BaseModel):
    """An action surfaced on the dashboard (enabled iff currently permitted)."""

    id: str                                  # "retry_bootstrap" | "destroy" | "refresh"
    label: str
    enabled: bool = False
    requires_confirmation: bool = False
    reason: Optional[str] = None             # why disabled, when not enabled


class InfrastructureLifecyclePhaseResponse(BaseModel):
    """ONE response → the whole Infrastructure Lifecycle dashboard."""

    workflow_id: str
    project_id: str
    task_id: Optional[str] = None
    current_phase: Optional[str] = None
    status: Optional[str] = None             # Workflow.status

    # Status section.
    infrastructure_status: str = INFRA_PENDING

    # Permission (computed from the caller's project role).
    can_manage: bool = False

    # Prerequisites for actions.
    has_repo_url: bool = False
    has_github_token: bool = False
    has_terraform: bool = False

    # Action availability.
    retry_bootstrap_available: bool = False
    destroy_available: bool = False
    destroy_block_reason: Optional[str] = None

    # Sections.
    terraform_state: TerraformStateView = Field(default_factory=TerraformStateView)
    inventory: List[ServiceGroup] = Field(default_factory=list)
    recovery_history: List[RecoveryAttemptView] = Field(default_factory=list)
    recovery_recommendations: List[str] = Field(default_factory=list)
    lifecycle_history: List[LifecycleEventView] = Field(default_factory=list)
    actions: List[LifecycleActionView] = Field(default_factory=list)

    # Monitoring (reuses the SAME PipelineRunView as bootstrap/deploy/destroy).
    monitoring_available: bool = False
    bootstrap_run: Optional[PipelineRunView] = None
    deploy_run: Optional[PipelineRunView] = None
    destroy_run: Optional[PipelineRunView] = None

    error: Optional[str] = None


# ── Action request / response ────────────────────────────────────────────────


class DestroyRequest(BaseModel):
    """Two-step confirmation — BOTH flags must be true to dispatch a destroy."""

    confirm: bool = False
    acknowledge_data_loss: bool = False


class LifecycleActionResult(BaseModel):
    """Result of a retry-bootstrap / destroy action."""

    status: str                              # "ok" | "blocked" | "failed"
    message: str
    event_id: Optional[str] = None
    dispatched: bool = False
    infrastructure_status: Optional[str] = None
