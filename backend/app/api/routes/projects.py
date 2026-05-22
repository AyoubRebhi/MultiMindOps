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
    ProjectContextResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectMemberCreate,
    ProjectMemberResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectUpdate,
    SelectPlanRequest,
    StartWorkflowRequest,
    WorkflowPhaseRunResponse,
    WorkflowResponse,
    WorkflowStartResponse,
)
from backend.app.services.core.artifact_approval_service import ArtifactApprovalService
from backend.app.services.core.artifact_persistence_service import ArtifactPersistenceService
from backend.app.services.core.project_bootstrap_service import (
    ProjectBootstrapService,
    schedule_bootstrap,
)
from backend.app.services.core.project_context_service import ProjectContextService
from backend.app.services.core.project_service import ProjectService
from backend.app.services.core.workflow_orchestration_service import (
    WorkflowOrchestrationService,
)

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
    """Reset bootstrap_status to pending and re-schedule analysis.

    Used by the ProjectDetail "Analysis failed → Retry" UI. Only the owner
    or members with write access (DEVELOPER+) should be able to call this;
    the membership check inside ``_load_or_404`` enforces the membership
    requirement, role gating can be tightened later.
    """
    project = _load_or_404(db, project_id, current_user)
    ProjectBootstrapService.reset_for_retry(db, project)
    schedule_bootstrap(
        background_tasks,
        project_id=project.id,
        user_id=current_user.id,
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
    """Start a new workflow for the project (runs architecture-decision phase)."""
    project = _load_or_404(db, project_id, current_user)
    try:
        workflow, task, state = WorkflowOrchestrationService.start_workflow(
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
    """Run (or rerun) a single phase. Does NOT restart the orchestration graph."""
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
