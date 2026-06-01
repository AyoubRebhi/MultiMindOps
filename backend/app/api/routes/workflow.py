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

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.agents.orchestrator_agent import OrchestratorAgent
from backend.app.core.authorization import (
    require_task_project_contributor,
    require_task_project_member,
)
from backend.app.core.security import get_current_user
from backend.app.database.session import SessionLocal
from backend.app.models.project import ProjectMember
from backend.app.models.task import Task
from backend.app.services.core.artifact_service import ArtifactService, ArtifactStateResolver
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.core.task_service import TaskService

logger = logging.getLogger(__name__)

# Phase 1 — Execution authorization unification.
#
# Per-task phase endpoints (run-docker / run-terraform / run-kubernetes /
# run-cicd / select-plan / GET state) now resolve the owning project via
# ``require_task_project_*`` so a peer DEVELOPER cannot run a phase on a
# task they don't have access to.
#
# The unscoped task-creating endpoints (``/architecture-decision``,
# ``/plan``) were removed — they used to mint a Task with no project
# linkage. New work flows through
# ``POST /api/projects/{project_id}/workflows`` which carries the role gate.
router = APIRouter(
    prefix="/workflow",
    tags=["Workflow"],
    dependencies=[Depends(get_current_user)],
)

_GONE_DETAIL = (
    "This endpoint was removed in the Phase 1 authorization unification. "
    "Use POST /api/projects/{project_id}/workflows instead — it runs the "
    "same architecture-decision phase inside a project boundary."
)


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
    # Repository build context (BuildStrategyDetector output) — exposed to the
    # frontend BuildContextPanel and used by retry-build to honour COPY paths.
    repository_build_context: dict[str, Any] | None = None
    build_artifact_context: dict[str, Any] | None = None
    # Pre-build static COPY validation result — used by the pre-build gate to
    # block builds with detectable COPY/build-context errors.
    static_validation: dict[str, Any] | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_artifacts(state: dict) -> dict[str, str]:
    """
    Pull artifacts, preferring user-edited content over generated.

    Priority (highest first):
      1. state["artifacts"][key]["current_content"]  — user-edited (wins)
      2. state["infra"]["artifacts"][key]            — original generated (fallback)
    """
    current = ArtifactStateResolver.get_latest_artifacts(state)

    # Base: all generated artifacts
    infra = state.get("infra") or {}
    result: dict[str, str] = dict(infra.get("artifacts") or {})
    result.update(current)

    return result


def _phase_response(task_id: str, state: dict, message: str = "") -> dict:
    # InfrastructureAgent.run() output is stored at state["infra"] by the
    # orchestrator. state["infrastructure"] is the artifact-service editable
    # store. We read context fields from BOTH so older tasks keep working.
    infra_agent = state.get("infra") or {}
    infra_store = state.get("infrastructure") or {}
    infra_gen = (
        infra_agent.get("infrastructure_generation")
        or state.get("infrastructure_generation")
        or infra_store.get("infrastructure_generation")
        or {}
    )
    return {
        "task_id":                  task_id,
        "current_phase":            state.get("current_phase", "unknown"),
        "status":                   state.get("status", "in_progress"),
        "artifacts":                _extract_artifacts(state),
        "terraform_outputs":        state.get("terraform_outputs") or {},
        "logs":                     state.get("logs", []),
        "message":                  message,
        "architecture_decision":    state.get("architecture_decision"),
        "topology_summary":         (
            state.get("topology_summary")
            or infra_agent.get("topology_summary")
            or infra_store.get("topology_summary")
        ),
        "repository_build_context": (
            infra_agent.get("repository_build_context")
            or infra_store.get("repository_build_context")
        ),
        "build_artifact_context": (
            infra_agent.get("build_artifact_context")
            or infra_store.get("build_artifact_context")
        ),
        "static_validation": infra_gen.get("static_validation"),
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
    # Phase 4 — re-hydrate runtime-only credentials (github_token, …) from
    # the encrypted store into the in-memory state. They are NEVER persisted:
    # the scrub in TaskService._sanitize_for_json strips them on the next
    # save_workflow_state. Without this, the per-phase agents that re-clone
    # a private repo would lose access to the token that Phase 4 removed
    # from workflow_state.
    state = CredentialsService.hydrate_state(db, state, project_id=task.project_id)
    return state, task


class SelectPlanRequest(BaseModel):
    plan_id: str  # "low_cost" | "balanced" | "high_performance"


# ── Architecture Decision phase (replaces /plan for new workflow) ─────────────

@router.post("/architecture-decision", status_code=status.HTTP_410_GONE)
async def workflow_architecture_decision_gone():
    """Removed in Phase 1 — see module docstring.

    The replacement is ``POST /api/projects/{project_id}/workflows``,
    which runs the same architecture-decision phase but requires
    project membership (DEVELOPER+).
    """
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_GONE_DETAIL)


# ── Plan selection gate ────────────────────────────────────────────────────────

@router.post("/{task_id}/select-plan", response_model=WorkflowPhaseResponse)
async def select_plan(
    task_id: str,
    body: SelectPlanRequest,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
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

@router.post("/plan", status_code=status.HTTP_410_GONE)
async def workflow_plan_gone():
    """Removed in Phase 1.

    Same migration path as ``/architecture-decision``: use
    ``POST /api/projects/{project_id}/workflows`` to start a project-scoped
    plan/architecture flow.
    """
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=_GONE_DETAIL)


# ── Phase 1: Docker ───────────────────────────────────────────────────────────

@router.post("/{task_id}/run-docker", response_model=WorkflowPhaseResponse)
async def run_docker(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
):
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

        # Mirror BuildStrategyDetector outputs + static validation into the
        # canonical infrastructure store so execution.py and the corrector
        # can resolve them from a single, persisted location.
        infra_agent_response = state.get("infra") or {}
        infra_store = state.setdefault("infrastructure", {})
        for key in (
            "repository_build_context",
            "build_artifact_context",
            "topology_summary",
            "infrastructure_generation",
        ):
            value = infra_agent_response.get(key)
            if value is not None:
                infra_store[key] = value

        # Persist known_files so the pre-build static-validation gate can
        # re-validate the (possibly user-edited) Dockerfile on retry.
        agent_ctx = (state.get("agent_context") or {}).get("infrastructure_context") or {}
        known_files = agent_ctx.get("known_files")
        if known_files:
            infra_store["known_files"] = list(known_files)

        # Persist the cloned-repo on-disk path so DockerExecutor can mirror
        # the repository tree into the temp build context. Without this,
        # COPY paths like "COPY requirements-backend.txt ." cannot resolve
        # at build time (repo_mirrored=0 catastrophe).
        repo_source_path = state.get("repo_path") or (state.get("agent_context") or {}).get("repo_path")
        if repo_source_path:
            infra_store["repo_source_path"] = repo_source_path
            logger.info("[RepoTrace] repo_source_path persisted: %s (workflow.run_docker → infrastructure store) task=%s", repo_source_path, task_id)
        else:
            logger.warning(
                "[RepoTrace] repo_source_path NOT persisted for task %s — "
                "build phase will fall back to re-cloning from repo_url.",
                task_id,
            )

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
async def run_terraform(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
):
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
        state = orchestrator.run_terraform_phase_only(state, task_id=task_id)
        TaskService.save_workflow_state(db, task, state)

        logger.info("[Workflow] Terraform phase complete for task %s, new phase: %s", task_id, state.get("current_phase"))
        return _phase_response(task_id, state, "Terraform files generated — awaiting approval")
    except Exception as exc:
        traceback.print_exc()
        TaskService.save_error(db, task, str(exc))
        raise HTTPException(status_code=500, detail=f"Terraform phase failed: {exc}")


# ── Phase 3: Kubernetes ───────────────────────────────────────────────────────

@router.post("/{task_id}/run-kubernetes", response_model=WorkflowPhaseResponse)
async def run_kubernetes(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
):
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
async def run_cicd(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
):
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
def get_workflow_state(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_member),
):
    """
    Return current workflow phase, artifacts accumulated so far, and logs.
    Frontend polls this after each run-* call.
    """
    state, task = _load_state(db, task_id)
    return _phase_response(task_id, state)
