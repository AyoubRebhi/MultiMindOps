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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.security import get_current_user, get_db
from backend.app.models.user import User
from backend.app.schemas.project import (
    ArtifactDetailResponse,
    ArtifactResponse,
    ArtifactVersionResponse,
    PhaseName,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectMemberResponse,
    ProjectResponse,
    ProjectUpdate,
    SelectPlanRequest,
    StartWorkflowRequest,
    WorkflowPhaseRunResponse,
    WorkflowResponse,
    WorkflowStartResponse,
)
from backend.app.services.core.artifact_persistence_service import ArtifactPersistenceService
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ProjectService.create_project(db, current_user, payload)


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return ProjectService.list_projects_for_user(db, current_user)


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

    payload = ArtifactDetailResponse.model_validate(artifact).model_dump()
    payload["versions"] = [
        ArtifactVersionResponse.model_validate(v).model_dump() for v in versions
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
