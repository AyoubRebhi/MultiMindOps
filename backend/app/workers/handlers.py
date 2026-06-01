"""Job handler registry.

A handler is an ``async`` callable that performs the actual work for one
job ``phase``. The worker owns the job lifecycle (claim, heartbeat, terminal
status, cancellation); a handler just DOES the work and either returns a
small ``result_summary`` dict or raises to signal failure.

Handler contract
----------------
    async def handler(job: ExecutionJob) -> dict | None: ...

* ``job.execution_context`` carries everything the handler needs EXCEPT
  secrets. Secrets (github_token, AWS creds) are re-fetched from the
  encrypted credentials store inside the handler at run time (Phase 4).
* Raising any exception ⇒ the worker routes the job through retry/fail.
* Returning (or returning a dict) ⇒ the worker marks the job succeeded,
  storing the dict as ``result_summary``.
* Handlers MUST be cancellation-aware where they own a subprocess: on
  ``asyncio.CancelledError`` they should terminate the child process in a
  ``finally`` and re-raise. (The Docker executor already cleans up its temp
  workspace in a finally; hard subprocess kill on cancel is a follow-up.)

Lazy imports
------------
Handlers import the heavy modules (DockerExecutor, route helpers) INSIDE the
function body, not at module load. This keeps the worker importable in a
standalone process without dragging in the FastAPI app, and avoids a circular
import between the worker and the route modules that enqueue jobs.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from backend.app.database.session import SessionLocal
from backend.app.models.execution_job import ExecutionJob

logger = logging.getLogger(__name__)


# phase → async handler
_REGISTRY: dict[str, Callable[[ExecutionJob], Awaitable[Optional[dict]]]] = {}


def register(phase: str):
    """Decorator registering a coroutine as the handler for ``phase``."""
    def _wrap(fn: Callable[[ExecutionJob], Awaitable[Optional[dict]]]):
        _REGISTRY[phase] = fn
        return fn
    return _wrap


def get_handler(phase: str) -> Optional[Callable[[ExecutionJob], Awaitable[Optional[dict]]]]:
    return _REGISTRY.get(phase)


def registered_phases() -> list[str]:
    return sorted(_REGISTRY)


# ── docker_build ────────────────────────────────────────────────────────────


@register("docker_build")
async def _handle_docker_build(job: ExecutionJob) -> Optional[dict]:
    """Run a Docker build for a task.

    ``execution_context`` carries the build parameters that the API
    endpoint computed (artifacts, image_tag, build strategy, repo path,
    session id, retry flags). The github_token is NOT in the context —
    we fetch it from the encrypted credentials store here, keyed by the
    job's project.
    """
    # Lazy imports: pulling the route module is fine at call time and keeps
    # the worker import light + circular-free.
    from backend.app.api.routes.execution import _run_build_background
    from backend.app.services.core.credentials_service import CredentialsService

    ctx = dict(job.execution_context or {})
    task_id = ctx.get("task_id")
    if not task_id:
        raise ValueError("docker_build job missing task_id in execution_context")

    # Re-hydrate the clone token at run time — never persisted in the job.
    github_token: Optional[str] = None
    db = SessionLocal()
    try:
        github_token = CredentialsService.get_credential(
            db, project_id=job.project_id, provider="github_pat",
        )
    except Exception as exc:
        logger.warning(
            "[Jobs] docker_build token fetch failed project=%s: %s",
            job.project_id, exc.__class__.__name__,
        )
    finally:
        db.close()

    await _run_build_background(
        task_id=task_id,
        artifacts=ctx.get("artifacts") or {},
        image_tag=ctx.get("image_tag") or "",
        is_retry=bool(ctx.get("is_retry")),
        build_number=int(ctx.get("build_number") or 1),
        build_strategy=ctx.get("build_strategy") or {},
        repo_source_path=ctx.get("repo_source_path"),
        execution_session_id=ctx.get("execution_session_id"),
        repo_url=ctx.get("repo_url"),
        repository_visibility=ctx.get("repository_visibility") or "public",
        github_token=github_token,
    )
    # The build persists its own detailed result into workflow_state; the
    # job result_summary just records the high-level outcome pointer.
    return {
        "task_id": task_id,
        "build_number": ctx.get("build_number"),
        "logs_reference": "workflow_state.execution.docker.logs",
    }


# ── corrector_reanalyze ───────────────────────────────────────────────────────


@register("corrector_reanalyze")
async def _handle_corrector_reanalyze(job: ExecutionJob) -> Optional[dict]:
    """Re-run corrector analysis on a task's stored Docker build logs.

    Re-derives the raw log text + artifacts from the task's persisted
    workflow_state so the job row stays lean and the work is re-runnable
    after a crash.
    """
    from backend.app.api.routes.corrector import (
        _docker_artifacts,
        _docker_logs_text,
        _reanalyze_background,
    )
    from backend.app.services.core.task_service import TaskService

    ctx = dict(job.execution_context or {})
    task_id = ctx.get("task_id")
    if not task_id:
        raise ValueError("corrector_reanalyze job missing task_id in execution_context")

    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if task is None:
            raise ValueError(f"corrector_reanalyze: task {task_id} not found")
        state = TaskService.load_workflow_state(db, task) or {}
        raw_logs = _docker_logs_text(state)
        artifacts = _docker_artifacts(state)
    finally:
        db.close()

    await _reanalyze_background(task_id, raw_logs, artifacts)
    return {"task_id": task_id, "reanalyzed": True}
