import traceback

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.authorization import (
    require_task_project_contributor,
    require_task_project_member,
)
from backend.app.core.security import get_current_user
from backend.app.database.session import SessionLocal
from backend.app.models.project import ProjectMember
from backend.app.models.task import Task
from backend.app.schemas.task import (
    ReviewArtifactsRequest,
    TaskResponse,
)
from backend.app.services.core.task_service import TaskService

# Phase 1 — Execution authorization unification.
#
# Per-task routes now resolve the owning project through the
# ``require_task_project_*`` dependencies (see core/authorization.py).
# The global list (GET /tasks/) and global creation (POST /tasks/) endpoints
# were removed because they had no way to enforce project scope and were
# never reachable from the project-centric UI flow. New work goes through
# /api/projects/{project_id}/workflows.
router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
    dependencies=[Depends(get_current_user)],
)


# Endpoints that used to be globally addressable (no project context) are
# refused with 410 Gone — the route is preserved as a tombstone so existing
# clients receive a structured error rather than a confusing 404.
_GONE_PAYLOAD = {
    "detail": (
        "This endpoint was removed in the Phase 1 authorization "
        "unification. Use the project-scoped equivalent under "
        "/api/projects/{project_id}/workflows instead."
    ),
}


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/", status_code=status.HTTP_410_GONE)
async def create_task_gone():
    """Removed in Phase 1.

    Used to accept an unconstrained POST /tasks/ that created a task with
    no project linkage. Replaced by project-scoped workflow creation under
    /api/projects/{project_id}/workflows, which carries the role gate.
    """
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_GONE_PAYLOAD["detail"])


@router.get("/", status_code=status.HTTP_410_GONE)
def list_tasks_gone():
    """Removed in Phase 1.

    Used to return every task in the database to any authenticated caller —
    the unscoped fetch that the audit flagged as a cross-tenant leak. Use
    /api/projects/{project_id}/workflows to enumerate workflows for a
    specific project instead.
    """
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_GONE_PAYLOAD["detail"])


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_member),
):
    # The gate resolved the task and verified membership. We re-fetch only
    # because TaskService.get_task may eagerly load extras; the gate has
    # already validated existence and project scope.
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.post("/plan-preview", status_code=status.HTTP_410_GONE)
async def plan_preview_gone():
    """Removed in Phase 1 — see ``create_task_gone`` for the migration path.

    The plan-preview endpoint used to create an unscoped task. Its callers
    must transition to ``POST /api/projects/{project_id}/workflows`` which
    runs the architecture-decision phase inside a project boundary.
    """
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_GONE_PAYLOAD["detail"])


@router.post("/validate-plan", status_code=status.HTTP_410_GONE)
async def validate_plan_gone():
    """Removed in Phase 1.

    Resumed an unscoped task by id, with no project gate. Use
    ``POST /api/projects/{project_id}/workflows/{workflow_id}/select-plan``
    instead — same logical step, project-scoped, role-gated.
    """
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_GONE_PAYLOAD["detail"])


@router.post("/generate", status_code=status.HTTP_410_GONE)
async def generate_artifacts_gone():
    """Removed in Phase 1.

    Generated artifacts on an unscoped task. The replacement path is the
    project-scoped per-phase run endpoint
    ``POST /api/projects/{project_id}/workflows/{workflow_id}/phases/{phase}``.
    """
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_GONE_PAYLOAD["detail"])


@router.post("/{task_id}/review", response_model=TaskResponse)
def review_artifacts(
    task_id: str,
    payload: ReviewArtifactsRequest,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
):
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    result = task.result or {}
    human_review = result.get("human_review") or {}
    infrastructure = result.get("infrastructure") or {}
    original_artifacts = (
        human_review.get("original_artifacts")
        or infrastructure.get("artifacts")
        or {}
    )

    if not original_artifacts:
        raise HTTPException(
            status_code=400,
            detail="No generated artifacts are available for review on this task.",
        )

    if not payload.reviewed_artifacts:
        raise HTTPException(
            status_code=400,
            detail="At least one artifact must be provided for review.",
        )

    try:
        TaskService.apply_human_review(
            db,
            task,
            reviewed_artifacts=payload.reviewed_artifacts,
            review_notes=payload.review_notes,
        )
        TaskService.append_log(
            db,
            task,
            "human_review_completed",
            "User approved the generated artifacts after review",
        )
        return task
    except Exception as e:
        traceback.print_exc()
        TaskService.save_error(db, task, str(e))
        raise HTTPException(status_code=500, detail=f"Artifact review failed: {str(e)}")


