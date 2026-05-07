"""
Execution router — Docker Build Execution Engine.

Endpoints
---------
POST /api/execution/docker/build/{task_id}
    Start an async Docker build.  Returns immediately with status="running".
    The build continues in a background asyncio task.

WS   /ws/execution/{task_id}
    Stream live log entries (JSON) until the build finishes.
    Reconnect-safe: new subscribers receive the full log history first.

GET  /api/execution/docker/status/{task_id}
    Return persisted execution state (logs survive page refresh).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.services.core.task_service import TaskService
from backend.app.services.execution.docker_executor import DockerExecutor
from backend.app.services.execution.docker_registry import generate_image_tag
from backend.app.services.execution.docker_streamer import log_stream_manager
from backend.app.services.execution.execution_models import (
    DockerBuildResult,
    ExecutionStatus,
)

logger = logging.getLogger(__name__)

# HTTP routes use /api/execution/... prefix; WebSocket uses /ws/execution/...
# Both are registered on the same router — see api/router.py for mounting.
router = APIRouter(tags=["Execution"])

# ── Acceptable upstream phases for triggering a build ─────────────────────────
_ALLOWED_BUILD_PHASES = {"docker_completed"}


# ── DB dependency ──────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_docker_artifacts(workflow_state: dict) -> dict[str, str]:
    """Pull Dockerfile + compose artifacts from the persisted workflow state."""
    infra = workflow_state.get("infra") or {}
    artifacts: dict[str, str] = dict(infra.get("artifacts") or {})

    # Also check result.infrastructure.artifacts (alternate storage path)
    result = workflow_state.get("result") or {}
    infra_result = result.get("infrastructure") or {}
    artifacts.update(infra_result.get("artifacts") or {})

    # Filter to Docker-related keys only
    docker_keys = {"dockerfile", "dockerignore", "docker_compose", "env_example"}
    return {k: v for k, v in artifacts.items() if k in docker_keys or k.startswith("docker_")}


def _save_execution_state(db: Session, task, result: DockerBuildResult) -> None:
    """Persist execution state into workflow_state.execution.docker."""
    task_obj = TaskService.get_task(db, str(task.id))
    if not task_obj:
        return
    state: dict = dict(TaskService.load_workflow_state(db, task_obj) or {})

    execution = state.setdefault("execution", {})
    execution["docker"] = result.to_db_dict()

    # Advance phase so run-terraform knows it can proceed
    if result.status == ExecutionStatus.SUCCESS:
        state["current_phase"] = "docker_build_success"
    elif result.status == ExecutionStatus.FAILED:
        state["current_phase"] = "docker_build_failed"

    TaskService.save_workflow_state(db, task_obj, state)


# ── Background build task ──────────────────────────────────────────────────────

async def _run_build_background(
    task_id: str,
    artifacts: dict[str, str],
    image_tag: str,
) -> None:
    """Coroutine that runs the full build lifecycle and persists results."""
    executor = DockerExecutor(
        task_id=task_id,
        artifacts=artifacts,
        image_tag=image_tag,
        registry_url=settings.DOCKER_REGISTRY_URL,
        registry_username=settings.DOCKER_REGISTRY_USERNAME,
        registry_password=settings.DOCKER_REGISTRY_PASSWORD,
        push_on_success=settings.DOCKER_PUSH_ON_SUCCESS,
    )

    result = await executor.build_image()

    # Persist to DB after build completes
    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if task:
            _save_execution_state(db, task, result)
    finally:
        db.close()

    logger.info(
        "[Execution] Build finished for task %s: status=%s exit_code=%s",
        task_id, result.status, result.exit_code,
    )


# ── POST /api/execution/docker/build/{task_id} ─────────────────────────────────

@router.post("/api/execution/docker/build/{task_id}")
async def start_docker_build(
    task_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Start an async Docker build for the given task.

    Validates that the workflow is in the `docker_completed` phase,
    extracts generated Docker artifacts, then launches a background build.
    Returns immediately with status=running and a WebSocket URL for log streaming.
    """
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = TaskService.load_workflow_state(db, task)
    if not state:
        raise HTTPException(status_code=422, detail="No workflow state found for this task")

    current_phase = state.get("current_phase", "")
    if current_phase not in _ALLOWED_BUILD_PHASES:
        raise HTTPException(
            status_code=409,
            detail=f"Expected phase 'docker_completed', got '{current_phase}'",
        )

    # Retrieve project name for tag generation
    plan = state.get("plan") or {}
    project_name = (
        plan.get("project_name")
        or plan.get("name")
        or str(task.prompt)[:32]
        or "app"
    )

    artifacts = _extract_docker_artifacts(state)
    if not artifacts.get("dockerfile"):
        raise HTTPException(
            status_code=422,
            detail="No Dockerfile found in task artifacts. Run the Docker phase first.",
        )

    image_tag = generate_image_tag(
        project_name=project_name,
        task_id=task_id,
        registry_url=settings.DOCKER_REGISTRY_URL,
        registry_username=settings.DOCKER_REGISTRY_USERNAME,
    )

    # Mark phase as running and persist
    state["current_phase"] = "docker_build_running"
    state.setdefault("execution", {})["docker"] = {
        "status": "running",
        "logs": [],
        "started_at": None,
        "finished_at": None,
        "image": image_tag,
        "exit_code": None,
    }
    TaskService.save_workflow_state(db, task, state)

    # Fire-and-forget background build
    asyncio.create_task(
        _run_build_background(task_id, artifacts, image_tag),
        name=f"docker_build_{task_id[:8]}",
    )

    logger.info("[Execution] Docker build started for task %s, image=%s", task_id, image_tag)

    return {
        "status": "running",
        "logs": [],
        "image_tag": image_tag,
        "execution_phase": "docker_build",
        "ws_url": f"/ws/execution/{task_id}",
        "task_id": task_id,
    }


# ── GET /api/execution/docker/status/{task_id} ─────────────────────────────────

@router.get("/api/execution/docker/status/{task_id}")
def get_docker_build_status(
    task_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return persisted Docker execution state (logs survive page refresh)."""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = TaskService.load_workflow_state(db, task) or {}
    execution = state.get("execution", {})
    docker_exec = execution.get("docker", {})

    return {
        "status": docker_exec.get("status", "pending"),
        "logs": docker_exec.get("logs", []),
        "image_tag": docker_exec.get("image"),
        "exit_code": docker_exec.get("exit_code"),
        "started_at": docker_exec.get("started_at"),
        "finished_at": docker_exec.get("finished_at"),
        "execution_phase": "docker_build",
        "current_phase": state.get("current_phase", ""),
        "task_id": task_id,
    }


# ── WebSocket /ws/execution/{task_id} ──────────────────────────────────────────

@router.websocket("/ws/execution/{task_id}")  # mounted at root (no /api prefix)
async def ws_execution_logs(websocket: WebSocket, task_id: str):
    """
    Stream live Docker build logs to the frontend.

    Protocol:
    - Server sends JSON lines:  {"timestamp": "...", "level": "INFO", "message": "..."}
    - Final message:            {"type": "done", "status": "success|failed"}
    - Reconnect-safe: replays full log history then continues live.
    """
    await websocket.accept()
    logger.info("[WS] Client connected for task %s", task_id)

    try:
        # If build is already done, serve persisted logs from DB
        db = SessionLocal()
        try:
            task = TaskService.get_task(db, task_id)
            state = TaskService.load_workflow_state(db, task) if task else {}
            execution = (state or {}).get("execution", {})
            docker_exec = execution.get("docker", {})
            persisted_logs: list[dict] = docker_exec.get("logs", [])
            final_status: str = docker_exec.get("status", "")
        finally:
            db.close()

        # Case 1: build already finished — serve persisted logs from DB
        if final_status in ("success", "failed"):
            for entry in persisted_logs:
                await websocket.send_text(json.dumps(entry))
            await websocket.send_text(json.dumps({"type": "done", "status": final_status}))
            return

        # Case 2: build is running or hasn't started yet — subscribe to live stream
        # Wait briefly for the stream to be created if the build just started
        for _ in range(20):
            stream = log_stream_manager.get(task_id)
            if stream is not None:
                break
            await asyncio.sleep(0.25)

        stream = log_stream_manager.get(task_id)
        if stream is None:
            # No stream and no persisted result — nothing to serve
            await websocket.send_text(
                json.dumps({"type": "error", "message": "No active build found for this task"})
            )
            return

        async for entry in stream.subscribe():
            payload = entry.to_dict()
            await websocket.send_text(json.dumps(payload))

        # Build finished — determine final status from DB
        db2 = SessionLocal()
        try:
            task2 = TaskService.get_task(db2, task_id)
            state2 = TaskService.load_workflow_state(db2, task2) if task2 else {}
            exec2 = (state2 or {}).get("execution", {}).get("docker", {})
            done_status = exec2.get("status", "failed")
        finally:
            db2.close()

        await websocket.send_text(json.dumps({"type": "done", "status": done_status}))

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected for task %s", task_id)
    except Exception as exc:
        logger.exception("[WS] Unexpected error for task %s: %s", task_id, exc)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
        except Exception:
            pass
