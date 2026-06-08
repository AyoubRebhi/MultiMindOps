"""
Tests for the Docker Build Execution Engine.

Covers:
- DockerExecutor.build_image() success path (mocked subprocess)
- Build failure (non-zero exit code)
- Timeout handling
- Log classification in docker_streamer
- Image tag generation in docker_registry
- Registry push (mocked)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.execution.docker_executor import DockerExecutor
from backend.app.services.execution.docker_registry import generate_image_tag
from backend.app.services.execution.docker_streamer import (
    LogStreamManager,
    classify_log_line,
)
from backend.app.services.execution.execution_models import (
    ExecutionStatus,
    LogLevel,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

VALID_DOCKERFILE = "FROM python:3.12-slim\nCMD ['python', '-c', 'print(1)']"

MINIMAL_ARTIFACTS = {
    "dockerfile": VALID_DOCKERFILE,
    "docker_compose": "version: '3.8'\nservices:\n  app:\n    build: .\n",
}


def _make_mock_process(returncode: int, stdout_lines: list[str]):
    """Create a fake asyncio Process that yields the given stdout lines."""

    async def _readline_gen():
        for line in stdout_lines:
            yield (line + "\n").encode()

    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = _readline_gen()
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    return proc


# ── Log classification ─────────────────────────────────────────────────────────

def test_classify_error_line():
    assert classify_log_line("ERROR: something broke") == LogLevel.ERROR


def test_classify_failed_line():
    assert classify_log_line("Build failed at step 3") == LogLevel.ERROR


def test_classify_success_line():
    assert classify_log_line("Successfully built abc123def456") == LogLevel.SUCCESS


def test_classify_info_step_line():
    assert classify_log_line("Step 1/5 : FROM python:3.12-slim") == LogLevel.INFO


def test_classify_default_line():
    assert classify_log_line("---> Running in some_container_id") == LogLevel.DEFAULT


# ── Image tag generation ───────────────────────────────────────────────────────

def test_generate_tag_no_registry():
    tag = generate_image_tag("my-app", "abc123def456")
    assert tag.startswith("my-app:")
    assert "abc123de" in tag


def test_generate_tag_dockerhub():
    tag = generate_image_tag("my-app", "abc123", registry_username="myuser")
    assert tag.startswith("myuser/my-app:")


def test_generate_tag_ghcr():
    tag = generate_image_tag(
        "my-app", "abc123",
        registry_url="ghcr.io",
        registry_username="myuser",
    )
    assert tag.startswith("ghcr.io/myuser/my-app:")


def test_generate_tag_special_chars():
    tag = generate_image_tag("My App!!!", "abc123")
    # Should not contain spaces or exclamation marks
    assert " " not in tag
    assert "!" not in tag


# ── LogStreamManager ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_manager_subscribe_receives_all_logs():
    manager = LogStreamManager()
    manager.create("task-1")

    await manager.publish("task-1", "line one")
    await manager.publish("task-1", "line two")
    await manager.finish("task-1")

    collected = []
    async for entry in manager.get("task-1").subscribe():
        collected.append(entry.message)

    assert collected == ["line one", "line two"]


@pytest.mark.asyncio
async def test_stream_manager_late_subscriber_gets_history():
    """A subscriber that connects after some logs are published still gets them all."""
    manager = LogStreamManager()
    manager.create("task-2")

    await manager.publish("task-2", "early line")
    await manager.finish("task-2")

    collected = []
    async for entry in manager.get("task-2").subscribe():
        collected.append(entry.message)

    assert "early line" in collected


# ── DockerExecutor — success path ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_image_success():
    fake_output = [
        "Step 1/3 : FROM python:3.12-slim",
        "Step 2/3 : COPY . /app",
        "Step 3/3 : CMD python app.py",
        "Successfully built abc123456789",
        "Successfully tagged myapp:test-123",
    ]

    mock_proc = _make_mock_process(0, fake_output)

    with (
        patch("backend.app.services.execution.docker_executor.asyncio.create_subprocess_exec",
              new=AsyncMock(return_value=mock_proc)),
        patch("backend.app.services.execution.docker_executor.ensure_docker_daemon",
              new=AsyncMock(return_value=(True, None))),
        patch("backend.app.services.execution.docker_executor.tempfile.mkdtemp",
              return_value="/tmp/fake_workspace"),
        patch("pathlib.Path.write_text"),
        patch("os.path.exists", return_value=False),
        patch("shutil.rmtree"),
    ):
        executor = DockerExecutor(
            task_id="task-success",
            artifacts=MINIMAL_ARTIFACTS,
            image_tag="myapp:test-123",
        )
        # Prevent actual filesystem operations
        executor._workspace = "/tmp/fake_workspace"

        result = await executor.build_image()

    assert result.status == ExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert any("Successfully built" in e.message for e in result.logs)


# ── DockerExecutor — failure path ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_image_invalid_dockerfile():
    """Non-zero exit code → status=failed."""
    fake_output = [
        "Step 1/2 : FROM nonexistent-base-image:999",
        "ERROR: Unable to find image 'nonexistent-base-image:999' locally",
    ]

    mock_proc = _make_mock_process(1, fake_output)

    with (
        patch("backend.app.services.execution.docker_executor.asyncio.create_subprocess_exec",
              new=AsyncMock(return_value=mock_proc)),
        patch("backend.app.services.execution.docker_executor.ensure_docker_daemon",
              new=AsyncMock(return_value=(True, None))),
        patch("backend.app.services.execution.docker_executor.tempfile.mkdtemp",
              return_value="/tmp/fake_fail"),
        patch("pathlib.Path.write_text"),
        patch("os.path.exists", return_value=False),
        patch("shutil.rmtree"),
    ):
        executor = DockerExecutor(
            task_id="task-fail",
            artifacts=MINIMAL_ARTIFACTS,
            image_tag="badimage:test",
        )
        executor._workspace = "/tmp/fake_fail"
        result = await executor.build_image()

    assert result.status == ExecutionStatus.FAILED
    assert result.exit_code == 1
    assert any("exit_code" in e.message or "ERROR" in e.message for e in result.logs)


# ── DockerExecutor — timeout ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_image_timeout():
    """asyncio.TimeoutError during build → status=failed with timeout message."""

    async def _slow_subprocess(*args, **kwargs):
        proc = MagicMock()

        async def _never_ending():
            while True:
                await asyncio.sleep(1)
            yield b""  # unreachable

        proc.stdout = _never_ending()
        proc.wait = AsyncMock(side_effect=asyncio.sleep(9999))
        proc.kill = MagicMock()
        return proc

    with (
        patch("backend.app.services.execution.docker_executor.asyncio.create_subprocess_exec",
              new=_slow_subprocess),
        patch("backend.app.services.execution.docker_executor.ensure_docker_daemon",
              new=AsyncMock(return_value=(True, None))),
        patch("backend.app.services.execution.docker_executor.BUILD_TIMEOUT_SECONDS", 0),
        patch("backend.app.services.execution.docker_executor.tempfile.mkdtemp",
              return_value="/tmp/fake_timeout"),
        patch("pathlib.Path.write_text"),
        patch("os.path.exists", return_value=False),
        patch("shutil.rmtree"),
    ):
        executor = DockerExecutor(
            task_id="task-timeout",
            artifacts=MINIMAL_ARTIFACTS,
            image_tag="timeout:test",
        )
        executor._workspace = "/tmp/fake_timeout"
        result = await executor.build_image()

    assert result.status == ExecutionStatus.FAILED
    assert result.error is not None
    assert "timed out" in result.error.lower() or "timeout" in result.error.lower()


# ── DockerExecutor — registry push ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_push_to_registry_success():
    mock_proc = _make_mock_process(0, ["The push refers to repository [docker.io/user/app]", "digest: sha256:abc"])

    with patch(
        "backend.app.services.execution.docker_executor.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=mock_proc),
    ):
        executor = DockerExecutor(
            task_id="task-push",
            artifacts=MINIMAL_ARTIFACTS,
            image_tag="myuser/myapp:test-push",
            registry_username="myuser",
            registry_password="mypassword",
        )
        executor._workspace = "/tmp/fake_push"

        with patch.object(executor, "_run_cmd", new=AsyncMock(return_value=0)):
            ok = await executor.push_to_registry()

    assert ok is True
