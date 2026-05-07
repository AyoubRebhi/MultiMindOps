"""
DockerExecutor — real Docker build & push using asyncio subprocesses.

Key design decisions:
- asyncio.create_subprocess_exec (never blocking subprocess.run)
- stdout + stderr merged via STDOUT redirect so log order is preserved
- 10-minute build timeout
- Workspace is a temp dir; cleaned up in finally regardless of outcome
- Log lines streamed line-by-line to LogStreamManager (WebSocket broadcast)
- Sanitised image tags — only alphanumeric / . - _ allowed
- Path traversal prevented: Dockerfile written inside isolated tmpdir only
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

from .docker_registry import docker_login, generate_image_tag
from .docker_streamer import LogStreamManager, classify_log_line, log_stream_manager
from .execution_models import (
    DockerBuildResult,
    ExecutionLogEntry,
    ExecutionStatus,
    LogLevel,
)

logger = logging.getLogger(__name__)

BUILD_TIMEOUT_SECONDS = 600  # 10 minutes
PUSH_TIMEOUT_SECONDS = 300   # 5 minutes

# Artifacts written to the temp workspace (key → filename)
_ARTIFACT_FILENAMES: dict[str, str] = {
    "dockerfile":    "Dockerfile",
    "dockerignore":  ".dockerignore",
    "docker_compose": "docker-compose.yml",
    "env_example":   ".env.example",
}

_TAG_SAFE = re.compile(r"[^a-zA-Z0-9._\-:/]")


def _sanitise_tag(tag: str) -> str:
    return _TAG_SAFE.sub("-", tag)


class DockerExecutor:
    """
    Executes Docker build and optional registry push for a given task.

    Usage:
        executor = DockerExecutor(task_id, artifacts, image_tag, registry_config)
        result = await executor.build_image()
    """

    def __init__(
        self,
        task_id: str,
        artifacts: dict[str, str],
        image_tag: str,
        registry_url: str = "",
        registry_username: str = "",
        registry_password: str = "",
        push_on_success: bool = False,
        streamer: LogStreamManager | None = None,
    ) -> None:
        self.task_id = task_id
        self.artifacts = artifacts
        self.image_tag = _sanitise_tag(image_tag)
        self.registry_url = registry_url
        self.registry_username = registry_username
        self.registry_password = registry_password
        self.push_on_success = push_on_success
        self._streamer = streamer or log_stream_manager
        self._workspace: str | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def build_image(self) -> DockerBuildResult:
        """
        Write artifacts to a temp workspace, run `docker build`, optionally push.
        Returns a structured DockerBuildResult. Never raises — errors are captured.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        self._streamer.create(self.task_id)
        result = DockerBuildResult(
            status=ExecutionStatus.RUNNING,
            started_at=started_at,
            image_tag=self.image_tag,
        )

        try:
            self._workspace = tempfile.mkdtemp(prefix=f"docker_build_{self.task_id[:8]}_")
            await self._write_artifacts()
            exit_code = await self._run_docker_build()
            result.exit_code = exit_code

            if exit_code == 0:
                result.status = ExecutionStatus.SUCCESS
                await self._emit(LogLevel.SUCCESS, f"Build succeeded: {self.image_tag}")

                if self.push_on_success and self.registry_username:
                    push_ok = await self.push_to_registry()
                    if not push_ok:
                        await self._emit(LogLevel.ERROR, "Registry push failed (image built successfully)")
            else:
                result.status = ExecutionStatus.FAILED
                result.error = f"docker build exited with code {exit_code}"
                await self._emit(LogLevel.ERROR, result.error)

        except asyncio.TimeoutError:
            result.status = ExecutionStatus.FAILED
            result.error = f"Build timed out after {BUILD_TIMEOUT_SECONDS}s"
            await self._emit(LogLevel.ERROR, result.error)

        except Exception as exc:
            result.status = ExecutionStatus.FAILED
            result.error = str(exc)
            await self._emit(LogLevel.ERROR, f"Executor error: {exc}")
            logger.exception("DockerExecutor error for task %s", self.task_id)

        finally:
            result.finished_at = datetime.now(timezone.utc).isoformat()
            result.logs = self._streamer.get(self.task_id).logs if self._streamer.get(self.task_id) else []
            await self._streamer.finish(self.task_id)
            self._cleanup_workspace()

        return result

    async def push_to_registry(self) -> bool:
        """
        Login (if credentials provided) then run `docker push`.
        Returns True on success.
        """
        if self.registry_username and self.registry_password:
            ok, output = await docker_login(
                self.registry_url, self.registry_username, self.registry_password
            )
            if not ok:
                await self._emit(LogLevel.ERROR, f"docker login failed: {output}")
                return False
            await self._emit(LogLevel.INFO, "Registry login succeeded")

        exit_code = await self._run_cmd(
            ["docker", "push", self.image_tag],
            timeout=PUSH_TIMEOUT_SECONDS,
            phase_label="push",
        )
        return exit_code == 0

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _write_artifacts(self) -> None:
        """Write Dockerfile and companion files into the isolated workspace."""
        ws = Path(self._workspace)  # type: ignore[arg-type]

        dockerfile_written = False
        for key, content in self.artifacts.items():
            filename = _ARTIFACT_FILENAMES.get(key)
            if not filename:
                continue
            dest = ws / filename
            # Prevent path traversal: ensure dest is inside workspace
            dest = dest.resolve()
            if not str(dest).startswith(str(ws.resolve())):
                logger.warning("Skipping artifact %s — path traversal detected", key)
                continue
            dest.write_text(content, encoding="utf-8")
            if key == "dockerfile":
                dockerfile_written = True

        if not dockerfile_written:
            raise FileNotFoundError("No Dockerfile artifact found. Cannot build image.")

        await self._emit(LogLevel.INFO, f"Workspace prepared: {self._workspace}")

    async def _run_docker_build(self) -> int:
        """Run `docker build -t <tag> <workspace>` and stream every output line."""
        cmd = [
            "docker", "build",
            "--progress=plain",
            "-t", self.image_tag,
            str(self._workspace),
        ]
        await self._emit(LogLevel.INFO, f"Running: {' '.join(cmd)}")
        return await self._run_cmd(cmd, timeout=BUILD_TIMEOUT_SECONDS, phase_label="build")

    async def _run_cmd(
        self,
        cmd: list[str],
        timeout: int,
        phase_label: str,
    ) -> int:
        """
        Execute a command, stream its merged stdout+stderr line-by-line,
        and return the exit code. Raises asyncio.TimeoutError on timeout.
        """
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
            cwd=self._workspace,
        )

        async def _drain_output() -> None:
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace").rstrip()
                if line:
                    await self._streamer.publish(self.task_id, line)

        drain_task = asyncio.create_task(_drain_output())

        try:
            await asyncio.wait_for(
                asyncio.gather(proc.wait(), drain_task),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            drain_task.cancel()
            raise

        return proc.returncode or 0

    async def _emit(self, level: LogLevel, message: str) -> None:
        entry = ExecutionLogEntry(level=level, message=message)
        stream = self._streamer.get_or_create(self.task_id)
        await stream.publish(entry)

    def _cleanup_workspace(self) -> None:
        if self._workspace and os.path.exists(self._workspace):
            try:
                shutil.rmtree(self._workspace, ignore_errors=True)
            except Exception:
                pass
            self._workspace = None
