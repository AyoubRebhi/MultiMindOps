"""
Step-by-step workflow router.

Each phase runs only after the previous one is explicitly approved by the user.

Flow
----
POST /workflow/plan                → run planning only, return plan for review
POST /workflow/{id}/run-docker     → run InfrastructureAgent, return Docker artifacts
POST /workflow/{id}/run-terraform  → run TerraformAgent, return .tf files
POST /workflow/{id}/run-kubernetes → run KubernetesAgent, return YAML manifests
POST /workflow/{id}/run-cicd       → run CI/CD + finalize, return complete result
GET  /workflow/{id}                → poll current phase and artifacts

State machine (current_phase field in workflow_state):
  planning_complete → docker_completed → terraform_completed →
  kubernetes_completed → completed
"""

from __future__ import annotations

import traceback
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.agents.orchestrator_agent import OrchestratorAgent
from backend.app.database.session import SessionLocal
from backend.app.services.core.artifact_service import ArtifactService
from backend.app.services.core.task_service import TaskService
from backend.app.services.environment.uploaded_env_file_service import UploadedEnvFileService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow", tags=["Workflow"])
_env_service = UploadedEnvFileService()


# ── DB dependency ─────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Request / response schemas ────────────────────────────────────────────────

class WorkflowStartRequest(BaseModel):
    prompt: str
    repo_url: str = ""
    repository_visibility: str = "public"
    github_token: str | None = None
    approved_artifacts: list[str] = []


class WorkflowPhaseResponse(BaseModel):
    task_id: str
    current_phase: str
    status: str
    artifacts: dict[str, Any] = {}
    terraform_outputs: dict[str, Any] = {}
    logs: list[Any] = []
    message: str = ""
    # Populated only for architecture-decision and GET state calls
    architecture_decision: dict[str, Any] | None = None
    # Infrastructure context grounding — topology metadata from the Docker phase
    topology_summary: dict[str, Any] | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_artifacts(state: dict) -> dict[str, str]:
    """
    Pull artifacts, preferring user-edited content over generated.

    Priority (highest first):
      1. state["artifacts"][key]["current_content"]  — user-edited (wins)
      2. state["infra"]["artifacts"][key]            — original generated (fallback)
    """
    # Base: all generated artifacts
    infra = state.get("infra") or {}
    result: dict[str, str] = dict(infra.get("artifacts") or {})

    # Override with user-edited current_content where available
    for key, entry in (state.get("artifacts") or {}).items():
        if isinstance(entry, dict):
            content = entry.get("current_content")
            if content:
                result[key] = content

    return result


def _phase_response(task_id: str, state: dict, message: str = "") -> dict:
    return {
        "task_id":               task_id,
        "current_phase":         state.get("current_phase", "unknown"),
        "status":                state.get("status", "in_progress"),
        "artifacts":             _extract_artifacts(state),
        "terraform_outputs":     state.get("terraform_outputs") or {},
        "logs":                  state.get("logs", []),
        "message":               message,
        "architecture_decision": state.get("architecture_decision"),
        "topology_summary":      state.get("topology_summary"),
    }


def _load_state(db: Session, task_id: str) -> dict:
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    state = TaskService.load_workflow_state(db, task)
    if not state:
        raise HTTPException(
            status_code=422,
            detail="No workflow state found for this task. Run /workflow/plan first.",
        )
    return state, task


class SelectPlanRequest(BaseModel):
    plan_id: str  # "low_cost" | "balanced" | "high_performance"


# ── Architecture Decision phase (replaces /plan for new workflow) ─────────────

@router.post("/architecture-decision", response_model=WorkflowPhaseResponse)
async def workflow_architecture_decision(request: Request, db: Session = Depends(get_db)):
    """
    Unified PLAN + COST_ESTIMATION replacement.

    Runs repository analysis (if repo_url provided) then generates 1–3 deployment
    strategies each enriched with AWS cost estimates.  Returns all strategies for
    user comparison before any infrastructure is generated.

    Frontend must NOT call run-docker until /select-plan is called first.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload_data = await request.json()
        prompt      = payload_data.get("prompt", "")
        repo_url    = payload_data.get("repo_url") or ""
        visibility  = payload_data.get("repository_visibility") or "public"
        token       = payload_data.get("github_token")
        env_input   = None
    else:
        form       = await request.form()
        prompt     = str(form.get("prompt") or "").strip()
        repo_url   = str(form.get("repo_url") or "").strip() or ""
        visibility = str(form.get("repository_visibility") or "public")
        token      = str(form.get("github_token") or "") or None
        env_input  = None
        env_file   = form.get("env_file")
        if getattr(env_file, "filename", None):
            env_input = await _env_service.build_input_from_upload(env_file)

    task = TaskService.create_task(db, prompt)
    TaskService.update_task_status(db, task, "in_progress")

    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.run_architecture_decision_phase(
            prompt=prompt,
            repo_url=repo_url or None,
            repository_visibility=visibility,
            github_token=token,
            uploaded_env_input=env_input,
        )

        TaskService.save_plan_awaiting_validation(db, task, state)

        logger.info(
            "[Workflow] architecture-decision complete for task %s — phase: %s",
            task.id, state.get("current_phase"),
        )
        return _phase_response(task.id, state, "Architecture strategies generated — awaiting selection")
    except Exception as exc:
        traceback.print_exc()
        TaskService.save_error(db, task, str(exc))
        raise HTTPException(status_code=500, detail=f"Architecture decision failed: {exc}")


# ── Plan selection gate ────────────────────────────────────────────────────────

@router.post("/{task_id}/select-plan", response_model=WorkflowPhaseResponse)
async def select_plan(
    task_id: str,
    body: SelectPlanRequest,
    db: Session = Depends(get_db),
):
    """
    Apply the user's plan selection from the architecture-decision phase.

    Validates that the task is in 'architecture_decision_complete' phase,
    promotes the selected strategy's plan + cost into top-level state fields,
    and sets current_phase = 'planning_complete' so the existing run-docker
    endpoint can be called next.

    This endpoint is the hard gate: run-docker MUST NOT be called before this.
    """
    state, task = _load_state(db, task_id)

    current_phase = state.get("current_phase", "")
    # Accept both the new phase and the legacy planning_complete for backward compat
    if current_phase not in ("architecture_decision_complete", "planning_complete"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Expected phase 'architecture_decision_complete', "
                f"got '{current_phase}'. Run /architecture-decision first."
            ),
        )

    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.resume_with_selected_plan(
            prior_state=state,
            selected_plan_id=body.plan_id,
        )
        TaskService.save_workflow_state(db, task, state)
        TaskService.update_task_status(db, task, "in_progress")

        logger.info(
            "[Workflow] select-plan '%s' applied for task %s — phase now: %s",
            body.plan_id, task_id, state.get("current_phase"),
        )
        return _phase_response(
            task_id,
            state,
            f"Plan '{body.plan_id}' selected — ready to generate infrastructure",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        traceback.print_exc()
        TaskService.save_error(db, task, str(exc))
        raise HTTPException(status_code=500, detail=f"Plan selection failed: {exc}")


# ── Phase 0: plan (preserved for backward compat) ─────────────────────────────

@router.post("/plan", response_model=WorkflowPhaseResponse)
async def workflow_plan(request: Request, db: Session = Depends(get_db)):
    """
    Start the workflow: run repository analysis + planning, then pause for user review.
    Returns the generated plan without running any code generation.
    """
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        payload_data = await request.json()
        prompt     = payload_data.get("prompt", "")
        repo_url   = payload_data.get("repo_url") or ""
        visibility = payload_data.get("repository_visibility") or "public"
        token      = payload_data.get("github_token")
        approved   = payload_data.get("approved_artifacts") or []
        env_input  = None
    else:
        form      = await request.form()
        prompt    = str(form.get("prompt") or "").strip()
        repo_url  = str(form.get("repo_url") or "").strip() or ""
        visibility = str(form.get("repository_visibility") or "public")
        token     = str(form.get("github_token") or "") or None
        approved  = []
        env_input = None
        env_file  = form.get("env_file")
        if getattr(env_file, "filename", None):
            env_input = await _env_service.build_input_from_upload(env_file)

    task = TaskService.create_task(db, prompt)
    TaskService.update_task_status(db, task, "in_progress")

    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.run_plan_preview(
            prompt=prompt,
            repo_url=repo_url or None,
            repository_visibility=visibility,
            github_token=token,
            uploaded_env_input=env_input,
        )
        state["approved_artifacts"] = approved
        plan = dict(state.get("plan") or {})
        plan["approved_artifacts"] = approved
        state["plan"] = plan
        state["current_phase"] = "planning_complete"

        TaskService.save_plan_awaiting_validation(db, task, state)

        return _phase_response(task.id, state, "Plan generated — awaiting approval")
    except Exception as exc:
        traceback.print_exc()
        TaskService.save_error(db, task, str(exc))
        raise HTTPException(status_code=500, detail=f"Planning failed: {exc}")


# ── Phase 1: Docker ───────────────────────────────────────────────────────────

@router.post("/{task_id}/run-docker", response_model=WorkflowPhaseResponse)
async def run_docker(task_id: str, db: Session = Depends(get_db)):
    """
    User approved the plan — run InfrastructureAgent (Docker phase only).
    Returns Dockerfile, .dockerignore, docker-compose.
    """
    state, task = _load_state(db, task_id)
    logger.info("[Workflow] Phase before docker execution: %s (task: %s)", state.get("current_phase"), task_id)
    if state.get("current_phase") not in ("planning_complete", None):
        raise HTTPException(
            status_code=409,
            detail=f"Expected phase 'planning_complete', got '{state.get('current_phase')}'",
        )

    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.run_docker_phase(state)

        # Initialize the editable artifact layer so user edits are persisted
        # separately from the immutable generated content.
        generated = dict((state.get("infra") or {}).get("artifacts") or {})
        state = ArtifactService.initialize_from_state(state, generated)

        TaskService.save_workflow_state(db, task, state)
        TaskService.update_task_status(db, task, "in_progress")

        logger.info("[Workflow] Docker phase complete for task %s, new phase: %s", task_id, state.get("current_phase"))
        return _phase_response(task_id, state, "Docker artifacts generated — awaiting approval")
    except Exception as exc:
        traceback.print_exc()
        TaskService.save_error(db, task, str(exc))
        raise HTTPException(status_code=500, detail=f"Docker phase failed: {exc}")


# ── Phase 2: Terraform ────────────────────────────────────────────────────────

@router.post("/{task_id}/run-terraform", response_model=WorkflowPhaseResponse)
async def run_terraform(task_id: str, db: Session = Depends(get_db)):
    """
    User approved Docker artifacts — run TerraformAgent.
    Returns .tf files and terraform_outputs contract for Kubernetes.
    Accepts both 'docker_completed' (skipped build) and 'docker_build_success' (build ran).
    """
    state, task = _load_state(db, task_id)
    logger.info("[Workflow] Phase before terraform execution: %s (task: %s)", state.get("current_phase"), task_id)
    _valid_terraform_phases = {"docker_completed", "docker_build_success"}
    if state.get("current_phase") not in _valid_terraform_phases:
        raise HTTPException(
            status_code=409,
            detail=f"Expected phase 'docker_completed' or 'docker_build_success', got '{state.get('current_phase')}'",
        )

    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.run_terraform_phase_only(state)
        TaskService.save_workflow_state(db, task, state)

        logger.info("[Workflow] Terraform phase complete for task %s, new phase: %s", task_id, state.get("current_phase"))
        return _phase_response(task_id, state, "Terraform files generated — awaiting approval")
    except Exception as exc:
        traceback.print_exc()
        TaskService.save_error(db, task, str(exc))
        raise HTTPException(status_code=500, detail=f"Terraform phase failed: {exc}")


# ── Phase 3: Kubernetes ───────────────────────────────────────────────────────

@router.post("/{task_id}/run-kubernetes", response_model=WorkflowPhaseResponse)
async def run_kubernetes(task_id: str, db: Session = Depends(get_db)):
    """
    User approved Terraform — run KubernetesAgent.
    Returns deployment.yaml, service.yaml (using terraform_outputs contract).
    """
    state, task = _load_state(db, task_id)
    logger.info("[Workflow] Phase before kubernetes execution: %s (task: %s)", state.get("current_phase"), task_id)
    if state.get("current_phase") != "terraform_completed":
        raise HTTPException(
            status_code=409,
            detail=f"Expected phase 'terraform_completed', got '{state.get('current_phase')}'",
        )

    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.run_kubernetes_phase_only(state)
        TaskService.save_workflow_state(db, task, state)

        logger.info("[Workflow] Kubernetes phase complete for task %s, new phase: %s", task_id, state.get("current_phase"))
        return _phase_response(task_id, state, "Kubernetes manifests generated — awaiting approval")
    except Exception as exc:
        traceback.print_exc()
        TaskService.save_error(db, task, str(exc))
        raise HTTPException(status_code=500, detail=f"Kubernetes phase failed: {exc}")


# ── Phase 4: CI/CD + Finalize ─────────────────────────────────────────────────

@router.post("/{task_id}/run-cicd", response_model=WorkflowPhaseResponse)
async def run_cicd(task_id: str, db: Session = Depends(get_db)):
    """
    User approved Kubernetes — run security scan, validation, CI/CD, and finalize.
    Returns the complete artifact set and final result.
    """
    state, task = _load_state(db, task_id)
    logger.info("[Workflow] Phase before cicd execution: %s (task: %s)", state.get("current_phase"), task_id)
    if state.get("current_phase") != "kubernetes_completed":
        raise HTTPException(
            status_code=409,
            detail=f"Expected phase 'kubernetes_completed', got '{state.get('current_phase')}'",
        )

    try:
        orchestrator = OrchestratorAgent()
        state = orchestrator.run_cicd_and_finalize_phase(state)

        # Persist the finalized result so GET /tasks/{id} can read it
        if state.get("result"):
            TaskService.save_result(db, task, state["result"])
        if state.get("plan"):
            TaskService.save_plan(db, task, state["plan"])

        TaskService.save_workflow_state(db, task, state)
        TaskService.update_task_status(db, task, state.get("status", "completed"))

        logger.info("[Workflow] CI/CD + finalize complete for task %s, new phase: %s", task_id, state.get("current_phase"))
        return _phase_response(task_id, state, "Workflow completed successfully")
    except Exception as exc:
        traceback.print_exc()
        TaskService.save_error(db, task, str(exc))
        raise HTTPException(status_code=500, detail=f"CI/CD phase failed: {exc}")


# ── GET: poll current state ───────────────────────────────────────────────────

@router.get("/{task_id}", response_model=WorkflowPhaseResponse)
def get_workflow_state(task_id: str, db: Session = Depends(get_db)):
    """
    Return current workflow phase, artifacts accumulated so far, and logs.
    Frontend polls this after each run-* call.
    """
    state, task = _load_state(db, task_id)
    return _phase_response(task_id, state)
