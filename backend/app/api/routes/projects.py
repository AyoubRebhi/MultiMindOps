"""Project-centric REST API.

Phase 1 surface area:
    POST   /api/projects                     create
    GET    /api/projects                     list (current user's memberships)
    GET    /api/projects/{id}                detail (with members + workflows + artifact count)
    PATCH  /api/projects/{id}                update
    GET    /api/projects/{id}/artifacts      list artifacts
    GET    /api/projects/{id}/workflows      list workflow execution instances
    GET    /api/projects/{id}/members        list members

Phase-level execution (rerun_phase), artifact approval, and version diffing
land in Phase 2.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.authorization import (
    require_project_approver,
    require_project_contributor,
    require_project_role,
)
from backend.app.core.security import get_current_user, get_db
from backend.app.models.project import ProjectMember
from backend.app.models.user import User
from backend.app.schemas.project import (
    ArtifactApprovalCreate,
    ArtifactApprovalResponse,
    ArtifactDetailResponse,
    ArtifactResponse,
    ArtifactVersionResponse,
    PhaseName,
    ProjectAnalysisResponse,
    ProjectContextResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectCredentialStatus,
    ProjectMemberCreate,
    ProjectMemberResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectSettingsResponse,
    ProjectSettingsUpdateRequest,
    ProjectUpdate,
    ProviderConfigured,
    RegeneratePhaseResponse,
    SelectPlanRequest,
    StartWorkflowRequest,
    WorkflowCancelResponse,
    WorkflowPhaseRunResponse,
    WorkflowResponse,
    WorkflowRevisionHistoryResponse,
    WorkflowStartResponse,
)
from backend.app.services.core.artifact_approval_service import ArtifactApprovalService
from backend.app.services.core.artifact_persistence_service import ArtifactPersistenceService
from backend.app.schemas.credentials import AwsCredentialStatus
from backend.app.services.core.credentials_service import (
    AWS_PROVIDER,
    GITHUB_PROVIDER,
    CredentialError,
    CredentialsService,
)
from backend.app.schemas.docker_phase import DockerPhaseResponse
from backend.app.schemas.github_actions_phase import GitHubActionsPhaseResponse
from backend.app.schemas.repository_installation_phase import (
    RepositoryInstallationPhaseResponse,
)
from backend.app.schemas.workflow_monitoring_phase import (
    WorkflowMonitoringPhaseResponse,
)
from backend.app.schemas.infrastructure_destroy_phase import (
    InfrastructureDestroyPhaseResponse,
    ProjectDeletionState,
)
from backend.app.schemas.infrastructure_recovery_phase import (
    InfrastructureRecoveryPhaseResponse,
)
from backend.app.schemas.infrastructure_lifecycle_phase import (
    DestroyRequest,
    InfrastructureLifecyclePhaseResponse,
    LifecycleActionResult,
)
from backend.app.schemas.workflow_analysis import WorkflowAnalysisResponse
from backend.app.services.core.docker_phase_projection_service import (
    DockerPhaseProjectionService,
)
from backend.app.services.core.github_actions_phase_projection_service import (
    GitHubActionsPhaseProjectionService,
)
from backend.app.services.core.repository_installation_projection_service import (
    RepositoryInstallationProjectionService,
)
from backend.app.services.workflow_monitoring import WorkflowMonitoringService
from backend.app.services.infrastructure_destroy import InfrastructureDestroyService
from backend.app.services.infrastructure_recovery import InfrastructureRecoveryService
from backend.app.services.infrastructure_lifecycle import InfrastructureLifecycleService
from backend.app.services.core.project_analysis_service import ProjectAnalysisService
from backend.app.services.core.workflow_analysis_aggregation_service import (
    WorkflowAnalysisAggregationService,
)
from backend.app.services.core.project_bootstrap_service import (
    ProjectBootstrapService,
    schedule_bootstrap,
)
from backend.app.services.core.project_context_service import ProjectContextService
from backend.app.services.core.project_service import ProjectService
from backend.app.services.core.task_service import TaskService
from backend.app.services.core.workflow_cancellation_service import (
    WorkflowCancellationService,
)
from backend.app.services.core.workflow_orchestration_service import (
    WorkflowOrchestrationService,
)
from backend.app.services.core.workflow_revision_service import (
    WorkflowRevisionService,
)
from backend.app.services.core.workflow_replay_service import WorkflowReplayService
from backend.app.services.core.workflow_trace_service import WorkflowTraceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["Projects"])


def _load_or_404(db: Session, project_id: str, user: User):
    project = ProjectService.get_project_for_user(db, project_id, user)
    if project is None:
        # Hide existence from non-members on purpose — returns 404 not 403.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a project and kick off the AI bootstrap pipeline.

    Synchronous portion: insert Project + OWNER membership, return 201.
    Asynchronous portion (scheduled via BackgroundTasks): clone the repo,
    run codebase analysis, generate architecture strategies, persist
    ProjectContext digests. The frontend polls the project + workflows +
    context endpoints to render bootstrap progress.

    If ``repository_url`` is omitted the bootstrap will short-circuit and
    mark the project as ``ready`` with empty analysis. The user can attach
    a repo later via PATCH and re-trigger bootstrap from the retry endpoint.
    """
    project = ProjectBootstrapService.create_project_and_bootstrap(
        db, current_user, payload,
    )

    # Private-repo GitHub PAT — persist it ENCRYPTED before the bootstrap task
    # is scheduled, so the background analysis (which pulls provider="github_pat"
    # from the credential store) can clone the private repo. The plaintext was
    # write-only on ProjectCreate; it never touches the Project row and is never
    # echoed back (ProjectResponse has no token field). A storage failure must
    # not abandon the just-created project — we log and let bootstrap proceed
    # token-less (it will surface a clone failure the user can retry after
    # attaching a credential).
    if payload.github_token:
        try:
            CredentialsService.set_credential(
                db,
                project_id=project.id,
                provider="github_pat",
                plaintext=payload.github_token,
                created_by=current_user.id,
                label="GitHub token (added at project creation)",
            )
        except (CredentialError, Exception) as exc:  # noqa: BLE001
            logger.warning(
                "[Projects] failed to store github_pat for project=%s: %s",
                project.id, exc.__class__.__name__,
            )

    schedule_bootstrap(
        background_tasks,
        project_id=project.id,
        user_id=current_user.id,
    )
    return project


@router.post(
    "/{project_id}/bootstrap/retry",
    response_model=ProjectResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_bootstrap(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reset bootstrap_status to pending and re-run a REAL analysis.

    Backs the ProjectDetail "Retry"/"Re-analyze" UI. Forces a fresh codebase
    analysis: it re-invokes the codebase-analysis LLM, bypasses the
    repository-analysis cache, and overwrites the persisted ProjectContext —
    so it works both for a FAILED bootstrap and for one that completed but
    produced a thin/empty result. Only the owner or members with write access
    (DEVELOPER+) should be able to call this; the membership check inside
    ``_load_or_404`` enforces the membership requirement, role gating can be
    tightened later.
    """
    project = _load_or_404(db, project_id, current_user)
    ProjectBootstrapService.reset_for_retry(db, project)
    schedule_bootstrap(
        background_tasks,
        project_id=project.id,
        user_id=current_user.id,
        force=True,
    )
    return project


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ProjectService.list_projects_for_user(db, current_user)


# ─── Static routes — MUST appear before the dynamic /{project_id} route ─────
#
# FastAPI matches routes top-to-bottom against the router's table. A dynamic
# segment like `/{project_id}` will happily capture a literal path segment
# like `me` or `search`, returning a 404 from the project lookup inside the
# handler instead of dispatching to the static handler the caller intended.
#
# Any new STATIC sub-path under /api/projects (e.g. /me, /search, /recent,
# /stats, /context-types) must be declared in this block. Dynamic project
# routes are registered AFTER this block.

@router.get("/me/identity")
def get_identity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the caller's user record + every project membership they hold.

    Frontend uses this to render role-gated UI without an extra user service.
    """
    memberships = (
        db.query(ProjectMember)
        .filter(ProjectMember.user_id == current_user.id)
        .all()
    )
    return {
        "id":           current_user.id,
        "email":        current_user.email,
        "display_name": current_user.display_name,
        "memberships":  [
            {"project_id": m.project_id, "role": m.role} for m in memberships
        ],
    }


# ─── Dynamic project routes ─────────────────────────────────────────────────
#
# Everything below has `/{project_id}` somewhere in the path. Do NOT add a
# new static path under /api/projects below this comment without also moving
# it above — otherwise FastAPI will route the request into the handler that
# treats your literal segment as a project_id.

@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _load_or_404(db, project_id, current_user)
    members = ProjectService.list_members(db, project.id)
    workflows = ProjectService.list_workflows(db, project.id)
    artifact_count = len(ProjectService.list_artifacts(db, project.id))

    payload = ProjectDetailResponse.model_validate(project).model_dump()
    payload["members"] = [ProjectMemberResponse.model_validate(m).model_dump() for m in members]
    payload["workflows"] = [WorkflowResponse.model_validate(w).model_dump() for w in workflows]
    payload["artifact_count"] = artifact_count
    return payload


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _load_or_404(db, project_id, current_user)
    return ProjectService.update_project(db, project, payload)


@router.get(
    "/{project_id}/deletion-state",
    response_model=ProjectDeletionState,
)
def get_project_deletion_state(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Whether the project may be deleted (the destruction deletion guard).

    Read-only: a project is deletable iff it has no live infrastructure OR its
    infrastructure was successfully destroyed. The UI uses this to enable/disable
    the delete action and explain why.
    """
    project = _load_or_404(db, project_id, current_user)
    return ProjectDeletionState(**InfrastructureDestroyService.infrastructure_state(db, project))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_role()),  # OWNER/ADMIN only
):
    """Delete a project — BLOCKED while it has live infrastructure.

    Deletion guard: a project may only be deleted when it has no provisioned
    infrastructure, or that infrastructure has been successfully destroyed
    (INFRASTRUCTURE_DESTROY → destroy_succeeded). Otherwise returns 409 so the
    engineer destroys first. On success the project + all its cascade-owned rows
    are removed.
    """
    project = _load_or_404(db, project_id, current_user)
    guard = InfrastructureDestroyService.infrastructure_state(db, project)
    if not guard["deletable"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=guard["reason"])
    ProjectService.delete_project(db, project)
    return None


# ─── Project settings (repository + credential status) ────────────────────────


def _build_project_settings_response(db: Session, project) -> ProjectSettingsResponse:
    """Aggregate repository fields + DECRYPT-FREE credential status.

    The AWS block reads only the non-secret ``label`` metadata (region /
    account / last-4) via ``get_aws_status`` — the secret access key is never
    touched. GitHub is a bare existence probe.
    """
    default_branch = (project.project_metadata or {}).get("default_branch")
    github_configured = CredentialsService.has_credential(
        db, project_id=project.id, provider=GITHUB_PROVIDER,
    )
    aws_meta = CredentialsService.get_aws_status(db, project_id=project.id)
    aws_status = (
        AwsCredentialStatus(configured=False)
        if aws_meta is None
        else AwsCredentialStatus(
            configured=True,
            region=aws_meta.get("region"),
            account_name=aws_meta.get("account_name"),
            access_key_id_last4=aws_meta.get("access_key_id_last4"),
        )
    )
    return ProjectSettingsResponse(
        repository_url=project.repository_url,
        repository_visibility=project.repository_visibility,
        default_branch=default_branch,
        credentials=ProjectCredentialStatus(
            github=ProviderConfigured(configured=github_configured),
            aws=aws_status,
        ),
    )


@router.get("/{project_id}/settings", response_model=ProjectSettingsResponse)
def get_project_settings(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Repository settings + per-provider connected/missing status.

    Membership-gated via ``_load_or_404`` (404 to non-members). Returns NO
    secret values — only ``configured`` flags + non-secret AWS metadata.
    """
    project = _load_or_404(db, project_id, current_user)
    return _build_project_settings_response(db, project)


@router.put("/{project_id}/settings", response_model=ProjectSettingsResponse)
def update_project_settings(
    project_id: str,
    payload: ProjectSettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),  # DEVELOPER+
):
    """Update repository URL / visibility / default branch.

    Credentials are NOT touched here — they go through the stricter
    ``/credentials/*`` endpoints. ``default_branch`` is stored in
    ``project_metadata`` (no dedicated column).
    """
    project = _load_or_404(db, project_id, current_user)
    data = payload.model_dump(exclude_unset=True)

    if "default_branch" in data:
        branch = (data.pop("default_branch") or "").strip()
        meta = dict(project.project_metadata or {})
        if branch:
            meta["default_branch"] = branch
        else:
            meta.pop("default_branch", None)
        project.project_metadata = meta

    for field in ("repository_url", "repository_visibility"):
        if field in data:
            setattr(project, field, data[field])

    db.commit()
    db.refresh(project)
    return _build_project_settings_response(db, project)


@router.get("/{project_id}/artifacts", response_model=list[ArtifactResponse])
def list_project_artifacts(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _load_or_404(db, project_id, current_user)
    return ProjectService.list_artifacts(db, project_id)


@router.get("/{project_id}/workflows", response_model=list[WorkflowResponse])
def list_project_workflows(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _load_or_404(db, project_id, current_user)
    return ProjectService.list_workflows(db, project_id)


@router.get("/{project_id}/members", response_model=list[ProjectMemberResponse])
def list_project_members(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _load_or_404(db, project_id, current_user)
    return ProjectService.list_members(db, project_id)


# ─── Workflow execution ──────────────────────────────────────────────────────

@router.post(
    "/{project_id}/workflows",
    response_model=WorkflowStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_workflow(
    project_id: str,
    payload: StartWorkflowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),  # DEVELOPER+
):
    """Start a workflow for the project (runs architecture-decision phase).

    Enforces one active workflow per project: if the project already has an
    active (non-terminal) workflow — e.g. the one created by project-creation
    bootstrap — that existing workflow is returned instead of creating a
    duplicate. A new workflow is created only when none is active.
    """
    project = _load_or_404(db, project_id, current_user)
    try:
        workflow, task, state = WorkflowOrchestrationService.get_or_create_workflow(
            db,
            project=project,
            user=current_user,
            prompt=payload.prompt,
            execution_mode=payload.execution_mode,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start workflow: {exc}")

    return WorkflowStartResponse(
        workflow_id=workflow.id,
        task_id=task.id,
        project_id=project.id,
        current_phase=workflow.current_phase or "ARCHITECTURE_DECISION",
        status=workflow.status,
        plan=state.get("plan"),
        architecture_decision=state.get("architecture_decision"),
        logs=state.get("logs", []),
    )


def _load_workflow_and_task(db: Session, project_id: str, workflow_id: str, current_user: User):
    project = _load_or_404(db, project_id, current_user)
    workflow = WorkflowOrchestrationService.get_workflow_for_project(db, project.id, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    task = WorkflowOrchestrationService.get_backing_task(db, workflow)
    if task is None:
        raise HTTPException(
            status_code=422,
            detail="Workflow has no backing task — re-create the workflow.",
        )
    return project, workflow, task


@router.post(
    "/{project_id}/workflows/{workflow_id}/select-plan",
    response_model=WorkflowPhaseRunResponse,
)
def select_plan(
    project_id: str,
    workflow_id: str,
    payload: SelectPlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),  # DEVELOPER+
):
    _, workflow, task = _load_workflow_and_task(db, project_id, workflow_id, current_user)
    try:
        state = WorkflowOrchestrationService.select_plan(
            db, workflow=workflow, task=task, plan_id=payload.plan_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Plan selection failed: {exc}")

    return WorkflowPhaseRunResponse(
        workflow_id=workflow.id,
        task_id=task.id,
        current_phase=workflow.current_phase or "",
        status=workflow.status,
        phases_state=workflow.phases_state or {},
        persisted_artifact_ids=[],
        logs=state.get("logs", []),
    )


@router.post(
    "/{project_id}/workflows/{workflow_id}/phases/{phase}",
    response_model=WorkflowPhaseRunResponse,
)
def run_workflow_phase(
    project_id: str,
    workflow_id: str,
    phase: PhaseName,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),  # DEVELOPER+
):
    """Run (or rerun) a single phase. Does NOT restart the orchestration graph.

    Phase-completion contract — the DOCKER phase NEVER returns 500 for an LLM
    problem (rate-limit, token exhaustion, invalid JSON, exhausted fallback
    chain). ``InfrastructureAgent`` degrades to deterministic artifacts, so the
    phase always completes (``completed`` or ``completed_with_fallback``). A 500
    here means infrastructure is genuinely broken (DB / disk / permissions).
    """
    project, workflow, task = _load_workflow_and_task(db, project_id, workflow_id, current_user)
    try:
        state, persisted_ids = WorkflowOrchestrationService.run_phase(
            db,
            project=project,
            workflow=workflow,
            task=task,
            phase=phase,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        # Reaching here for DOCKER implies a true infrastructure failure (the
        # generation path itself is non-raising); surface it as a 500 so it is
        # not silently swallowed.
        raise HTTPException(status_code=500, detail=f"Phase '{phase}' failed: {exc}")

    return WorkflowPhaseRunResponse(
        workflow_id=workflow.id,
        task_id=task.id,
        current_phase=workflow.current_phase or "",
        status=workflow.status,
        phases_state=workflow.phases_state or {},
        persisted_artifact_ids=persisted_ids,
        logs=state.get("logs", []),
    )


# ─── Workflow revision (regenerate a phase + invalidate downstream) ──────────

@router.post(
    "/{project_id}/workflows/{workflow_id}/phases/{phase}/regenerate",
    response_model=RegeneratePhaseResponse,
)
def regenerate_workflow_phase(
    project_id: str,
    workflow_id: str,
    phase: PhaseName,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),  # DEVELOPER+
):
    """Regenerate a COMPLETED phase and invalidate everything downstream.

    Iterative re-design: re-runs the targeted phase (creating the next
    ``ArtifactVersion`` — the previous bytes are preserved, never deleted),
    marks the transitive downstream phases ``invalidated`` so they are re-run
    against the new artifacts, points ``current_phase`` back at the regenerated
    phase, and records a revision-history entry. Does NOT restart the workflow.

    Only the inline generation phases are regeneratable (DOCKER /
    TERRAFORM_GENERATION / GITHUB_ACTIONS_GENERATION). A 400 is returned for a
    non-regeneratable phase or one that has not completed yet.
    """
    project, workflow, task = _load_workflow_and_task(db, project_id, workflow_id, current_user)
    try:
        result = WorkflowRevisionService.regenerate_phase(
            db,
            project=project,
            workflow=workflow,
            task=task,
            phase=phase,
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Regenerate '{phase}' failed: {exc}")

    return RegeneratePhaseResponse(**result)


@router.get(
    "/{project_id}/workflows/{workflow_id}/revisions",
    response_model=WorkflowRevisionHistoryResponse,
)
def get_workflow_revisions(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the workflow's revision history (newest first).

    Read-only — assembled from the revision-history entries the regenerate
    endpoint records in ``Workflow.logs`` (no extra table, no migration). Each
    entry says which phase was regenerated, its new revision number, which
    downstream phases it invalidated, and which artifact versions it superseded.
    """
    _, workflow, _ = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    return WorkflowRevisionService.build_history_payload(workflow)


# ─── Workflow cancellation ───────────────────────────────────────────────────

@router.post(
    "/{project_id}/workflows/{workflow_id}/cancel",
    response_model=WorkflowCancelResponse,
)
def cancel_workflow(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),  # DEVELOPER+
):
    """Cancel a workflow at a deployment/observation phase.

    Cancellable at GITHUB_ACTIONS_GENERATION / REPOSITORY_INSTALLATION /
    WORKFLOW_MONITORING. Stops any in-flight GitHub Actions run (cancel API),
    marks ``status = cancelled``, and PRESERVES every artifact + phase record so
    the run can later be resumed from a previous phase. 400 if the workflow is
    not at a cancellable phase.
    """
    project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    try:
        result = WorkflowCancellationService.cancel(
            db, project=project, workflow=workflow, task=task, user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cancel failed: {exc}")
    return WorkflowCancelResponse(**result)


@router.get(
    "/{project_id}/workflows/{workflow_id}",
    response_model=WorkflowResponse,
)
def get_workflow(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _, workflow, _ = _load_workflow_and_task(db, project_id, workflow_id, current_user)
    return workflow


def _load_workflow_lenient(db: Session, project_id: str, workflow_id: str, current_user: User):
    """Load project + workflow (+ optional backing task).

    Unlike ``_load_workflow_and_task`` this does NOT 422 when a workflow has no
    backing task — the observability/replay layer degrades gracefully (terraform
    replay still works; docker replay is skipped).
    """
    project = _load_or_404(db, project_id, current_user)
    workflow = WorkflowOrchestrationService.get_workflow_for_project(db, project.id, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    task = WorkflowOrchestrationService.get_backing_task(db, workflow)
    return project, workflow, task


@router.get(
    "/{project_id}/workflows/{workflow_id}/debug",
    response_model=None,
)
def get_workflow_debug(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Unified observability view for a workflow.

    Returns the full phase timeline, the DB-backed artifacts list, failure
    classifications, the materialised execution trace, and an artifact
    completeness audit. Read-only — it materialises the live trace from the
    authoritative ``Workflow.phases_state`` but never alters workflow state.
    """
    _project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    task_state = TaskService.load_workflow_state(db, task) if task else {}
    return WorkflowTraceService.build_debug_payload(
        db, workflow=workflow, task_state=task_state,
    )


@router.post(
    "/{project_id}/workflows/{workflow_id}/replay",
    response_model=None,
)
def replay_workflow(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),  # DEVELOPER+
):
    """Deterministically re-execute a workflow from DB artifacts ONLY.

    Re-runs terraform validate/plan and the docker build using the artifacts
    already persisted in the database. Performs NO LLM calls and NO regeneration
    of terraform/Dockerfile. Returns a summary of the re-enqueued steps.
    """
    project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    try:
        return WorkflowReplayService.replay(
            db, project=project, workflow=workflow, task=task,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Replay failed: {exc}")


# ─── Artifact detail with version history ────────────────────────────────────

@router.get(
    "/{project_id}/artifacts/{artifact_id}",
    response_model=ArtifactDetailResponse,
)
def get_artifact_with_versions(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _load_or_404(db, project_id, current_user)
    artifact = ArtifactPersistenceService.get_artifact(db, artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    versions = ArtifactPersistenceService.list_versions(db, artifact.id)
    approvals = ArtifactApprovalService.list_for_artifact(db, artifact.id)

    payload = ArtifactDetailResponse.model_validate(artifact).model_dump()
    payload["versions"] = [
        ArtifactVersionResponse.model_validate(v).model_dump() for v in versions
    ]
    payload["approvals"] = [
        ArtifactApprovalResponse.model_validate(a).model_dump() for a in approvals
    ]
    return payload


@router.get(
    "/{project_id}/artifacts/{artifact_id}/versions/{version}",
    response_model=ArtifactVersionResponse,
)
def get_artifact_version(
    project_id: str,
    artifact_id: str,
    version: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _load_or_404(db, project_id, current_user)
    artifact = ArtifactPersistenceService.get_artifact(db, artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    row = ArtifactPersistenceService.get_version(db, artifact.id, version)
    if row is None:
        raise HTTPException(status_code=404, detail="Version not found")
    return row


# ─── Architecture decision read ──────────────────────────────────────────────

@router.get("/{project_id}/workflows/{workflow_id}/architecture-decision")
def get_architecture_decision(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the architecture-decision payload (plans + recommended_plan).

    Returns 404 if the workflow has no architecture_decision yet (e.g. the
    workflow failed before reaching the planner).
    """
    _, workflow, task = _load_workflow_and_task(db, project_id, workflow_id, current_user)
    state = (task.workflow_state or {}) if task else {}
    arch = state.get("architecture_decision") or {}
    if not arch.get("plans"):
        raise HTTPException(status_code=404, detail="No architecture decision yet")
    return {
        "workflow_id":       workflow.id,
        "current_phase":     workflow.current_phase,
        "status":            workflow.status,
        "selected_plan_id":  state.get("selected_plan_id"),
        "plans":             arch.get("plans"),
        "recommended_plan":  arch.get("recommended_plan"),
    }


# ─── Docker Generation phase read (projection) ───────────────────────────────

@router.get(
    "/{project_id}/workflows/{workflow_id}/docker",
    response_model=DockerPhaseResponse,
)
def get_docker_phase(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregated Docker-Generation payload (generation + validation + corrector).

    READ-ONLY projection over data the DOCKER phase already persisted — the
    Docker analogue of ``/architecture-decision`` and ``/workflow-analysis``. It
    NEVER re-runs the InfrastructureAgent, the corrector, or calls an LLM. One
    response feeds the whole Docker surface (generated Dockerfile + metadata +
    validation findings + corrector analysis + approved-artifact provenance).

    Degrades gracefully: a workflow that has not reached DOCKER yet projects to
    ``generated=False`` (200, not 404) so the surface can show an honest "not
    generated yet" state alongside the option to run the phase.
    """
    _, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    return DockerPhaseProjectionService.build(
        db, project_id=workflow.project_id, workflow=workflow, task=task,
    )


# ─── GitHub Actions Generation phase read (projection) ───────────────────────

@router.get(
    "/{project_id}/workflows/{workflow_id}/github-actions",
    response_model=GitHubActionsPhaseResponse,
)
def get_github_actions_phase(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregated GitHub Actions Generation payload (deploy.yml + context + validation).

    READ-ONLY projection over data the GITHUB_ACTIONS_GENERATION phase already
    persisted — the deployment analogue of ``/docker``. It NEVER re-runs
    generation or calls an LLM. Degrades gracefully: a workflow that has not
    reached the phase projects to ``generated=False`` (200, not 404).
    """
    _, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    return GitHubActionsPhaseProjectionService.build(
        db, project_id=workflow.project_id, workflow=workflow, task=task,
    )


# ─── Repository Installation phase read (projection) ─────────────────────────

@router.get(
    "/{project_id}/workflows/{workflow_id}/repository-installation",
    response_model=RepositoryInstallationPhaseResponse,
)
def get_repository_installation_phase(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregated Repository Installation payload (branch + commit + PR + logs).

    READ-ONLY projection over data the REPOSITORY_INSTALLATION phase already
    persisted — the installation analogue of ``/github-actions``. It NEVER clones,
    commits, or pushes. Degrades gracefully: a workflow that has not reached the
    phase projects to ``installed=False`` (200, not 404), with
    ``prerequisites_met`` reflecting whether the generated pipelines exist yet.
    """
    project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    return RepositoryInstallationProjectionService.build(
        db, project_id=workflow.project_id, workflow=workflow, task=task, project=project,
    )


# ─── Workflow Monitoring phase read (live GitHub Actions observation) ─────────

@router.get(
    "/{project_id}/workflows/{workflow_id}/monitoring",
    response_model=WorkflowMonitoringPhaseResponse,
)
def get_workflow_monitoring(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Observe the installed pipelines' GitHub Actions runs (bootstrap + deploy).

    READ-ONLY: this NEVER triggers, reruns, cancels, or modifies a workflow or
    the repository. On each call it queries the GitHub Actions API for the latest
    run of bootstrap.yml + deploy.yml and returns a monitoring snapshot; the
    frontend polls it (~30s) or refreshes manually. Monitoring failures (no
    token, missing permission, deleted repo/workflow, rate limit, API error)
    degrade to a 200 with ``monitoring_available=false`` + a reason — they NEVER
    fail the workflow.
    """
    project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    return WorkflowMonitoringService.build(
        db, project=project, workflow=workflow, task=task,
    )


# ─── Infrastructure Destroy phase read (projection + live observation) ────────

@router.get(
    "/{project_id}/workflows/{workflow_id}/destroy",
    response_model=InfrastructureDestroyPhaseResponse,
)
def get_infrastructure_destroy(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregated Infrastructure Destroy payload (lifecycle + live destroy.yml run).

    READ-ONLY: it never runs Terraform, never installs, never dispatches. It
    reports the persisted lifecycle state (requested / running / succeeded /
    failed) and, when the phase has run, observes the latest ``destroy.yml`` run
    EXACTLY like bootstrap.yml — reconciling the terminal state (succeeded /
    failed) from the run conclusion so the deletion guard sees it. Degrades
    gracefully: a workflow that has not destroyed yet projects with
    ``prerequisites_met`` reflecting whether a destroy can be triggered.
    """
    project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    return InfrastructureDestroyService.get_status(
        db, project=project, workflow=workflow, task=task,
    )


# ─── Infrastructure Recovery phase read (diagnostic — read-only) ──────────────

@router.get(
    "/{project_id}/workflows/{workflow_id}/recovery",
    response_model=InfrastructureRecoveryPhaseResponse,
)
def get_infrastructure_recovery(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Structured, READ-ONLY recovery diagnosis for a failed provisioning.

    After ``bootstrap.yml`` fails during ``terraform apply``, this observes the
    failed run (read-only, like monitoring), inspects the generated Terraform +
    remote state backend, classifies the failure, and returns a ``RecoveryReport``
    with recommendations. It NEVER runs Terraform (no apply / destroy / import),
    never touches AWS, and never modifies the workflow lifecycle — it only
    persists a recovery artifact + a diagnostic marker. The engineer decides what
    to do; the recovery actions are disabled placeholders. Degrades gracefully
    (``recovery_available=false``) when there is no failure to diagnose.
    """
    project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    return InfrastructureRecoveryService.get_status(
        db, project=project, workflow=workflow, task=task,
    )


# ─── Infrastructure Lifecycle phase (operational dashboard + actions) ─────────

# Roles allowed to manage infrastructure (retry/destroy). VIEWER is read-only.
_LIFECYCLE_MANAGE_ROLES = {"DEVELOPER", "CLOUD_ARCHITECT", "OWNER", "ADMIN"}


def _can_manage_infrastructure(db: Session, project, current_user: User) -> bool:
    """True when the caller may retry/destroy (engineer/admin/owner), else False.

    Read-only members (VIEWER) get False, so the dashboard renders the actions
    disabled. The action endpoints additionally enforce this server-side via
    ``require_project_contributor``.
    """
    if getattr(project, "owner_id", None) == current_user.id:
        return True
    if (getattr(current_user, "role", "") or "").upper() == "ADMIN":
        return True
    member = (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == current_user.id,
        )
        .first()
    )
    role = (getattr(member, "role", "") or "").upper()
    return role in _LIFECYCLE_MANAGE_ROLES


@router.get(
    "/{project_id}/workflows/{workflow_id}/lifecycle",
    response_model=InfrastructureLifecyclePhaseResponse,
)
def get_infrastructure_lifecycle(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The Infrastructure Lifecycle dashboard (status + state + inventory +
    recovery + history + actions). READ-ONLY: it aggregates the existing destroy
    / monitoring / recovery / import surfaces and the immutable lifecycle history;
    it never runs Terraform or mutates the generation lifecycle. ``can_manage``
    reflects whether the caller may retry/destroy (read-only users get False).
    """
    project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    can_manage = _can_manage_infrastructure(db, project, current_user)
    return InfrastructureLifecycleService.get_status(
        db, project=project, workflow=workflow, task=task, can_manage=can_manage,
    )


@router.post(
    "/{project_id}/workflows/{workflow_id}/lifecycle/retry-bootstrap",
    response_model=LifecycleActionResult,
)
def retry_bootstrap(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),  # DEVELOPER+ (no VIEWER)
):
    """Re-dispatch bootstrap.yml — ONLY when the last bootstrap failed.

    GitHub Actions runs the bootstrap (the backend never runs Terraform). Records
    an immutable ``BOOTSTRAP_RETRY`` lifecycle event. Returns 409 when bootstrap
    is not in a failed state.
    """
    project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    result = InfrastructureLifecycleService.retry_bootstrap(
        db, project=project, workflow=workflow, task=task, actor_id=current_user.id,
    )
    if result.status == "blocked":
        raise HTTPException(status_code=409, detail=result.message)
    return result


@router.post(
    "/{project_id}/workflows/{workflow_id}/lifecycle/destroy",
    response_model=LifecycleActionResult,
)
def lifecycle_destroy(
    project_id: str,
    workflow_id: str,
    body: DestroyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),  # DEVELOPER+ (no VIEWER)
):
    """Dispatch destroy.yml after a TWO-step confirmation + lifecycle guards.

    Requires ``confirm`` AND ``acknowledge_data_loss``. Never destroys after a
    bootstrap failure, while a run is in progress, or when already destroyed.
    GitHub Actions runs ``terraform destroy`` (never the backend); monitoring
    observes it exactly like bootstrap/deploy. Records ``DESTROY_REQUESTED``.
    """
    project, workflow, task = _load_workflow_lenient(db, project_id, workflow_id, current_user)
    result = InfrastructureLifecycleService.request_destroy(
        db, project=project, workflow=workflow, task=task,
        confirm=body.confirm, acknowledge_data_loss=body.acknowledge_data_loss,
        actor_id=current_user.id,
    )
    if result.status == "blocked":
        raise HTTPException(status_code=409, detail=result.message)
    return result


# ─── Project context (intelligence layer) ───────────────────────────────────

@router.get(
    "/{project_id}/context",
    response_model=list[ProjectContextResponse],
)
def list_project_context(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List every persisted ProjectContext digest for the project."""
    _load_or_404(db, project_id, current_user)
    return ProjectContextService.list_for_project(db, project_id)


# ─── Consolidated analysis + security results ────────────────────────────────

@router.get(
    "/{project_id}/analysis",
    response_model=ProjectAnalysisResponse,
)
def get_project_analysis(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the consolidated codebase-analysis + security payload.

    Read-only assembly from data the bootstrap pipeline already persisted
    (ProjectContext digests + the backing task's transformed security block).
    The frontend polls this while ``bootstrap_status`` is non-terminal to drive
    the Analysis-status component, then renders the Analysis + Security tabs.
    Never returns credential material.
    """
    project = _load_or_404(db, project_id, current_user)
    return ProjectAnalysisService.build_payload(db, project)


@router.get(
    "/{project_id}/workflow-analysis",
    response_model=WorkflowAnalysisResponse,
)
def get_project_workflow_analysis(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Project-scoped projection of the Analysis phase (the FIVE sections).

    A READ-ONLY view of the SAME persisted analysis that powers
    ``GET /{project_id}/analysis`` — it calls the identical
    ``ProjectAnalysisService.build_payload`` (via the aggregation service) and
    only reshapes it into the five Analysis-phase sections. It NEVER re-runs
    analysis, calls an LLM, or writes records. Same access rule as /analysis.
    """
    project = _load_or_404(db, project_id, current_user)
    return WorkflowAnalysisAggregationService.build_for_project(db, project)


# ─── Artifact approval workflow ──────────────────────────────────────────────
#
# Authorization: only CLOUD_ARCHITECT, ADMIN, and OWNER may issue approval
# decisions on infrastructure artifacts. Enforced by ``require_project_approver``
# below — this is the single source of truth, the frontend role gating is for
# UX only.

@router.post(
    "/{project_id}/artifacts/{artifact_id}/approvals",
    response_model=ArtifactApprovalResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_artifact_approval(
    project_id: str,
    artifact_id: str,
    payload: ArtifactApprovalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_approver),  # authz gate
):
    artifact = ArtifactPersistenceService.get_artifact(db, artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        _, approval = ArtifactApprovalService.record(
            db,
            artifact=artifact,
            user_id=current_user.id,
            action=payload.action,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return approval


@router.get(
    "/{project_id}/artifacts/{artifact_id}/approvals",
    response_model=list[ArtifactApprovalResponse],
)
def list_artifact_approvals(
    project_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _load_or_404(db, project_id, current_user)
    artifact = ArtifactPersistenceService.get_artifact(db, artifact_id)
    if artifact is None or artifact.project_id != project_id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return ArtifactApprovalService.list_for_artifact(db, artifact.id)


# ─── Membership management ──────────────────────────────────────────────────

@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_project_member(
    project_id: str,
    payload: ProjectMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_role()),  # OWNER/ADMIN only
):
    project = _load_or_404(db, project_id, current_user)
    existing = (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == project.id,
            ProjectMember.user_id == payload.user_id,
        )
        .first()
    )
    if existing:
        existing.role = payload.role
        db.commit()
        db.refresh(existing)
        return existing
    row = ProjectMember(project_id=project.id, user_id=payload.user_id, role=payload.role)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch(
    "/{project_id}/members/{member_id}",
    response_model=ProjectMemberResponse,
)
def update_project_member(
    project_id: str,
    member_id: str,
    payload: ProjectMemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_role()),  # OWNER/ADMIN only
):
    _load_or_404(db, project_id, current_user)
    row = (
        db.query(ProjectMember)
        .filter(ProjectMember.id == member_id, ProjectMember.project_id == project_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Member not found")
    row.role = payload.role
    db.commit()
    db.refresh(row)
    return row


# NOTE: /me/identity is declared near the top of this file, BEFORE the
# /{project_id} dynamic route. See the route-ordering comment block above.
