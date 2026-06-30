"""Infrastructure Destroy phase — request + aggregated read-only response schema.

The destroy phase reuses the platform's existing architecture end-to-end:

    generate destroy.yml  → install it (reuse RepositoryInstallationService)
    → dispatch it (reuse workflow_dispatch)  → observe it (reuse the monitoring
      GitHub Actions client, EXACTLY like bootstrap.yml)

The backend NEVER runs Terraform — GitHub Actions is the execution engine. This
response powers the one read the destroy surface makes (and polls): it carries
the lifecycle state (requested / running / succeeded / failed), the install +
dispatch provenance, and the live ``destroy.yml`` run observation.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from backend.app.schemas.workflow_monitoring_phase import PipelineRunView


# The four lifecycle states the phase persists in
# ``phases_state[INFRASTRUCTURE_DESTROY].status`` (see InfrastructureDestroyService).
DESTROY_REQUESTED = "destroy_requested"   # destroy.yml committed, run not yet confirmed
DESTROY_RUNNING = "destroy_running"       # dispatched / GitHub Actions run in flight
DESTROY_SUCCEEDED = "destroy_succeeded"   # destroy.yml run concluded success
DESTROY_FAILED = "destroy_failed"         # install/dispatch failed OR run concluded failure


class InfrastructureDestroyPhaseResponse(BaseModel):
    """ONE response → the whole Infrastructure Destroy surface."""

    workflow_id: str
    project_id: str
    task_id: Optional[str] = None
    current_phase: Optional[str] = None
    status: Optional[str] = None              # Workflow.status
    phase_status: Optional[str] = None        # one of the DESTROY_* states (or None)

    # Lifecycle booleans (objective: store requested/running/succeeded/failed).
    requested: bool = False
    running: bool = False
    succeeded: bool = False
    failed: bool = False

    # Pre-flight (UX): can the destroy be triggered at all?
    prerequisites_met: bool = False
    has_repo_url: bool = False
    has_github_token: bool = False
    has_terraform: bool = False
    missing_requirements: List[str] = []

    # Install + dispatch provenance (set once the phase has run).
    repo_url: Optional[str] = None
    branch: Optional[str] = None
    base_branch: Optional[str] = None
    commit_sha: Optional[str] = None
    pr_url: Optional[str] = None
    pr_created: bool = False
    pr_skipped_reason: Optional[str] = None
    dispatched: bool = False
    dispatch_error: Optional[str] = None
    error: Optional[str] = None

    # Live run observation (read-only — observed exactly like bootstrap.yml).
    monitoring_available: bool = False
    run: Optional[PipelineRunView] = None

    logs: List[str] = []


class ProjectDeletionState(BaseModel):
    """Whether a project may be deleted (the destruction deletion guard).

    A project may be deleted only when it has no live infrastructure, or its
    infrastructure has been successfully destroyed.
    """

    deletable: bool
    has_infrastructure: bool
    destroy_succeeded: bool
    reason: Optional[str] = None
