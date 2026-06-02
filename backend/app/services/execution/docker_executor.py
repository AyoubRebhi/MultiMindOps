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

BUILD_TIMEOUT_SECONDS = 2400  # 40 minutes
PUSH_TIMEOUT_SECONDS = 2400   # 40 minutes

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
        repo_source_path: str | None = None,
        retry_iteration: int = 1,
        execution_session_id: str | None = None,
        repo_url: str | None = None,
        repository_visibility: str = "public",
        github_token: str | None = None,
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
        # Self-heal the persisted build strategy against the actual Dockerfile.
        # When the persisted strategy says e.g. "backend/app" but the Dockerfile
        # COPY sources are repo-root-relative (no slash), override to repo root.
        # This protects builds whose strategy was persisted by an earlier code
        # path that didn't include the autocorrect step.
        self._build_strategy = self._self_heal_strategy(
            self._build_strategy,
            artifacts.get("dockerfile") or "",
        )
        self._finish_stream = finish_stream
        # Path on disk where the analyzed repository lives. When provided, its
        # contents are mirrored into the temp build context so COPY paths
        # referencing repo files resolve correctly.
        self._repo_source_path: str | None = repo_source_path
        # Last-resort clone source — when repo_source_path is missing or stale,
        # the executor re-clones from this URL so a single missing piece of
        # workflow state can never leave the build context empty.
        self._repo_url: str | None = repo_url
        self._repository_visibility: str = repository_visibility
        self._github_token: str | None = github_token
        logger.info(
            "[RepoTrace] repo_source_path received by executor: %s repo_url=%s task=%s",
            repo_source_path or "(not provided)",
            repo_url or "(not provided)",
            task_id,
        )
        # Retry session metadata — surfaces in every emitted event so the
        # frontend can segment logs per retry attempt.
        self._retry_iteration: int = max(1, int(retry_iteration or 1))
        self._execution_session_id: str = (
            execution_session_id
            or f"{task_id[:8]}-r{self._retry_iteration}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        )
        # Tracking for structured failure diagnostics
        self._docker_command: str | None = None
        self._last_error_line: str | None = None
        self._failed_step: str | None = None
        # COPY introspection state — populated by _extract_copy_sources +
        # _resolve_final_build_context. Used by the build-context diagnostic
        # block and the pre-execution COPY check.
        self._copy_sources: list[str] = []
        self._resolved_build_context_path: Path | None = None

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
            "[BuildContext] session=%s retry=%d strategy=%s context=%s dockerfile=%s image=%s",
            self._execution_session_id, self._retry_iteration,
            strategy, ctx, df_path, self.image_tag,
        )
        await self._emit(LogLevel.INFO, "─" * 60)
        await self._emit(LogLevel.INFO, "[BuildContext] Build strategy trace:")
        await self._emit(LogLevel.INFO, f"  session_id:    {self._execution_session_id}")
        await self._emit(LogLevel.INFO, f"  retry_iteration: {self._retry_iteration}")
        await self._emit(LogLevel.INFO, f"  strategy:      {strategy}")
        await self._emit(LogLevel.INFO, f"  repo_root:     {self._repo_source_path or '(not provided)'}")
        await self._emit(LogLevel.INFO, f"  temp_context:  {self._workspace or 'not yet created'}")
        await self._emit(LogLevel.INFO, f"  dockerfile:    {df_path}")
        await self._emit(LogLevel.INFO, f"  build_context: {ctx}")
        await self._emit(LogLevel.INFO, f"  image tag:     {self.image_tag}")
        await self._emit(LogLevel.INFO, "─" * 60)

    async def _ensure_repo_available(self) -> None:
        """
        Guarantee ``self._repo_source_path`` points to an on-disk directory.

        Resolution order:
          1. If the provided path exists and is a directory → keep it.
          2. Otherwise, if a repo_url is available, clone it now.
          3. Otherwise, leave it None — the downstream COPY assertion in
             _write_artifacts will fail the build with a clear error.

        This method is idempotent and runs at most one clone per build.
        """
        if self._repo_source_path:
            path = Path(self._repo_source_path)
            if path.is_dir():
                logger.info(
                    "[RepoTrace] _ensure_repo_available: existing path OK %s task=%s",
                    self._repo_source_path, self.task_id,
                )
                return
            logger.warning(
                "[RepoTrace] _ensure_repo_available: persisted path missing on disk: %s — will re-clone",
                self._repo_source_path,
            )
            await self._emit(
                LogLevel.WARNING,
                f"[RepoTrace] persisted repo_source_path missing on disk: "
                f"{self._repo_source_path} — re-cloning",
            )

        if not self._repo_url:
            logger.warning(
                "[RepoTrace] _ensure_repo_available: no repo_url available — "
                "cannot re-clone. task=%s", self.task_id,
            )
            await self._emit(
                LogLevel.WARNING,
                "[RepoTrace] no repo_url available to re-clone the repository. "
                "Build context will be empty unless artifacts are self-contained.",
            )
            return

        try:
            from backend.app.services.repository.github_service import GitHubService
            await self._emit(
                LogLevel.INFO,
                f"[RepoTrace] cloning repository from {self._repo_url} …",
            )
            gh = GitHubService()
            cloned = await asyncio.to_thread(
                gh.clone_repository,
                self._repo_url,
                self._repository_visibility,
                self._github_token,
            )
            self._repo_source_path = cloned
            logger.info(
                "[RepoTrace] _ensure_repo_available: cloned %s → %s task=%s",
                self._repo_url, cloned, self.task_id,
            )
            await self._emit(
                LogLevel.SUCCESS,
                f"[RepoTrace] repository cloned to {cloned}",
            )
        except Exception as exc:
            logger.error(
                "[RepoTrace] _ensure_repo_available: clone failed task=%s url=%s err=%s",
                self.task_id, self._repo_url, exc,
            )
            await self._emit(
                LogLevel.ERROR,
                f"[RepoTrace] clone failed: {exc}. Downstream COPY check will block the build.",
            )

    async def _write_artifacts(self) -> None:
        """
        Stage the build context.

        Order matters:
          1. Mirror the analyzed repository tree into the temp workspace so
             every COPY src referenced by the Dockerfile resolves against a
             real file. Without this, monorepo COPY paths like
             ``COPY backend/app/requirements.txt`` fail with "file not found
             in build context" — the temp workspace would only contain the
             Dockerfile.
          2. Overlay generated/user-edited artifacts (Dockerfile,
             .dockerignore, docker-compose, .env.example) so they win over
             any in-repo copies.
          3. Hard-validate that every COPY source physically exists inside
             the final workspace. If any are missing, abort the build with
             a clear error BEFORE invoking docker.
        """
        ws = Path(self._workspace)  # type: ignore[arg-type]

        # ── 0. Ensure a repo path exists on disk before the mirror step ───────
        # When repo_source_path is missing or stale (temp clone garbage-collected,
        # server restart, task created before previous-round fixes shipped, etc.)
        # we re-clone from repo_url. This is the LAST line of defense before
        # build context creation — it guarantees we never reach the COPY check
        # with an empty workspace and "(not provided)" in the trace.
        await self._ensure_repo_available()

        # ── 1. Mirror repo into the workspace (when available) ────────────────
        mirrored_count = 0
        if self._repo_source_path:
            src_root = Path(self._repo_source_path)
            await self._emit(
                LogLevel.INFO,
                f"[Mirror] copying repository tree from {src_root} → {ws}",
            )
            if src_root.is_dir():
                try:
                    mirrored_count = await asyncio.to_thread(
                        self._mirror_repo_tree, src_root, ws,
                    )
                    logger.info(
                        "[Mirror] task=%s session=%s repo_root=%s temp=%s files=%d",
                        self.task_id, self._execution_session_id,
                        src_root, ws, mirrored_count,
                    )
                    await self._emit(
                        LogLevel.INFO,
                        f"[Mirror] completed: {mirrored_count} file(s) copied "
                        f"from {src_root} into {ws}",
                    )
                except Exception as exc:
                    logger.warning(
                        "[DockerExecutor] Repo mirror failed: %s", exc,
                    )
                    await self._emit(
                        LogLevel.ERROR,
                        f"[Mirror] FAILED — COPY paths referencing repo files "
                        f"will not resolve: {exc}",
                    )
            else:
                logger.warning(
                    "[DockerExecutor] repo_source_path does not exist on disk: %s",
                    self._repo_source_path,
                )
                await self._emit(
                    LogLevel.ERROR,
                    f"[Mirror] FAILED — repo_source_path does not exist: "
                    f"{self._repo_source_path}",
                )
        else:
            # No repo path provided — this is almost always a misconfiguration.
            # Log loudly so operators see it immediately. The hard COPY check
            # below will then block the build with a precise error message.
            logger.warning(
                "[DockerExecutor] No repo_source_path supplied — build context "
                "will contain ONLY the generated artifacts. Any COPY of a repo "
                "file will fail. task=%s",
                self.task_id,
            )
            await self._emit(
                LogLevel.WARNING,
                "[Mirror] SKIPPED — repo_source_path not provided. Only "
                "generated artifacts will be in the build context.",
            )

        # ── 1b. Hard assertion: mirror must succeed when repo files are needed ─
        dockerfile_content = self.artifacts.get("dockerfile") or ""
        self._copy_sources = self._extract_copy_sources(dockerfile_content)
        needs_repo_files = bool(self._copy_sources)

        if needs_repo_files and self._repo_source_path:
            # repo path was supplied — assert the mirror succeeded
            assert Path(self._repo_source_path).is_dir(), (
                f"[BuildContext] repo_source_path is not a directory: "
                f"{self._repo_source_path}"
            )
            if mirrored_count == 0:
                snapshot = self._snapshot_workspace(ws)
                await self._emit(LogLevel.ERROR, "─" * 60)
                await self._emit(LogLevel.ERROR, "[BuildContext] MIRROR FAILED — 0 files copied")
                for line in snapshot:
                    await self._emit(LogLevel.ERROR, f"  {line}")
                await self._emit(LogLevel.ERROR, "─" * 60)
                raise RuntimeError(
                    "Repository mirror failed — build context incomplete. "
                    f"repo_source_path={self._repo_source_path} "
                    f"workspace={ws} mirrored=0 files. "
                    "Dockerfile references repo files that cannot be resolved."
                )

        if needs_repo_files and not self._repo_source_path:
            # Dockerfile references repo files but no path was supplied at all.
            # This is the catastrophic case the user reported: repo_root=(not provided).
            raise RuntimeError(
                "Build context is incomplete: Dockerfile contains COPY of "
                f"{len(self._copy_sources)} repo path(s) but no repo_source_path "
                "was supplied to the executor. Cannot proceed."
            )

        # ── 2. Overlay artifacts (always win) ─────────────────────────────────
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

        # ── 2b. Resolve the final build context against the (now mirrored) ws ─
        self._resolve_final_build_context(ws, dockerfile_content)

        # ── 2c. Emit the comprehensive [BuildContext] diagnostic block ────────
        snapshot = self._snapshot_workspace(ws)
        existing_root = [n for n in snapshot if not n.startswith("  ")][:20]
        await self._emit(LogLevel.INFO, "═" * 60)
        await self._emit(LogLevel.INFO, "[BuildContext]")
        await self._emit(LogLevel.INFO, f"  repo_source_path     = {self._repo_source_path or '(not provided)'}")
        await self._emit(LogLevel.INFO, f"  workspace            = {ws}")
        await self._emit(LogLevel.INFO, f"  mirrored_files       = {mirrored_count}")
        await self._emit(LogLevel.INFO, f"  dockerfile_path      = {ws / 'Dockerfile'}")
        await self._emit(LogLevel.INFO, f"  build_context        = {self._resolved_build_context_path}")
        await self._emit(LogLevel.INFO, f"  existing_root_files  = {existing_root}")
        await self._emit(LogLevel.INFO, "═" * 60)
        await self._emit(LogLevel.INFO, f"Workspace prepared: {self._workspace}")

        # ── 3. Per-source COPY check (visible in live logs) ───────────────────
        for src in self._copy_sources:
            resolved = (ws / src).resolve()
            exists = resolved.exists()
            await self._emit(
                LogLevel.INFO if exists else LogLevel.ERROR,
                f"[COPY CHECK] source={src} resolved_path={resolved} exists={str(exists).lower()}",
            )

        # ── 4. Hard validation: every COPY source must exist in workspace ────
        missing = self._collect_missing_copy_sources(ws, dockerfile_content)
        if missing:
            details = "\n".join(
                f"    COPY {m['src']} → not found at {m['expected_abs']}"
                for m in missing
            )
            workspace_snapshot = self._snapshot_workspace(ws)
            diagnostic_lines = [
                "─" * 60,
                "[BuildContext] PRE-EXECUTION COPY CHECK FAILED",
                f"  repo_source_path       = {self._repo_source_path or '(not provided)'}",
                f"  resolved_build_context = {self._resolved_build_context_path or ws}",
                f"  dockerfile_path        = {Path(ws) / 'Dockerfile'}",
                f"  temp_workspace         = {ws}",
                f"  mirrored_files_count   = {mirrored_count}",
                f"  missing_sources        = {[m['src'] for m in missing]}",
                "  workspace_contents:",
            ]
            for entry in workspace_snapshot:
                diagnostic_lines.append(f"    - {entry}")
            diagnostic_lines.append("─" * 60)
            for line in diagnostic_lines:
                await self._emit(LogLevel.ERROR, line)
            raise FileNotFoundError(
                "Pre-execution COPY check failed: "
                f"{len(missing)} source(s) are missing from the build context.\n"
                f"{details}\n"
                f"build_context={ws} repo_mirrored={mirrored_count} files\n"
                f"repo_source_path={self._repo_source_path or '(not provided)'}\n"
                f"workspace_top_level={workspace_snapshot}"
            )

    @staticmethod
    def _mirror_repo_tree(src_root: Path, dest_root: Path) -> int:
        """
        Copy the repository tree into the build context. Skips .git, large
        build outputs, and node_modules to keep the workspace lean. Returns
        the number of files copied.
        """
        skip_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__",
                     ".pytest_cache", ".mypy_cache", "dist", "build",
                     "target", ".gradle", ".idea", ".vscode"}
        copied = 0
        skipped = 0
        for path in src_root.rglob("*"):
            rel = path.relative_to(src_root)
            parts = set(rel.parts)
            if parts & skip_dirs:
                skipped += 1
                continue
            dest = dest_root / rel
            if path.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            elif path.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(path, dest)
                    copied += 1
                except (OSError, shutil.SameFileError):
                    skipped += 1
                    continue
        logger.info(
            "[Mirror] tree copy %s → %s : copied=%d skipped=%d",
            src_root, dest_root, copied, skipped,
        )
        return copied

    @staticmethod
    def _self_heal_strategy(strategy: dict, dockerfile: str) -> dict:
        """
        Reconcile a persisted build strategy with the actual Dockerfile content.

        If the strategy says ``context_path=backend/app`` but the Dockerfile has
        ``COPY requirements-backend.txt .`` (bare filename → repo-root-relative),
        override to ``repo_root_context``. The override is recorded in the
        ``_self_healed_from`` field so operators can trace the change.

        This mirrors the route-level _autocorrect_build_strategy helper but
        runs INSIDE the executor so it cannot be bypassed by a stale state.
        """
        if not strategy or not dockerfile:
            return strategy or {}
        context_path = (strategy.get("context_path") or ".").strip()
        if context_path in ("", "."):
            return strategy  # already repo root

        sources = DockerExecutor._extract_copy_sources(dockerfile)
        if not sources:
            return strategy

        prefix = context_path.rstrip("/") + "/"
        root_relative_count = 0
        for src in sources:
            if src.startswith(prefix):
                continue
            if "/" not in src and "\\" not in src:
                root_relative_count += 1

        if root_relative_count == 0:
            return strategy

        logger.warning(
            "[BuildContext] executor self-heal: persisted strategy=%s context=%s "
            "but %d/%d COPY source(s) are repo-root-relative — switching to "
            "repo_root_context.",
            strategy.get("strategy"), context_path,
            root_relative_count, len(sources),
        )
        return {
            "strategy": "repo_root_context",
            "context_path": ".",
            "dockerfile_path": "Dockerfile",
            "recommended_copy_prefix": None,
            "_self_healed_from": {
                "strategy": strategy.get("strategy"),
                "context_path": strategy.get("context_path"),
                "reason": (
                    f"{root_relative_count}/{len(sources)} COPY source(s) "
                    "are repo-root-relative; persisted strategy targeted subdir."
                ),
            },
        }

    @staticmethod
    def _snapshot_workspace(workspace: Path, max_entries: int = 30) -> list[str]:
        """
        Return a flat listing of the top-level files/dirs in the workspace
        for inclusion in failure diagnostics. Trailing slash = directory.
        """
        try:
            entries = []
            for p in sorted(workspace.iterdir()):
                entries.append(p.name + ("/" if p.is_dir() else ""))
                if len(entries) >= max_entries:
                    entries.append(f"… ({len(list(workspace.iterdir())) - max_entries} more)")
                    break
            return entries
        except Exception as exc:
            return [f"(snapshot failed: {exc})"]

    @staticmethod
    def _extract_copy_sources(dockerfile: str) -> list[str]:
        """
        Parse every COPY/ADD instruction in the Dockerfile and return the
        list of source paths. Skips:
          • ``--from=stage`` copies (sources come from prior build stages)
          • bare ``.`` and ``./`` sources (whole-context copies)
        Returns repo-relative paths verbatim — caller decides how to resolve.
        """
        import re as _re
        copy_re = _re.compile(r"(?im)^\s*(COPY|ADD)\s+(.*)$")
        sources: list[str] = []
        for m in copy_re.finditer(dockerfile or ""):
            tail = m.group(2).strip()
            if "--from=" in tail:
                continue
            tokens = [t for t in tail.split() if t and not t.startswith("--")]
            if len(tokens) < 2:
                continue
            for src in tokens[:-1]:
                clean = src.strip().strip(',').strip('"').strip("'").lstrip("[").rstrip("]")
                if not clean or clean in (".", "./"):
                    continue
                sources.append(clean)
        return sources

    def _resolve_final_build_context(
        self,
        repo_root: Path,
        dockerfile: str,
    ) -> Path:
        """
        Decide which directory will be used as ``docker build``'s context.

        Rules (first match wins):
          1. If any COPY source resolves at the repo root (bare filename OR
             explicit root-level path that exists on disk), the build context
             must be the repo root.
          2. Otherwise stick with whatever context the build strategy named
             (already mirrored into self._workspace).

        Sets and returns ``self._resolved_build_context_path``.
        """
        repo_root = Path(repo_root).resolve()
        sources = self._extract_copy_sources(dockerfile)
        for src in sources:
            # Bare filename (no slash) → always repo-root-relative.
            if "/" not in src and "\\" not in src:
                self._resolved_build_context_path = repo_root
                logger.info(
                    "[BuildContext] resolved context=repo_root (bare-name COPY %r → %s)",
                    src, repo_root,
                )
                return repo_root
            # Otherwise check on disk
            candidate = (repo_root / src).resolve()
            try:
                candidate.relative_to(repo_root)
            except ValueError:
                continue
            if candidate.exists():
                self._resolved_build_context_path = repo_root
                logger.info(
                    "[BuildContext] resolved context=repo_root (COPY %r → %s exists)",
                    src, candidate,
                )
                return repo_root

        # No root-relative COPY → keep the configured strategy context.
        ctx = Path(self._build_strategy.get("context_path") or repo_root)
        if not ctx.is_absolute():
            ctx = (repo_root / ctx).resolve()
        self._resolved_build_context_path = ctx
        logger.info("[BuildContext] resolved context=%s (no root-relative COPY)", ctx)
        return ctx

    def _collect_missing_copy_sources(
        self,
        workspace: Path,
        dockerfile: str,
    ) -> list[dict[str, str]]:
        """
        Parse COPY/ADD instructions and check each source against the workspace.

        Returns a list of {src, expected_abs} dicts for sources that do not
        resolve to a file or directory inside the workspace. Globs are
        considered satisfied if any matching path exists. ``--from=<stage>``
        copies are skipped (their sources come from earlier build stages).
        """
        import re as _re
        import glob as _glob

        missing: list[dict[str, str]] = []
        ws_resolved = workspace.resolve()
        # Match: COPY [flags] src [src...] dst   /   ADD [flags] src [src...] dst
        copy_re = _re.compile(r"(?im)^\s*(COPY|ADD)\s+(.*)$")
        for m in copy_re.finditer(dockerfile or ""):
            tail = m.group(2).strip()
            # Strip flags like --from=, --chown=, --chmod=
            tokens = [t for t in tail.split() if t]
            tokens = [t for t in tokens if not t.startswith("--")]
            # If --from=<stage> was in flags, skip this copy entirely.
            if "--from=" in tail:
                continue
            if len(tokens) < 2:
                continue
            srcs = tokens[:-1]
            for src in srcs:
                # JSON exec form COPY ["src","dst"] — strip brackets/quotes
                clean = src.strip().strip(',').strip('"').strip("'").lstrip("[").rstrip("]")
                if not clean or clean in (".", "./"):
                    continue
                # Compute absolute path inside workspace
                abs_path = (workspace / clean).resolve()
                # Reject path traversal
                if not str(abs_path).startswith(str(ws_resolved)):
                    missing.append({"src": clean, "expected_abs": str(abs_path)})
                    continue
                # Direct existence check
                if abs_path.exists():
                    continue
                # Glob check
                matches = _glob.glob(str(abs_path), recursive=True)
                if matches:
                    continue
                # Try as relative pattern from workspace (handles **)
                glob_matches = list(workspace.glob(clean))
                if glob_matches:
                    continue
                missing.append({"src": clean, "expected_abs": str(abs_path)})
        return missing

    async def _run_docker_build(self) -> int:
        """Run `docker build -f <dockerfile> -t <tag> <context>` and stream output."""
        dockerfile_path = str(Path(self._workspace) / "Dockerfile")  # type: ignore[arg-type]
        cmd = [
            "docker", "build",
            "--progress=plain",
            "-f", dockerfile_path,
            "-t", self.image_tag,
            str(self._workspace),
        ]
        self._docker_command = " ".join(cmd)
        logger.info(
            "[DockerExecutor] Starting build for task %s session=%s",
            self.task_id, self._execution_session_id,
        )
        logger.info("[DockerExecutor] FULL COMMAND: %s", self._docker_command)
        await self._emit(LogLevel.INFO, "─" * 60)
        await self._emit(LogLevel.INFO, f"[DockerExecutor] $ {self._docker_command}")
        await self._emit(LogLevel.INFO, "─" * 60)
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
        import time as _time
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,  # Capture stderr separately
            cwd=self._workspace,
        )
        start = _time.monotonic()
        logger.info("[DockerExecutor] %s phase started", phase_label)

        last_stdout: str | None = None
        last_stderr: str | None = None
        stdout_count = 0
        stderr_count = 0

        async def _drain_stdout() -> None:
            nonlocal last_stdout, stdout_count
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode(errors="replace").rstrip()
                if line:
                    last_stdout = line
                    self._track_step(line)
                    await self._publish_log_line(line)
                    stdout_count += 1

        async def _drain_stderr() -> None:
            nonlocal last_stderr, stderr_count
            assert proc.stderr is not None
            async for raw_line in proc.stderr:
                line = raw_line.decode(errors="replace").rstrip()
                if line:
                    last_stderr = line
                    self._last_error_line = line
                    await self._publish_log_line(line)
                    stderr_count += 1

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
        duration_ms = int((_time.monotonic() - start) * 1000)
        if exit_code == 0:
            logger.info(
                "[DockerExecutor] %s phase succeeded exit=0 stdout=%d stderr=%d duration=%dms",
                phase_label, stdout_count, stderr_count, duration_ms,
            )
        else:
            logger.warning(
                "[DockerExecutor] %s phase failed exit=%d stdout=%d stderr=%d duration=%dms last=%s",
                phase_label, exit_code, stdout_count, stderr_count, duration_ms,
                last_stderr or last_stdout,
            )
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

        meta = dict(metadata or {})
        meta.setdefault("retry_iteration", self._retry_iteration)
        meta.setdefault("execution_session_id", self._execution_session_id)

        await emit_execution_event(
            self.task_id,
            event_type,
            message=message,
            status=status,
            phase=phase,
            iteration=self._retry_iteration,
            metadata=meta,
        )

    def _cleanup_workspace(self) -> None:
        if self._workspace and os.path.exists(self._workspace):
            try:
                shutil.rmtree(self._workspace, ignore_errors=True)
            except Exception:
                pass
            self._workspace = None
