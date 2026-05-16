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
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.services.core.artifact_service import extract_current_from_state
from backend.app.services.core.task_service import TaskService
from backend.app.services.execution.docker_executor import DockerExecutor
from backend.app.services.execution.docker_registry import generate_image_tag
from backend.app.services.execution.docker_streamer import log_stream_manager
from backend.app.services.execution.execution_models import (
    DockerBuildResult,
    ExecutionLogEntry,
    ExecutionStatus,
    LogLevel,
)

logger = logging.getLogger(__name__)

# HTTP routes use /api/execution/... prefix; WebSocket uses /ws/execution/...
# Both are registered on the same router — see api/router.py for mounting.
router = APIRouter(tags=["Execution"])

# ── Acceptable upstream phases for triggering a build ─────────────────────────
_ALLOWED_BUILD_PHASES = {
    "docker_completed",
    "docker_build_failed",
    "docker_build_success",
    # Corrector phases: human reviewed analysis and approved a retry
    "human_review_required",
    "corrector_analysis_completed",
}
_BLOCKED_BUILD_PHASES = {
    "docker_build_running",
    "corrector_analysis_running",  # Analysis in progress — wait for it
    "execution_failed",            # Max retries exceeded — no more builds
    "terraform_completed",
    "kubernetes_completed",
    "completed",
}


# ── DB dependency ──────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_docker_artifacts(workflow_state: dict) -> dict[str, str]:
    """
    Pull Dockerfile + compose artifacts from the persisted workflow state.

    Priority:
      1. workflow_state["artifacts"][key]["current_content"]  ← user-edited (wins)
      2. workflow_state["infra"]["artifacts"]                 ← original generated (fallback)
    """
    docker_keys: set[str] = {"dockerfile", "dockerignore", "docker_compose", "env_example"}

    # Editable artifact layer (set by ArtifactService, updated via PATCH endpoint)
    result: dict[str, str] = extract_current_from_state(workflow_state)

    if result.get("dockerfile"):
        # Log which version we're using for audit / regression detection
        meta = workflow_state.get("artifacts") or {}
        for key in list(result):
            artifact_meta = meta.get(key) or {}
            logger.info(
                "[ArtifactService] Loaded artifact=%s version=%s modified_by=%s",
                key,
                artifact_meta.get("version", "?"),
                artifact_meta.get("last_modified_by", "?"),
            )
        return result

    # Fallback: original generated artifacts (no editable layer yet)
    infra = workflow_state.get("infra") or {}
    artifacts: dict[str, str] = dict(infra.get("artifacts") or {})
    wf_result = workflow_state.get("result") or {}
    infra_result = wf_result.get("infrastructure") or {}
    artifacts.update(infra_result.get("artifacts") or {})

    return {k: v for k, v in artifacts.items() if k in docker_keys or k.startswith("docker_")}


def _save_execution_state(db: Session, task, result: DockerBuildResult, is_retry: bool = False) -> None:
    """Persist execution state into workflow_state.execution.docker."""
    task_obj = TaskService.get_task(db, str(task.id))
    if not task_obj:
        return
    state: dict = dict(TaskService.load_workflow_state(db, task_obj) or {})

    execution = state.setdefault("execution", {})
    docker_exec = execution.setdefault("docker", {})

    previous_logs = docker_exec.get("logs", []) if is_retry else []

    new_logs = [e.to_dict() for e in result.logs]
    existing_timestamps = {log.get("timestamp") for log in previous_logs}
    merged_logs = list(previous_logs)
    for log in new_logs:
        if log.get("timestamp") not in existing_timestamps:
            merged_logs.append(log)

    result_dict = result.to_db_dict()
    result_dict["logs"] = merged_logs
    execution["docker"] = result_dict

    docker_exec = execution["docker"]
    docker_exec["retries"] = docker_exec.get("retries", 0)
    docker_exec["build_number"] = docker_exec.get("build_number", 1)

    if result.status == ExecutionStatus.SUCCESS:
        state["current_phase"] = "docker_build_success"
    elif result.status == ExecutionStatus.FAILED:
        state["current_phase"] = "docker_build_failed"

    logger.info(
        "[Execution] Persisted logs count=%d status=%s task=%s",
        len(merged_logs), result.status, task.id,
    )
    TaskService.save_workflow_state(db, task_obj, state)


# ── Background build task ──────────────────────────────────────────────────────

async def _run_build_background(
    task_id: str,
    artifacts: dict[str, str],
    image_tag: str,
    is_retry: bool = False,
    build_number: int = 1,
) -> None:
    """Coroutine that runs the full build lifecycle and persists results."""
    logger.info("[Execution] Build background task started: task=%s build_number=%d", task_id, build_number)

    if is_retry:
        separator_entry = ExecutionLogEntry(
            level=LogLevel.INFO,
            message=f"========== RETRY BUILD #{build_number} ==========",
        )
        stream = log_stream_manager.get_or_create(task_id)
        await stream.publish(separator_entry)

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

    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if task:
            _save_execution_state(db, task, result, is_retry=is_retry)
    finally:
        db.close()

    logger.info(
        "[Execution] Stream completed: task=%s status=%s exit_code=%s",
        task_id, result.status, result.exit_code,
    )

    # ── Corrector hook: trigger analysis on every build failure ───────────────
    if result.status == ExecutionStatus.FAILED:
        asyncio.create_task(
            _run_corrector_on_failure(task_id, result),
            name=f"corrector_{task_id[:8]}",
        )


# ── POST /api/execution/docker/build/{task_id} ─────────────────────────────────

@router.post("/api/execution/docker/build/{task_id}")
async def start_docker_build(
    task_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Start an async Docker build for the given task."""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = TaskService.load_workflow_state(db, task)
    if not state:
        raise HTTPException(status_code=422, detail="No workflow state found for this task")

    current_phase = state.get("current_phase", "")
    if current_phase in _BLOCKED_BUILD_PHASES:
        raise HTTPException(
            status_code=409,
            detail=f"Build already in progress or workflow completed. Current phase: '{current_phase}'",
        )
    if current_phase not in _ALLOWED_BUILD_PHASES:
        raise HTTPException(
            status_code=409,
            detail=f"Expected phase one of {_ALLOWED_BUILD_PHASES}, got '{current_phase}'",
        )

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

    # Audit: log which artifact versions will be used for this build
    artifact_meta = state.get("artifacts") or {}
    for key in artifacts:
        meta = artifact_meta.get(key) or {}
        logger.info(
            "[Execution] Using artifact=%s version=%s modified_by=%s checksum=%s task=%s",
            key,
            meta.get("version", "legacy"),
            meta.get("last_modified_by", "generated"),
            meta.get("checksum", "n/a"),
            task_id,
        )

    image_tag = generate_image_tag(
        project_name=project_name,
        task_id=task_id,
        registry_url=settings.DOCKER_REGISTRY_URL,
        registry_username=settings.DOCKER_REGISTRY_USERNAME,
    )

    execution = state.setdefault("execution", {})
    docker_exec = execution.setdefault("docker", {})

    is_retry = current_phase in ("docker_build_failed", "human_review_required", "corrector_analysis_completed")
    build_number = docker_exec.get("build_number", 0) + 1
    previous_logs = docker_exec.get("logs", []) if is_retry else []

    state["current_phase"] = "docker_build_running"
    docker_exec.update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "image": image_tag,
        "exit_code": None,
        "build_number": build_number,
        "retries": docker_exec.get("retries", 0) + (1 if is_retry else 0),
        "logs": previous_logs,
    })
    TaskService.save_workflow_state(db, task, state)

    asyncio.create_task(
        _run_build_background(task_id, artifacts, image_tag, is_retry=is_retry, build_number=build_number),
        name=f"docker_build_{task_id[:8]}",
    )

    logger.info("[Execution] Docker build started: task=%s image=%s build_number=%d", task_id, image_tag, build_number)

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

    started_at = docker_exec.get("started_at")
    finished_at = docker_exec.get("finished_at")
    duration_seconds = None
    if started_at and finished_at:
        try:
            start_dt = datetime.fromisoformat(started_at)
            end_dt = datetime.fromisoformat(finished_at)
            duration_seconds = int((end_dt - start_dt).total_seconds())
        except (ValueError, TypeError):
            pass
    elif started_at and docker_exec.get("status") == "running":
        try:
            start_dt = datetime.fromisoformat(started_at)
            duration_seconds = int((datetime.now(timezone.utc) - start_dt).total_seconds())
        except (ValueError, TypeError):
            pass

    logs = docker_exec.get("logs", [])
    logger.info(
        "[Execution] Replay persisted logs: task=%s count=%d status=%s",
        task_id, len(logs), docker_exec.get("status", "pending"),
    )

    return {
        "status": docker_exec.get("status", "pending"),
        "logs": logs,
        "image_tag": docker_exec.get("image"),
        "exit_code": docker_exec.get("exit_code"),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "retries": docker_exec.get("retries", 0),
        "build_number": docker_exec.get("build_number", 0),
        "execution_phase": "docker_build",
        "current_phase": state.get("current_phase", ""),
        "task_id": task_id,
        "failure_reason": docker_exec.get("failure_reason"),
        "docker_command": docker_exec.get("docker_command"),
        "last_error_line": docker_exec.get("last_error_line"),
        "failed_step": docker_exec.get("failed_step"),
    }


# ── WebSocket /ws/execution/{task_id} ──────────────────────────────────────────

@router.websocket("/ws/execution/{task_id}")
async def ws_execution_logs(websocket: WebSocket, task_id: str):
    """
    Stream live Docker build logs to the frontend.

    Payload format (standardized):
      log entry:  {"type": "log", "timestamp": "...", "level": "INFO", "message": "..."}
      complete:   {"type": "complete", "status": "success|failed", "exit_code": 0}
      error:      {"type": "error", "message": "...", "exit_code": 1}
      heartbeat:  {"type": "pong"}

    Protocol:
      - Reconnect-safe: replays full log history from DB, then streams live.
      - Separate asyncio task handles ping/close messages concurrently so the
        main stream loop is NEVER blocked waiting for client input.
    """
    await websocket.accept()
    logger.info("[WS] Client connected: task_id=%s", task_id)

    # Shared cancellation flag — set by ping-receiver task on disconnect/close
    closed = asyncio.Event()

    async def _ping_receiver() -> None:
        """Background task: handle ping/close from client without blocking log streaming."""
        while not closed.is_set():
            try:
                raw = await websocket.receive_text()
                data = json.loads(raw)
                if data.get("type") == "ping":
                    try:
                        await websocket.send_text(json.dumps({"type": "pong"}))
                    except Exception:
                        closed.set()
                        break
                elif data.get("type") == "close":
                    closed.set()
                    break
            except WebSocketDisconnect:
                closed.set()
                break
            except Exception:
                closed.set()
                break

    async def _send(payload: dict) -> bool:
        """Send a JSON payload; returns False if the connection is gone."""
        if closed.is_set():
            return False
        try:
            await websocket.send_text(json.dumps(payload))
            return True
        except Exception:
            closed.set()
            return False

    try:
        # ── Load persisted state ──────────────────────────────────────────────
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

        logger.info(
            "[WS] Task %s: final_status=%s buffered_logs=%d",
            task_id, final_status or "none", len(persisted_logs),
        )

        # Start ping-receiver concurrently (never blocks the log stream)
        ping_task = asyncio.create_task(_ping_receiver())

        # ── Case 1: Build already finished — replay persisted logs from DB ────
        if final_status in ("success", "failed"):
            logger.info("[WS] Replaying %d persisted logs (build finished)", len(persisted_logs))
            for i, entry in enumerate(persisted_logs):
                if closed.is_set():
                    break
                logger.debug("[WS] Sending persisted log %d/%d", i + 1, len(persisted_logs))
                await _send({**entry, "type": "log"})

            if not closed.is_set():
                logger.info("[WS] Sending complete event: status=%s", final_status)
                await _send({
                    "type": "complete",
                    "status": final_status,
                    "exit_code": docker_exec.get("exit_code"),
                })

            # Keep alive briefly for the client to receive done message
            try:
                await asyncio.wait_for(ping_task, timeout=30.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                ping_task.cancel()
            return

        # ── Case 2: Build running or not yet started ──────────────────────────
        # Send any persisted logs first (previous retry segments)
        if persisted_logs:
            logger.info("[WS] Sending %d persisted logs before live stream", len(persisted_logs))
            for entry in persisted_logs:
                if closed.is_set():
                    break
                await _send({**entry, "type": "log"})

        # Wait up to 5 seconds for the stream to be created by the executor
        stream = None
        for attempt in range(20):
            if closed.is_set():
                break
            stream = log_stream_manager.get(task_id)
            if stream is not None:
                logger.info("[WS] Stream found after %d polls for task %s", attempt, task_id)
                break
            await asyncio.sleep(0.25)

        if stream is None or closed.is_set():
            logger.info("[WS] No active stream for task %s, serving info", task_id)
            await _send({"type": "info", "message": "Build not currently running. Reconnect when build starts."})
            ping_task.cancel()
            return

        # ── Stream live logs (no blocking wait between entries) ───────────────
        logger.info("[WS] Starting live log stream: task=%s", task_id)
        log_count = 0
        async for entry in stream.subscribe():
            if closed.is_set():
                break
            entry_dict = entry.to_dict()  # already has type="log" from model
            logger.debug(
                "[WS] Sending live log #%d: level=%s msg=%.60s",
                log_count, entry_dict.get("level"), entry_dict.get("message", ""),
            )
            if not await _send(entry_dict):
                break
            log_count += 1

        logger.info("[WS] Stream finished: task=%s total_lines=%d", task_id, log_count)
        ping_task.cancel()

        if closed.is_set():
            return

        # ── Determine final status from DB and send complete event ────────────
        db2 = SessionLocal()
        try:
            task2 = TaskService.get_task(db2, task_id)
            state2 = TaskService.load_workflow_state(db2, task2) if task2 else {}
            exec2 = (state2 or {}).get("execution", {}).get("docker", {})
            done_status = exec2.get("status", "failed")
            exit_code = exec2.get("exit_code")
        finally:
            db2.close()

        logger.info("[WS] Build complete: task=%s status=%s exit_code=%s", task_id, done_status, exit_code)
        await _send({
            "type": "complete",
            "status": done_status,
            "exit_code": exit_code,
        })

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected: task_id=%s", task_id)
    except Exception as exc:
        logger.exception("[WS] Unexpected error: task_id=%s error=%s", task_id, exc)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(exc), "exit_code": 1}))
        except Exception:
            pass


# ── Corrector orchestration hook ───────────────────────────────────────────────

async def _run_corrector_on_failure(
    task_id: str,
    build_result: DockerBuildResult,
) -> None:
    """
    Trigger corrector analysis after a Docker build failure.

    State transitions driven by this function:
      docker_build_failed
        → corrector_analysis_running   (immediately)
        → human_review_required        (retry budget remaining)
        → execution_failed             (retry_count >= max_retries)

    Retry lifecycle:
      retry_count is incremented each time a build fails and corrector runs.
      When retry_count reaches max_retries, the workflow moves to execution_failed
      so no further automatic or manual retries are allowed without operator intervention.
    """
    logger.info("[Corrector] Starting analysis for task=%s", task_id)

    # ── Step 1: Read current state, increment retry_count, set phase ──────────
    db = SessionLocal()
    retry_count: int = 0
    max_retries: int = 3
    artifacts: dict = {}

    try:
        task = TaskService.get_task(db, task_id)
        if not task:
            logger.warning("[Corrector] Task not found: task=%s", task_id)
            return

        state: dict = dict(TaskService.load_workflow_state(db, task) or {})
        execution = state.setdefault("execution", {})
        corrector: dict = execution.setdefault("corrector", {})

        retry_count = corrector.get("retry_count", 0) + 1
        max_retries = corrector.get("max_retries", 3)

        corrector.update({
            "status": "running",
            "retry_count": retry_count,
            "max_retries": max_retries,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
        })
        state["current_phase"] = "corrector_analysis_running"
        TaskService.save_workflow_state(db, task, state)
        artifacts = _extract_docker_artifacts(state)
    finally:
        db.close()

    logger.info(
        "[Corrector] Retry count=%d/%d for task=%s",
        retry_count, max_retries, task_id,
    )

    # ── Step 2: Reconstruct log text from DockerBuildResult ───────────────────
    raw_logs = "\n".join(entry.message for entry in build_result.logs)

    # ── Step 3: Run corrector analysis ────────────────────────────────────────
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
        analysis = await agent.analyze(
            raw_logs=raw_logs,
            artifacts=artifacts,
            context={
                "task_id": task_id,
                "exit_code": build_result.exit_code,
                "failed_step": build_result.failed_step,
                "build_number": retry_count,
            },
        )

    except Exception as exc:
        logger.exception(
            "[Corrector] Analysis failed for task=%s: %s", task_id, exc
        )
        analysis = None

    # ── Step 4: Persist result and advance workflow phase ─────────────────────
    db2 = SessionLocal()
    try:
        task2 = TaskService.get_task(db2, task_id)
        if not task2:
            return

        state2: dict = dict(TaskService.load_workflow_state(db2, task2) or {})
        execution2 = state2.setdefault("execution", {})
        corrector2: dict = execution2.get("corrector", {})

        if analysis is not None:
            corrector2.update({
                "status": "completed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "analysis": analysis.to_dict(),
                "error": None,
            })
        else:
            corrector2.update({
                "status": "error",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": "Corrector analysis failed unexpectedly.",
            })

        execution2["corrector"] = corrector2

        if retry_count >= max_retries:
            state2["current_phase"] = "execution_failed"
            logger.warning(
                "[Corrector] Max retries exceeded: task=%s %d/%d → execution_failed",
                task_id, retry_count, max_retries,
            )
        else:
            state2["current_phase"] = "human_review_required"
            logger.info(
                "[Corrector] Analysis complete: task=%s retry=%d/%d → human_review_required",
                task_id, retry_count, max_retries,
            )

        TaskService.save_workflow_state(db2, task2, state2)
    finally:
        db2.close()
