"""Execution services — Docker build engine and supporting layers."""

from .command_detector_service import CommandDetectorService
from .execution_trace_service import ExecutionTraceService
from .execution_models import (
    DockerBuildResult,
    ExecutionLogEntry,
    ExecutionStatus,
    LogLevel,
)
from .docker_streamer import LogStreamManager, log_stream_manager, classify_log_line
from .docker_registry import generate_image_tag, docker_login
from .docker_executor import DockerExecutor

__all__ = [
    # existing
    "CommandDetectorService",
    "ExecutionTraceService",
    # new
    "DockerBuildResult",
    "ExecutionLogEntry",
    "ExecutionStatus",
    "LogLevel",
    "LogStreamManager",
    "log_stream_manager",
    "classify_log_line",
    "generate_image_tag",
    "docker_login",
    "DockerExecutor",
]
