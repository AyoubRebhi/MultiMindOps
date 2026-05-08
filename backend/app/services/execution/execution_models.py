"""
Pydantic models for the Docker Build Execution Engine.

Designed to be extensible: future Terraform, kubectl, Helm, and Trivy
execution phases will follow the same LogEntry / ExecutionResult pattern.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

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

    def to_dict(self) -> dict:
        return {
            "type": "log",
            "timestamp": self.timestamp,
            "level": self.level.value,
            "message": self.message,
        }


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


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
