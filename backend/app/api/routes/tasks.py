import json
import traceback

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.agents.orchestrator_agent import OrchestratorAgent
from backend.app.database.session import SessionLocal
from backend.app.schemas.task import (
    GenerateArtifactsRequest,
    PlanPreviewRequest,
    PlanPreviewResponse,
    ReviewArtifactsRequest,
    TaskCreate,
    TaskResponse,
    ValidatePlanRequest,
    ValidatePlanResponse,
)
from backend.app.services.core.task_service import TaskService
from backend.app.services.environment.uploaded_env_file_service import UploadedEnvFileService

router = APIRouter(prefix="/tasks", tags=["Tasks"])
uploaded_env_service = UploadedEnvFileService()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/", response_model=TaskResponse)
async def create_task(request: Request, db: Session = Depends(get_db)):
    payload, uploaded_env_input = await _parse_task_request(request, TaskCreate)
    task = TaskService.create_task(db, payload.prompt)

    try:
        TaskService.update_task_status(db, task, "in_progress")

        orchestrator = OrchestratorAgent()
        workflow_state = orchestrator.run(
            prompt=payload.prompt,
            repo_url=payload.repo_url,
            repository_visibility=payload.repository_visibility,
            github_token=payload.github_token,
            uploaded_env_input=uploaded_env_input,
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
async def plan_preview(request: Request, db: Session = Depends(get_db)):
    """
    Bloc 7 — Phase 1: run repository analysis + planning, then pause.

    Returns ``task_id`` and ``requires_user_input=True`` so the caller can
    present the plan to the user before any artifact is generated.
    Execution resumes via ``POST /tasks/validate-plan``.
    """
    payload, uploaded_env_input = await _parse_task_request(request, PlanPreviewRequest)

    task = TaskService.create_task(db, payload.prompt)
    TaskService.update_task_status(db, task, "in_progress")

    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.run_plan_preview(
            prompt=payload.prompt,
            repo_url=payload.repo_url,
            repository_visibility=payload.repository_visibility,
            github_token=payload.github_token,
            uploaded_env_input=uploaded_env_input,
        )

        # Persist the full workflow state so validate-plan can resume it.
        TaskService.save_plan_awaiting_validation(db, task, state)

        return {
            "task_id": task.id,
            "status": state.get("status"),
            "requires_user_input": True,
            "plan": state.get("plan"),
            "cost_estimation": state.get("cost_estimation"),
            "repository_security": state.get("repository_security"),
            "security": state.get("security"),
            "repo_summary": state.get("repo_summary"),
            "logs": state.get("logs", []),
        }
    except Exception as e:
        traceback.print_exc()
        TaskService.save_error(db, task, str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Plan preview failed: {type(e).__name__}: {str(e)}",
        )


@router.post("/validate-plan", response_model=ValidatePlanResponse)
async def validate_plan(payload: ValidatePlanRequest, db: Session = Depends(get_db)):
    """
    Bloc 7 — Phase 2: receive the human decision and resume the pipeline.

    Decision values
    ---------------
    * ``approved``  → run artifact generation and return the final result.
    * ``rejected``  → stop; return a rejection response.
    * ``modified``  → replan with ``feedback``; return the new plan with
                      ``requires_user_input=True`` for another validation round.
    """
    task = TaskService.get_task(db, payload.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ("awaiting_plan_validation", "in_progress"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Task is in status '{task.status}' and cannot accept a plan decision. "
                "Only tasks in 'awaiting_plan_validation' can be validated."
            ),
        )

    prior_state = TaskService.load_workflow_state(db, task)
    if not prior_state:
        raise HTTPException(
            status_code=422,
            detail="No persisted workflow state found for this task. Re-run plan-preview first.",
        )

    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.resume_with_human_decision(
            prior_state=prior_state,
            decision=payload.decision,
            feedback=payload.feedback,
        )

        # ── Rejected ─────────────────────────────────────────────────────────
        if payload.decision == "rejected":
            TaskService.update_task_status(db, task, "rejected")
            TaskService.append_log(
                db, task, "human_validation",
                f"Plan rejected. Reason: {payload.feedback or 'Not specified'}",
            )
            return ValidatePlanResponse(
                task_id=task.id,
                decision="rejected",
                status="rejected",
                requires_user_input=False,
                rejection_reason=payload.feedback or "Plan rejected by user",
                logs=state.get("logs", []),
            )

        # ── Modified — new plan ready, waiting for next decision ──────────────
        if payload.decision == "modified":
            TaskService.save_plan_awaiting_validation(db, task, state)
            return ValidatePlanResponse(
                task_id=task.id,
                decision="modified",
                status="awaiting_plan_validation",
                requires_user_input=True,
                plan=state.get("plan"),
                cost_estimation=state.get("cost_estimation"),
                logs=state.get("logs", []),
            )

        # ── Approved — full generation completed ──────────────────────────────
        for log in state.get("logs", []):
            if log.get("step") not in ("task_created", "human_validation"):
                TaskService.append_log(db, task, log["step"], log["message"])

        if state.get("plan"):
            TaskService.save_plan(db, task, state["plan"])

        if state.get("result"):
            TaskService.save_result(db, task, state["result"])
            if state["result"].get("infrastructure", {}).get("artifacts"):
                TaskService.initialize_human_review(db, task)
            else:
                TaskService.update_task_status(db, task, state.get("status", "completed"))
        else:
            TaskService.update_task_status(db, task, state.get("status", "completed"))

        return ValidatePlanResponse(
            task_id=task.id,
            decision="approved",
            status=state.get("status", "completed"),
            requires_user_input=False,
            result=state.get("result"),
            logs=state.get("logs", []),
        )

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        TaskService.save_error(db, task, str(e))
        raise HTTPException(status_code=500, detail=f"Plan validation failed: {str(e)}")


@router.post("/generate", response_model=TaskResponse)
async def generate_artifacts(request: Request, db: Session = Depends(get_db)):
    payload, uploaded_env_input = await _parse_task_request(
        request,
        GenerateArtifactsRequest,
        include_approved_artifacts=True,
    )
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
            uploaded_env_input=uploaded_env_input,
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


async def _parse_task_request(
    request: Request,
    model_class,
    *,
    include_approved_artifacts: bool = False,
):
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        payload_data = await request.json()
        return model_class(**payload_data), None

    form = await request.form()
    payload_data = {
        "prompt": (form.get("prompt") or "").strip(),
        "repo_url": _normalize_optional(form.get("repo_url")),
        "repository_visibility": _normalize_optional(form.get("repository_visibility")) or "public",
        "github_token": _normalize_optional(form.get("github_token")),
    }

    if include_approved_artifacts:
        approved_artifacts = [
            str(item)
            for item in form.getlist("approved_artifacts")
            if str(item).strip()
        ]
        if not approved_artifacts and form.get("approved_artifacts"):
            try:
                approved_artifacts = json.loads(str(form.get("approved_artifacts")))
            except Exception:
                approved_artifacts = [str(form.get("approved_artifacts"))]
        payload_data["approved_artifacts"] = approved_artifacts

    uploaded_env_input = None
    env_file = form.get("env_file")
    if getattr(env_file, "filename", None):
        uploaded_env_input = await uploaded_env_service.build_input_from_upload(env_file)

    return model_class(**payload_data), uploaded_env_input


def _normalize_optional(value):
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
