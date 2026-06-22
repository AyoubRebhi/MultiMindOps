"""
Pydantic models for the Docker Build Execution Engine.

Designed to be extensible: future Terraform, kubectl, Helm, and Trivy
execution phases will follow the same LogEntry / ExecutionResult pattern.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from typing import Any

from pydantic import BaseModel, Field


class LogLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    SUCCESS = "SUCCESS"
    DEFAULT = "DEFAULT"


class ExecutionLogEntry(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    level: LogLevel = LogLevel.DEFAULT
    message: str
    # Retry session metadata — populated when the log is published through a
    # TaskLogStream that carries session context. Frontend uses these fields
    # to segment terminal output per retry attempt.
    retry_iteration: int | None = None
    execution_session_id: str | None = None
    is_replay: bool = False

    def to_dict(self) -> dict:
        payload: dict[str, Any] = {
            "type": "log",
            "timestamp": self.timestamp,
            "level": self.level.value,
            "message": self.message,
            "is_replay": self.is_replay,
        }
        if self.retry_iteration is not None:
            payload["retry_iteration"] = self.retry_iteration
        if self.execution_session_id is not None:
            payload["execution_session_id"] = self.execution_session_id
        return payload


class ExecutionEvent(BaseModel):
    """Typed event used by SSE/WebSocket execution consoles."""

    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    type: str
    message: str | None = None
    level: LogLevel | str | None = None
    phase: str | None = None
    status: str | None = None
    iteration: int | None = None
    max_iterations: int | None = None
    patch: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Retry session metadata mirrored at the top level so the frontend doesn't
    # have to dig through metadata for routing.
    retry_iteration: int | None = None
    execution_session_id: str | None = None
    is_replay: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timestamp": self.timestamp,
            "type": self.type,
            "message": self.message,
            "level": self.level.value if isinstance(self.level, LogLevel) else self.level,
            "phase": self.phase,
            "status": self.status,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "patch": self.patch,
            "metadata": self.metadata,
            "retry_iteration": self.retry_iteration,
            "execution_session_id": self.execution_session_id,
            "is_replay": self.is_replay,
        }
        return {key: value for key, value in payload.items() if value is not None}


class ExecutionMachineStatus(str, Enum):
    IDLE = "idle"
    BUILDING = "building"
    ANALYZING_FAILURE = "analyzing_failure"
    GENERATING_PATCH = "generating_patch"
    APPLYING_PATCH = "applying_patch"
    RETRYING = "retrying"
    SUCCESS = "success"
    FAILED = "failed"
    MAX_RETRIES_REACHED = "max_retries_reached"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    # Phase 3A — operator stopped a running phase. Distinct from FAILED so the UI
    # can show a neutral "stopped" badge (not an error) and offer Replay.
    CANCELLED = "cancelled"


class DockerBuildResult(BaseModel):
    """Returned by the POST /api/execution/docker/build/{task_id} endpoint."""

    status: ExecutionStatus = ExecutionStatus.RUNNING
    logs: list[ExecutionLogEntry] = Field(default_factory=list)
    image_tag: str | None = None
    exit_code: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    execution_phase: str = "docker_build"
    error: str | None = None
    # Structured failure diagnostics
    failure_reason: str | None = None
    docker_command: str | None = None
    last_error_line: str | None = None
    failed_step: str | None = None

    def to_db_dict(self) -> dict:
        return {
            "status": self.status.value,
            "logs": [e.to_dict() for e in self.logs],
            "image_tag": self.image_tag,
            "exit_code": self.exit_code,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "execution_phase": self.execution_phase,
            "error": self.error,
            "failure_reason": self.failure_reason,
            "docker_command": self.docker_command,
            "last_error_line": self.last_error_line,
            "failed_step": self.failed_step,
        }
