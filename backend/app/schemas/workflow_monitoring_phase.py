"""Workflow Monitoring phase — aggregated read-only response schema.

Powers the one request the monitoring surface makes (and polls every ~30s):

    GET /api/projects/{project_id}/workflows/{workflow_id}/monitoring
        -> WorkflowMonitoringPhaseResponse

Every field is assembled READ-ONLY by querying the GitHub Actions API for the
latest run of the two installed pipelines (bootstrap.yml + deploy.yml). Nothing
here triggers, reruns, cancels, or modifies a workflow or the repository. All
fields are optional/defaulted so a workflow without monitoring data (no repo,
no token, no runs yet, or a degraded fetch) still renders cleanly.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PipelineRunView(BaseModel):
    """The latest observed run of ONE pipeline (Infrastructure or Delivery)."""

    pipeline: str                       # "bootstrap" | "deploy"
    kind: str                           # mirror of pipeline (FE symmetry)
    name: str                           # "Infrastructure Pipeline" | "Delivery Pipeline"
    workflow_file: str                  # "bootstrap.yml" | "deploy.yml"
    workflow_url: Optional[str] = None  # repo's workflow page (runs list)

    # available = the API could be queried for this pipeline (auth+network OK).
    # found     = a run actually exists.
    available: bool = False
    found: bool = False

    run_id: Optional[int] = None
    run_number: Optional[int] = None
    status: Optional[str] = None        # queued | in_progress | completed | ...
    conclusion: Optional[str] = None    # success | failure | cancelled | ... | None
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    actor: Optional[str] = None
    event: Optional[str] = None         # push | workflow_dispatch | ...
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    html_url: Optional[str] = None      # the run URL ("Open in GitHub")

    # Optional step data (best-effort, only for active runs).
    current_job: Optional[str] = None
    current_step: Optional[str] = None

    error: Optional[str] = None         # per-pipeline failure reason, if any


class WorkflowMonitoringPhaseResponse(BaseModel):
    """ONE response → the whole Workflow Monitoring surface."""

    workflow_id: str
    project_id: str
    task_id: Optional[str] = None
    current_phase: Optional[str] = None
    status: Optional[str] = None              # Workflow.status
    phase_status: Optional[str] = None        # phases_state[WORKFLOW_MONITORING].status

    # True when the GitHub Actions API could be reached for at least one pipeline.
    monitoring_available: bool = False
    # True when the payload was served from the last persisted snapshot because
    # the live refresh failed (token revoked, GitHub unreachable, …).
    stale: bool = False
    fetched_at: Optional[str] = None
    repo_url: Optional[str] = None
    error: Optional[str] = None               # overall failure reason, if any

    # The two pipelines (named per the brief).
    infrastructure: PipelineRunView           # bootstrap.yml
    delivery: PipelineRunView                  # deploy.yml
