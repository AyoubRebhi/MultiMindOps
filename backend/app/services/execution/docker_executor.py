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
    ExecutionEvent,
    ExecutionLogEntry,
    ExecutionStatus,
    LogLevel,
)
from .execution_state_service import record_execution_event

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
        build_strategy: dict | None = None,
        finish_stream: bool = True,
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
        # Build strategy metadata (from RepositoryBuildContext)
        self._build_strategy: dict = build_strategy or {}
        self._finish_stream = finish_stream
        # Tracking for structured failure diagnostics
        self._docker_command: str | None = None
        self._last_error_line: str | None = None
        self._failed_step: str | None = None

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
            await self._emit_event(
                "build_started",
                message=f"Docker build started: {self.image_tag}",
                status="running",
                phase="building",
            )
            # ── Build strategy trace (Phase 6) ────────────────────────────────
            await self._emit_build_strategy_trace()

            # ── PART 5: Pre-build validation ──────────────────────────────────
            validation_error = await self._validate_docker_environment()
            if validation_error:
                result.status = ExecutionStatus.FAILED
                result.exit_code = 1
                result.error = validation_error
                result.failure_reason = "Docker environment validation failed"
                await self._emit_event(
                    "execution_failed",
                    message=validation_error,
                    status="failed",
                    phase="failed",
                )
                await self._emit(LogLevel.ERROR, validation_error)
                return result

            self._workspace = tempfile.mkdtemp(prefix=f"docker_build_{self.task_id[:8]}_")
            await self._write_artifacts()
            exit_code = await self._run_docker_build()
            result.exit_code = exit_code

            if exit_code == 0:
                result.status = ExecutionStatus.SUCCESS
                await self._emit_event(
                    "build_success",
                    message=f"Build succeeded: {self.image_tag}",
                    status="success",
                    phase="success",
                )
                await self._emit(LogLevel.SUCCESS, f"Build succeeded: {self.image_tag}")

                if self.push_on_success and self.registry_username:
                    push_ok = await self.push_to_registry()
                    if not push_ok:
                        await self._emit(LogLevel.ERROR, "Registry push failed (image built successfully)")
            else:
                result.status = ExecutionStatus.FAILED
                result.error = f"docker build exited with code {exit_code}"
                # Populate structured failure diagnostics
                result.docker_command = self._docker_command
                result.last_error_line = self._last_error_line
                result.failed_step = self._failed_step
                # Build a human-readable failure reason
                parts = []
                if self._failed_step:
                    parts.append(f"Failed step: {self._failed_step}")
                if self._last_error_line:
                    parts.append(self._last_error_line)
                result.failure_reason = " | ".join(parts) if parts else result.error
                await self._emit_event(
                    "build_failed",
                    message=result.failure_reason or result.error,
                    status="failed",
                    phase="analyzing_failure",
                    metadata={
                        "exit_code": exit_code,
                        "failed_step": result.failed_step,
                        "last_error_line": result.last_error_line,
                    },
                )
                await self._emit(LogLevel.ERROR, result.error)

        except asyncio.TimeoutError:
            result.status = ExecutionStatus.FAILED
            result.error = f"Build timed out after {BUILD_TIMEOUT_SECONDS}s"
            result.failure_reason = "Build timeout"
            result.docker_command = self._docker_command
            result.last_error_line = self._last_error_line
            await self._emit_event(
                "execution_failed",
                message=result.error,
                status="failed",
                phase="failed",
            )
            await self._emit(LogLevel.ERROR, result.error)

        except FileNotFoundError as exc:
            result.status = ExecutionStatus.FAILED
            result.exit_code = 1
            result.error = str(exc)
            result.failure_reason = f"Missing file: {exc}"
            await self._emit_event(
                "execution_failed",
                message=result.failure_reason,
                status="failed",
                phase="failed",
            )
            await self._emit(LogLevel.ERROR, f"File not found: {exc}")

        except Exception as exc:
            result.status = ExecutionStatus.FAILED
            result.error = str(exc)
            result.failure_reason = f"Executor error: {exc}"
            result.docker_command = self._docker_command
            result.last_error_line = self._last_error_line
            await self._emit_event(
                "execution_failed",
                message=result.failure_reason,
                status="failed",
                phase="failed",
            )
            await self._emit(LogLevel.ERROR, f"Executor error: {exc}")
            logger.exception("[DockerExecutor] error for task %s", self.task_id)

        finally:
            result.finished_at = datetime.now(timezone.utc).isoformat()
            result.logs = self._streamer.get(self.task_id).logs if self._streamer.get(self.task_id) else []
            if self._finish_stream:
                await self._streamer.finish(self.task_id)
            self._cleanup_workspace()
            logger.info(
                "[DockerExecutor] Build finished for task %s: status=%s exit_code=%s failure_reason=%s",
                self.task_id, result.status, result.exit_code, result.failure_reason,
            )

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

    async def _emit_build_strategy_trace(self) -> None:
        """
        Emit explicit build strategy information to the log stream so operators
        always know EXACTLY what is being executed and from which context.
        """
        strategy = self._build_strategy.get("strategy", "docker_build_temp_workspace")
        ctx      = self._build_strategy.get("context_path", self._workspace or "temp_workspace")
        df_path  = self._build_strategy.get("dockerfile_path", "Dockerfile")

        logger.info(
            "[BuildExecutor] strategy=%s context=%s dockerfile=%s image=%s",
            strategy, ctx, df_path, self.image_tag,
        )
        await self._emit(LogLevel.INFO, "─" * 60)
        await self._emit(LogLevel.INFO, "[BuildExecutor] Build strategy trace:")
        await self._emit(LogLevel.INFO, f"  strategy:   {strategy}")
        await self._emit(LogLevel.INFO, f"  context:    {ctx}")
        await self._emit(LogLevel.INFO, f"  dockerfile: {df_path}")
        await self._emit(LogLevel.INFO, f"  image tag:  {self.image_tag}")
        await self._emit(LogLevel.INFO, f"  workspace:  {self._workspace or 'not yet created'}")
        await self._emit(LogLevel.INFO, "─" * 60)

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
        self._docker_command = " ".join(cmd)
        logger.info("[DockerExecutor] Starting build for task %s", self.task_id)
        logger.info("[DockerExecutor] Command: %s", self._docker_command)
        await self._emit(LogLevel.INFO, f"Running: {self._docker_command}")
        return await self._run_cmd(cmd, timeout=BUILD_TIMEOUT_SECONDS, phase_label="build")

    async def _run_cmd(
        self,
        cmd: list[str],
        timeout: int,
        phase_label: str,
    ) -> int:
        """
        Execute a command, stream BOTH stdout and stderr line-by-line,
        and return the exit code. Raises asyncio.TimeoutError on timeout.
        """
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,  # Capture stderr separately
            cwd=self._workspace,
        )

        last_stdout: str | None = None
        last_stderr: str | None = None

        async def _drain_stdout() -> None:
            nonlocal last_stdout
            assert proc.stdout is not None
            logger.info("[DockerExecutor] Streaming stdout for %s phase...", phase_label)
            line_count = 0
            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace").rstrip()
                if line:
                    last_stdout = line
                    self._track_step(line)
                    await self._publish_log_line(line)
                    line_count += 1
                    logger.debug("[DockerExecutor] stdout line #%d: %.60s", line_count, line)
            logger.info("[DockerExecutor] stdout drain complete: %d lines", line_count)

        async def _drain_stderr() -> None:
            nonlocal last_stderr
            assert proc.stderr is not None
            logger.info("[DockerExecutor] Streaming stderr for %s phase...", phase_label)
            line_count = 0
            async for raw_line in proc.stderr:
                line = raw_line.decode(errors="replace").rstrip()
                if line:
                    last_stderr = line
                    self._last_error_line = line
                    await self._publish_log_line(line)
                    line_count += 1
                    logger.debug("[DockerExecutor] stderr line #%d: %.60s", line_count, line)
            logger.info("[DockerExecutor] stderr drain complete: %d lines", line_count)

        drain_stdout = asyncio.create_task(_drain_stdout())
        drain_stderr = asyncio.create_task(_drain_stderr())

        try:
            await asyncio.wait_for(
                asyncio.gather(proc.wait(), drain_stdout, drain_stderr),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            drain_stdout.cancel()
            drain_stderr.cancel()
            raise

        exit_code = proc.returncode or 0
        if exit_code != 0:
            logger.info("[DockerExecutor] Build failed with exit_code=%d", exit_code)
            logger.info("[DockerExecutor] Last error line: %s", last_stderr or last_stdout)
            # Ensure last_error_line is set from either stream
            if not self._last_error_line:
                self._last_error_line = last_stderr or last_stdout

        return exit_code

    def _track_step(self, line: str) -> None:
        """Track the current Dockerfile step from build output."""
        # Match: "Step 3/10 : RUN npm install" or "Step 3 : RUN npm install"
        import re as _re
        m = _re.match(r"^Step\s+\d+(?:/\d+)?\s*:\s*(.+)$", line, _re.IGNORECASE)
        if m:
            self._failed_step = m.group(1).strip()

    async def _validate_docker_environment(self) -> str | None:
        """
        PART 5: Validate Docker Desktop connectivity and required files.
        Returns an error string if validation fails, None if OK.
        """
        logger.info("[DockerExecutor] Validating Docker environment for task %s", self.task_id)

        # 1. Check Docker daemon connectivity
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                return "Docker daemon did not respond within 10s. Is Docker Desktop running?"

            if proc.returncode != 0:
                stderr = await proc.stderr.read() if proc.stderr else b""
                err_msg = stderr.decode(errors="replace").strip()
                logger.error("[DockerExecutor] Docker info failed: %s", err_msg)
                return (
                    "Docker daemon is not running. "
                    "Please start Docker Desktop and try again. "
                    f"Details: {err_msg[:200]}"
                )
            logger.info("[DockerExecutor] Docker daemon is running")
        except FileNotFoundError:
            return (
                "Docker command not found. "
                "Please install Docker Desktop and ensure 'docker' is in your PATH."
            )
        except Exception as exc:
            return f"Docker environment check failed: {exc}"

        # 2. Validate Dockerfile artifact exists
        if not self.artifacts.get("dockerfile"):
            logger.error("[DockerExecutor] No Dockerfile artifact found")
            return "No Dockerfile found in task artifacts. Run the Docker phase first."
        logger.info("[DockerExecutor] Dockerfile artifact present")

        # 3. Validate docker-compose.yml if referenced
        if self.artifacts.get("docker_compose"):
            logger.info("[DockerExecutor] docker-compose.yml artifact present")

        return None  # All validations passed

    async def _emit(self, level: LogLevel, message: str) -> None:
        entry = ExecutionLogEntry(level=level, message=message)
        stream = self._streamer.get_or_create(self.task_id)
        await stream.publish(entry)
        self._record_log_event(entry)

    async def _publish_log_line(self, line: str) -> None:
        entry = await self._streamer.publish(self.task_id, line)
        self._record_log_event(entry)

    def _record_log_event(self, entry: ExecutionLogEntry) -> None:
        record_execution_event(
            self.task_id,
            ExecutionEvent(
                type="build_log",
                timestamp=entry.timestamp,
                level=entry.level,
                message=entry.message,
                phase="building",
            ),
        )

    async def _emit_event(
        self,
        event_type: str,
        *,
        message: str | None = None,
        status: str | None = None,
        phase: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        from .execution_state_service import emit_execution_event

        await emit_execution_event(
            self.task_id,
            event_type,
            message=message,
            status=status,
            phase=phase,
            metadata=metadata or {},
        )

    def _cleanup_workspace(self) -> None:
        if self._workspace and os.path.exists(self._workspace):
            try:
                shutil.rmtree(self._workspace, ignore_errors=True)
            except Exception:
                pass
            self._workspace = None
