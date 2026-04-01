import traceback

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agents.orchestrator_agent import OrchestratorAgent
from backend.app.database.session import SessionLocal
from backend.app.schemas.task import TaskCreate, TaskResponse
from backend.app.services.task_service import TaskService
from backend.app.schemas.task import (
    GenerateArtifactsRequest,
    PlanPreviewRequest,
    PlanPreviewResponse,
    ReviewArtifactsRequest,
)
router = APIRouter(prefix="/tasks", tags=["Tasks"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/", response_model=TaskResponse)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    task = TaskService.create_task(db, payload.prompt)

    try:
        TaskService.update_task_status(db, task, "in_progress")

        orchestrator = OrchestratorAgent()
        workflow_state = orchestrator.run(
            prompt=payload.prompt,
            repo_url=payload.repo_url,
            repository_visibility=payload.repository_visibility,
            github_token=payload.github_token,
        )

        for log in workflow_state.get("logs", []):
            if log["step"] != "task_created":
                TaskService.append_log(db, task, log["step"], log["message"])

        if workflow_state.get("plan"):
            TaskService.save_plan(db, task, workflow_state["plan"])

        if workflow_state.get("result"):
            TaskService.save_result(db, task, workflow_state["result"])

        TaskService.update_task_status(db, task, workflow_state.get("status", "completed"))

    except Exception as e:
        traceback.print_exc()
        TaskService.save_error(db, task, str(e))
        raise HTTPException(status_code=500, detail=f"Task processing failed: {str(e)}")

    return task

@router.get("/", response_model=list[TaskResponse])
def list_tasks(db: Session = Depends(get_db)):
    return TaskService.list_tasks(db)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.post("/plan-preview", response_model=PlanPreviewResponse)
def plan_preview(payload: PlanPreviewRequest):
    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.run_plan_preview(
            prompt=payload.prompt,
            repo_url=payload.repo_url,
            repository_visibility=payload.repository_visibility,
            github_token=payload.github_token,
        )

        return {
            "status": state.get("status"),
            "plan": state.get("plan"),
            "repository_security": state.get("repository_security"),
            "repo_summary": state.get("repo_summary"),
            "logs": state.get("logs", []),
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Plan preview failed: {type(e).__name__}: {str(e)}"
        ) 
@router.post("/generate", response_model=TaskResponse)
def generate_artifacts(payload: GenerateArtifactsRequest, db: Session = Depends(get_db)):
    task = TaskService.create_task(db, payload.prompt)

    try:
        TaskService.update_task_status(db, task, "in_progress")

        orchestrator = OrchestratorAgent()
        workflow_state = orchestrator.run_generation(
            prompt=payload.prompt,
            repo_url=payload.repo_url,
            repository_visibility=payload.repository_visibility,
            github_token=payload.github_token,
            approved_artifacts=payload.approved_artifacts,
        )

        for log in workflow_state.get("logs", []):
            if log["step"] != "task_created":
                TaskService.append_log(db, task, log["step"], log["message"])

        if workflow_state.get("plan"):
            TaskService.save_plan(db, task, workflow_state["plan"])

        if workflow_state.get("result"):
            TaskService.save_result(db, task, workflow_state["result"])

        if workflow_state.get("result", {}).get("infrastructure", {}).get("artifacts"):
            TaskService.initialize_human_review(db, task)
            TaskService.append_log(
                db,
                task,
                "human_review",
                "Artifacts saved and waiting for human approval",
            )
        else:
            TaskService.update_task_status(db, task, workflow_state.get("status", "completed"))
        return task

    except Exception as e:
        traceback.print_exc()
        TaskService.save_error(db, task, str(e))
        raise HTTPException(status_code=500, detail=f"Artifact generation failed: {str(e)}")


@router.post("/{task_id}/review", response_model=TaskResponse)
def review_artifacts(
    task_id: str,
    payload: ReviewArtifactsRequest,
    db: Session = Depends(get_db),
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
