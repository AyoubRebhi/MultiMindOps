"""
Corrector Agent API routes.

GET  /api/corrector/{task_id}
    Returns the latest corrector analysis, retry counts, and current workflow phase.

POST /api/corrector/reanalyze/{task_id}
    Triggers a fresh corrector analysis using the stored Docker build logs.
    Does NOT rebuild — only re-analyzes existing logs with the corrector pipeline.

These endpoints are intentionally read-heavy: the corrector only produces
analysis objects. All state mutations flow through the execution pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.database.session import SessionLocal
from backend.app.services.core.artifact_service import ArtifactService, ArtifactStateResolver
from backend.app.services.core.task_service import TaskService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Corrector"])

_MAX_RETRIES_DEFAULT = 3


# ── DB dependency ──────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Internal helpers ───────────────────────────────────────────────────────────

def _corrector_state(workflow_state: dict) -> dict:
    return workflow_state.get("execution", {}).get("corrector", {})


def _docker_logs_text(workflow_state: dict) -> str:
    """Reconstruct raw log text from persisted log entry list."""
    logs: list[dict] = (
        workflow_state.get("execution", {})
        .get("docker", {})
        .get("logs", [])
    )
    return "\n".join(
        entry.get("message", "")
        for entry in logs
        if isinstance(entry, dict) and entry.get("message")
    )


def _docker_artifacts(workflow_state: dict) -> dict:
    """
    Extract Dockerfile artifacts from persisted workflow state.

    Priority:
      1. workflow_state["artifacts"][key]["current_content"]  ← user-edited (wins)
      2. workflow_state["infra"]["artifacts"]                 ← original generated (fallback)
    """
    return ArtifactStateResolver.get_latest_artifacts(workflow_state)


# ── GET /api/corrector/{task_id} ───────────────────────────────────────────────

@router.get("/api/corrector/{task_id}")
def get_corrector_status(
    task_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Return the latest corrector analysis, retry lifecycle, and current phase.

    Response shape:
    {
      "task_id": "...",
      "current_phase": "human_review_required",
      "corrector": {
        "status": "completed",
        "retry_count": 1,
        "max_retries": 3,
        "analysis": { ... CorrectorResult ... }
      },
      "retry_count": 1,
      "max_retries": 3,
      "analysis": { ... CorrectorResult ... }
    }
    """
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = TaskService.load_workflow_state(db, task) or {}
    corrector = _corrector_state(state)

    return {
        "task_id": task_id,
        "current_phase": state.get("current_phase", ""),
        "corrector": corrector,
        "retry_count": corrector.get("retry_count", 0),
        "max_retries": corrector.get("max_retries", _MAX_RETRIES_DEFAULT),
        "analysis": corrector.get("analysis"),
    }


# ── POST /api/corrector/reanalyze/{task_id} ────────────────────────────────────

@router.post("/api/corrector/reanalyze/{task_id}")
async def reanalyze(
    task_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Re-run corrector analysis on the stored Docker build logs.

    This does NOT trigger a Docker rebuild. It re-runs the analysis pipeline
    (sanitizer → extractor → classifier → optional LLM enrichment) on the
    log data already persisted in workflow_state.execution.docker.logs.

    Useful when:
      - The human wants a fresh AI analysis after reviewing the logs manually.
      - The LLM was unavailable during the original analysis.
    """
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = TaskService.load_workflow_state(db, task) or {}
    raw_logs = _docker_logs_text(state)

    if not raw_logs.strip():
        raise HTTPException(
            status_code=422,
            detail="No Docker build logs found for this task. Run a build first.",
        )

    artifacts = _docker_artifacts(state)

    # Mark corrector as running and update phase
    execution = state.setdefault("execution", {})
    corrector = execution.setdefault("corrector", {})
    corrector.update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })
    state["current_phase"] = "corrector_analysis_running"
    TaskService.save_workflow_state(db, task, state)

    logger.info("[Corrector] Re-analysis requested for task=%s", task_id)

    asyncio.create_task(
        _reanalyze_background(task_id, raw_logs, artifacts),
        name=f"reanalyze_{task_id[:8]}",
    )

    return {
        "task_id": task_id,
        "status": "running",
        "message": (
            "Corrector re-analysis started. "
            "Poll GET /api/corrector/{task_id} for the result."
        ),
    }


# ── Background analysis coroutine ──────────────────────────────────────────────

async def _reanalyze_background(
    task_id: str,
    raw_logs: str,
    artifacts: dict,
) -> None:
    """
    Run the full corrector pipeline in the background and persist the result.

    State transitions:
      corrector_analysis_running
        → corrector_analysis_completed  (intermediate, immediately overwritten)
        → human_review_required         (normal — retry budget remaining)
        → execution_failed              (retry_count >= max_retries)
    """
    logger.info("[Corrector] Starting analysis for task=%s", task_id)

    try:
        from backend.app.services.corrector.docker_corrector import DockerCorrectorAgent
        from backend.app.services.core.llm_service import get_llm_service

        try:
            llm = get_llm_service()
        except Exception as llm_exc:
            llm = None
            logger.warning(
                "[Corrector] LLM unavailable — using deterministic analysis only: %s",
                llm_exc,
            )

        agent = DockerCorrectorAgent(llm_service=llm)
        result = await agent.analyze(
            raw_logs=raw_logs,
            artifacts=artifacts,
            context={"task_id": task_id},
        )

        await _persist_corrector_result(task_id, result)

    except Exception as exc:
        logger.exception(
            "[Corrector] Re-analysis background task failed for task=%s: %s",
            task_id, exc,
        )
        await _persist_corrector_error(task_id, str(exc))


async def _persist_corrector_result(task_id: str, result: Any) -> None:
    """Persist a successful CorrectorResult and advance the workflow phase."""
    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if not task:
            logger.warning("[Corrector] Task not found during persist: task=%s", task_id)
            return

        state: dict = dict(TaskService.load_workflow_state(db, task) or {})
        execution = state.setdefault("execution", {})
        corrector: dict = execution.setdefault("corrector", {})

        retry_count: int = corrector.get("retry_count", 0)
        max_retries: int = corrector.get("max_retries", _MAX_RETRIES_DEFAULT)

        corrector.update({
            "status": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "analysis": result.to_dict(),
            "error": None,
        })

        if retry_count >= max_retries:
            state["current_phase"] = "execution_failed"
            logger.warning(
                "[Corrector] Max retries reached: task=%s retry_count=%d/%d → execution_failed",
                task_id, retry_count, max_retries,
            )
        else:
            state["current_phase"] = "human_review_required"
            logger.info(
                "[Corrector] Analysis persisted: task=%s retry=%d/%d → human_review_required",
                task_id, retry_count, max_retries,
            )

        TaskService.save_workflow_state(db, task, state)
        ArtifactService.store_ai_patch_suggestions(db, task, result.to_dict())
    finally:
        db.close()


async def _persist_corrector_error(task_id: str, error_message: str) -> None:
    """Persist an analysis error so the workflow is not left in a running state."""
    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if not task:
            return

        state: dict = dict(TaskService.load_workflow_state(db, task) or {})
        execution = state.setdefault("execution", {})
        corrector: dict = execution.setdefault("corrector", {})

        corrector.update({
            "status": "error",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": error_message,
        })
        # Even on error, transition to human_review so the UI isn't stuck
        state["current_phase"] = "human_review_required"

        TaskService.save_workflow_state(db, task, state)
        logger.info(
            "[Corrector] Error state persisted for task=%s → human_review_required",
            task_id,
        )
    finally:
        db.close()
