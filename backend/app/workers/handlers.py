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

import asyncio
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


# ── terraform_validate / terraform_plan ───────────────────────────────────────


async def _run_terraform_phase(job: ExecutionJob, *, steps_name: str) -> Optional[dict]:
    """Shared body for the streamed Terraform validation / plan phases.

    Runs the terraform command sequence against the generated artifact
    directory, streaming every line over the existing ``log_stream_manager``
    (so it surfaces on the same WebSocket as Docker builds), then records the
    outcome into the workflow. A terraform-logic failure (bad config, missing
    cloud credentials) is NOT raised — it is recorded as a failed phase and the
    job still succeeds, so the worker does not pointlessly retry it. Only an
    environment error (terraform binary absent) propagates.
    """
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService,
    )
    from backend.app.services.execution.docker_streamer import log_stream_manager
    from backend.app.services.terraform_pipeline import TerraformPipelineService
    from backend.app.services.terraform_pipeline.pipeline_service import (
        PLAN_STEPS,
        VALIDATE_STEPS,
    )
    from backend.app.services.terraform_pipeline.streaming import stream_terraform_steps

    ctx = dict(job.execution_context or {})
    artifact_id = ctx.get("artifact_id")
    task_id = ctx.get("task_id")
    workflow_id = ctx.get("workflow_id")
    phase = ctx.get("phase")
    stream_key = ctx.get("stream_key") or f"{task_id}::{steps_name}"
    if not artifact_id or not phase:
        raise ValueError(
            f"{steps_name} job missing artifact_id/phase in execution_context"
        )

    steps = VALIDATE_STEPS if steps_name == "terraform_validate" else PLAN_STEPS

    svc = TerraformPipelineService()
    artifact_dir = svc.artifact_path(artifact_id)

    async def _publish(line: str) -> None:
        await log_stream_manager.publish(stream_key, line)

    ok = False
    results: list[dict] = []
    error: Optional[str] = None
    failure_classification: Optional[str] = None
    env_error: Optional[Exception] = None
    plan_json: Optional[str] = None
    infrastructure_summary: Optional[dict] = None
    try:
        await _publish(f"== {phase} starting (artifact {artifact_id}) ==")
        # DB-authoritative rehydrate (no filesystem-trust). The persisted
        # ``terraform`` Artifact rows are the SINGLE source of truth for the
        # generated HCL; ``generated_terraform/<id>/`` is only a process-local
        # projection that can be stale (a re-generation bumped the DB), partial,
        # or wiped by a restart — and the generation step also leaves inert
        # canonical-key-named files there. So we ALWAYS rebuild the working
        # directory from the DB before running terraform: validate/plan never run
        # against whatever happens to be sitting on disk. Only when the DB holds
        # no terraform artifacts do we fall back to an existing on-disk dir.
        from backend.app.services.core.artifact_persistence_service import (
            ArtifactPersistenceService as _APS,
        )
        db_rh = SessionLocal()
        try:
            tf_files = _APS.get_terraform_files(
                db_rh, project_id=job.project_id, workflow_id=workflow_id,
            )
        finally:
            db_rh.close()
        if tf_files:
            svc.rehydrate(artifact_id, tf_files)
            await _publish(
                f"== rehydrated {len(tf_files)} terraform file(s) from DB (authoritative) =="
            )
        elif (not artifact_dir.exists()) or not any(artifact_dir.glob("*.tf")):
            await _publish(
                "WARN: no terraform artifacts in DB and no on-disk HCL to "
                "rehydrate — terraform will likely fail"
            )
        ok, results = await stream_terraform_steps(artifact_dir, steps, _publish)
        if not ok:
            error = "terraform reported a non-zero exit — see logs"
            # Classify the failure (NETWORK_ERROR / PROVIDER_FETCH_FAILED /
            # VALIDATION_FAILED) from the captured terraform output so a registry
            # outage is reported as a transient/recoverable problem rather than a
            # config defect.
            from backend.app.services.terraform_generation.validators import (
                classify_terraform_output,
            )
            combined = "\n".join(
                str(r.get("output") or "") for r in results if not r.get("ok")
            )
            failure_classification = classify_terraform_output(combined)
            if failure_classification:
                await _publish(f"== failure classified as {failure_classification} ==")
        elif steps_name == "terraform_plan":
            # Plan succeeded → derive a human-readable Infrastructure Summary.
            # A failure here (unparseable plan, terraform show error) must NOT
            # fail the plan phase itself — the plan still ran fine.
            plan_json, infrastructure_summary = await _build_plan_summary(
                artifact_dir, _publish
            )
    except asyncio.CancelledError:
        # Phase 3A — operator cancelled the job. The streaming runner already
        # stopped the terraform child (terminate→grace→kill). Record the phase as
        # cancelled (preserving artifact_id/job_id for Replay), finish the stream
        # so the WS emits a `cancelled` complete frame, then re-raise so the worker
        # finalises the job as cancelled. We do NOT fall through to the
        # record_terraform_phase_result(failed) path below.
        await _publish("== phase cancelled by operator ==")
        await log_stream_manager.finish(stream_key)
        db_c = SessionLocal()
        try:
            WorkflowOrchestrationService.record_terraform_phase_cancelled(
                db_c,
                workflow_id=workflow_id,
                task_id=task_id,
                phase=phase,
            )
        finally:
            db_c.close()
        raise
    except RuntimeError as exc:
        # Environment problem (binary missing / artifact dir gone). Record the
        # phase as failed AND propagate so the job itself is marked failed.
        error = str(exc)
        env_error = exc
        await _publish(f"ERROR: {error}")
    finally:
        await log_stream_manager.finish(stream_key)

    db = SessionLocal()
    try:
        WorkflowOrchestrationService.record_terraform_phase_result(
            db,
            workflow_id=workflow_id,
            task_id=task_id,
            project_id=job.project_id,
            phase=phase,
            ok=ok,
            results=results,
            artifact_id=artifact_id,
            error=error,
            failure_classification=failure_classification,
            plan_json=plan_json,
            infrastructure_summary=infrastructure_summary,
        )
    finally:
        db.close()

    if env_error is not None:
        raise env_error

    return {"phase": phase, "artifact_id": artifact_id, "ok": ok}


async def _build_plan_summary(artifact_dir, publish) -> tuple[Optional[str], Optional[dict]]:
    """Generate ``plan.json`` + a categorized Infrastructure Summary.

    Best-effort: any failure is logged to the live stream and swallowed
    (returns ``(None, None)``) so the already-successful plan phase is never
    downgraded to failed just because the readable summary could not be built.
    """
    from backend.app.services.terraform_pipeline.plan_summary import (
        build_infrastructure_summary,
        generate_plan_json,
    )

    try:
        await publish("== generating plan summary (terraform show -json) ==")
        plan_json = await generate_plan_json(artifact_dir)
        if not plan_json:
            await publish("WARN: could not read plan JSON — summary skipped")
            return None, None
        summary = build_infrastructure_summary(plan_json)
        if summary is not None:
            await publish(
                f"== infrastructure summary: {summary.get('total_resources', 0)} "
                f"resource(s) across {len(summary.get('categories') or [])} categor(ies) =="
            )
        return plan_json, summary
    except Exception as exc:  # noqa: BLE001 — summary is best-effort
        logger.warning("[Jobs] plan summary generation failed: %s", exc)
        await publish(f"WARN: plan summary generation failed: {exc}")
        return None, None


@register("terraform_validate")
async def _handle_terraform_validate(job: ExecutionJob) -> Optional[dict]:
    """Run ``terraform init -backend=false`` + ``terraform validate``, streamed."""
    return await _run_terraform_phase(job, steps_name="terraform_validate")


@register("terraform_plan")
async def _handle_terraform_plan(job: ExecutionJob) -> Optional[dict]:
    """Run ``terraform init -backend=false`` + ``terraform plan -out=tfplan``, streamed."""
    return await _run_terraform_phase(job, steps_name="terraform_plan")
