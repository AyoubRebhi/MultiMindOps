"""Execution state machine and persisted event history helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.database.session import SessionLocal
from backend.app.services.core.task_service import TaskService
from backend.app.services.execution.docker_streamer import log_stream_manager
from backend.app.services.execution.execution_models import ExecutionEvent, ExecutionMachineStatus, LogLevel

logger = logging.getLogger(__name__)


_EVENT_STATE_MAP: dict[str, ExecutionMachineStatus] = {
    "build_started": ExecutionMachineStatus.BUILDING,
    "build_log": ExecutionMachineStatus.BUILDING,
    "build_failed": ExecutionMachineStatus.ANALYZING_FAILURE,
    "corrector_analysis": ExecutionMachineStatus.ANALYZING_FAILURE,
    "generating_patch": ExecutionMachineStatus.GENERATING_PATCH,
    "patch_generated": ExecutionMachineStatus.GENERATING_PATCH,
    "patch_applied": ExecutionMachineStatus.APPLYING_PATCH,
    "retry_iteration": ExecutionMachineStatus.RETRYING,
    "build_success": ExecutionMachineStatus.SUCCESS,
    "max_retries_reached": ExecutionMachineStatus.MAX_RETRIES_REACHED,
    "execution_failed": ExecutionMachineStatus.FAILED,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_execution_event(
    event_type: str,
    *,
    message: str | None = None,
    level: LogLevel | str | None = None,
    phase: str | None = None,
    status: str | None = None,
    iteration: int | None = None,
    max_iterations: int | None = None,
    patch: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ExecutionEvent:
    state = _EVENT_STATE_MAP.get(event_type)
    return ExecutionEvent(
        type=event_type,
        message=message,
        level=level,
        phase=phase or (state.value if state else None),
        status=status,
        iteration=iteration,
        max_iterations=max_iterations,
        patch=patch,
        metadata=metadata or {},
    )


def record_execution_event(
    task_id: str,
    event: ExecutionEvent,
    *,
    db: Session | None = None,
) -> dict[str, Any]:
    """Append an event to workflow_state.execution.history and update state."""
    owns_db = db is None
    session = db or SessionLocal()
    try:
        task = TaskService.get_task(session, task_id)
        if not task:
            logger.warning("[ExecutionState] Task not found while recording event: %s", task_id)
            return event.to_dict()

        state: dict = dict(TaskService.load_workflow_state(session, task) or {})
        execution = state.setdefault("execution", {})
        history = execution.setdefault("history", [])
        event_dict = event.to_dict()
        history.append(event_dict)

        machine = execution.setdefault("state_machine", {})
        event_state = _EVENT_STATE_MAP.get(event.type)
        if event_state:
            machine["state"] = event_state.value
            execution["state"] = event_state.value
        if event.phase:
            machine["phase"] = event.phase
            execution["current_phase_label"] = event.phase
        if event.iteration is not None:
            machine["active_iteration"] = event.iteration
            execution["active_iteration"] = event.iteration
        if event.max_iterations is not None:
            machine["max_iterations"] = event.max_iterations
            execution["max_iterations"] = event.max_iterations
        if event.message:
            machine["current_message"] = event.message
            execution["current_message"] = event.message
        machine["last_event_at"] = event.timestamp
        execution["last_event_at"] = event.timestamp

        TaskService.save_workflow_state(session, task, state)
        return event_dict
    finally:
        if owns_db:
            session.close()


async def emit_execution_event(
    task_id: str,
    event_type: str,
    *,
    message: str | None = None,
    level: LogLevel | str | None = None,
    phase: str | None = None,
    status: str | None = None,
    iteration: int | None = None,
    max_iterations: int | None = None,
    patch: str | None = None,
    metadata: dict[str, Any] | None = None,
    persist: bool = True,
    db: Session | None = None,
) -> ExecutionEvent:
    """Publish an event to live subscribers and optionally persist it."""
    event = make_execution_event(
        event_type,
        message=message,
        level=level,
        phase=phase,
        status=status,
        iteration=iteration,
        max_iterations=max_iterations,
        patch=patch,
        metadata=metadata,
    )
    await log_stream_manager.publish_event(task_id, event)
    if persist:
        record_execution_event(task_id, event, db=db)
    logger.info(
        "[ExecutionEvent] task=%s type=%s phase=%s iteration=%s/%s message=%.100s",
        task_id,
        event.type,
        event.phase,
        event.iteration,
        event.max_iterations,
        event.message or "",
    )
    return event


def load_execution_history(db: Session, task_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    task = TaskService.get_task(db, task_id)
    if not task:
        return [], {}
    state = TaskService.load_workflow_state(db, task) or {}
    execution = state.get("execution") or {}
    return list(execution.get("history") or []), execution
