"""
Execution router — Docker Build Execution Engine.

Endpoints
---------
POST /api/execution/docker/build/{task_id}
    Start an async Docker build.  Returns immediately with status="running".
    The build continues in a background asyncio task.

WS   /ws/execution/{task_id}
    Stream live log entries (JSON) until the build finishes.
    Reconnect-safe: new subscribers receive the full log history first.

GET  /api/execution/docker/status/{task_id}
    Return persisted execution state (logs survive page refresh).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from backend.app.core.authorization import (
    require_task_project_contributor,
    require_task_project_member,
    resolve_task_membership,
)
from backend.app.core.config import settings
from backend.app.core.jwt import TokenError, decode_token
from backend.app.core.security import get_current_user
from backend.app.database.session import SessionLocal
from backend.app.models.project import ProjectMember
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.services.core.artifact_service import ArtifactService, ArtifactStateResolver
from backend.app.services.core.task_service import TaskService
from backend.app.services.execution.docker_connectivity import docker_health_check
from backend.app.services.execution.docker_executor import DockerExecutor
from backend.app.services.execution.docker_registry import generate_image_tag
from backend.app.services.execution.docker_streamer import log_stream_manager
from backend.app.services.execution.execution_state_service import (
    emit_execution_event,
    load_execution_history,
    record_execution_event,
)
from backend.app.services.execution.execution_models import (
    DockerBuildResult,
    ExecutionEvent,
    ExecutionLogEntry,
    ExecutionMachineStatus,
    ExecutionStatus,
    LogLevel,
)
from backend.app.services.execution.job_service import JobService

logger = logging.getLogger(__name__)

# HTTP routes use /api/execution/... prefix; WebSocket uses /ws/execution/...
# Both are registered on the same router — see api/router.py for mounting.
router = APIRouter(tags=["Execution"])

# ── Acceptable upstream phases for triggering a build ─────────────────────────
_ALLOWED_BUILD_PHASES = {
    "docker_completed",
    "docker_build_failed",
    "docker_build_success",
    # Corrector phases: human reviewed analysis and approved a retry
    "human_review_required",
    "corrector_analysis_completed",
}
_BLOCKED_BUILD_PHASES = {
    "docker_build_running",
    "corrector_analysis_running",  # Analysis in progress — wait for it
    "execution_failed",            # Max retries exceeded — no more builds
    "terraform_completed",
    "kubernetes_completed",
    "completed",
}


def _sse_payload(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ── DB dependency ──────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_docker_artifacts(workflow_state: dict) -> dict[str, str]:
    """
    Pull Dockerfile + compose artifacts from the persisted workflow state.

    Priority:
      1. workflow_state["artifacts"][key]["current_content"]  ← user-edited (wins)
      2. workflow_state["infra"]["artifacts"]                 ← original generated (fallback)
    """
    result = ArtifactStateResolver.get_latest_artifacts(workflow_state)
    meta = (workflow_state.get("infrastructure") or {}).get("artifacts") or workflow_state.get("artifacts") or {}
    for key in list(result):
        artifact_meta = meta.get(key) or {}
        logger.info(
            "[ArtifactResolver] Loaded artifact=%s version=%s modified_by=%s",
            key,
            artifact_meta.get("version", "legacy"),
            artifact_meta.get("last_modified_by", "generated"),
        )
    return result


def _autocorrect_build_strategy(
    *,
    strategy: dict,
    dockerfile: str,
    repo_source_path: str | None,
    known_files: list[str],
    task_id: str,
) -> dict:
    """
    Reconcile the persisted build strategy with the actual Dockerfile.

    Why this exists
    ---------------
    BuildStrategyDetector ran at generation time using known_files. If the
    detector found ``backend/`` as a top-level dir it tagged the strategy
    ``backend_context`` with ``context_path=backend/app``. But the Dockerfile
    we are ABOUT TO EXECUTE may COPY repo-root files (e.g.
    ``COPY requirements-backend.txt .``). When that file lives at the repo
    root, the build context MUST be the repo root, not ``backend/app``.

    Decision
    --------
    If the Dockerfile's COPY sources all resolve at the REPO ROOT (vs. inside
    the strategy's context_path subdir), override the strategy to
    ``repo_root_context``. Log the override so operators can trace it.
    """
    import os as _os
    import re as _re

    if not strategy:
        strategy = {}
    context_path = (strategy.get("context_path") or ".").strip()
    if context_path in ("", "."):
        # Already repo root — nothing to correct.
        return strategy

    if not dockerfile:
        return strategy

    # Parse COPY sources (skip COPY --from=stage).
    copy_re = _re.compile(r"(?im)^\s*COPY\s+(.*)$")
    copy_sources: list[str] = []
    for m in copy_re.finditer(dockerfile):
        tail = m.group(1).strip()
        if "--from=" in tail:
            continue
        tokens = [t for t in tail.split() if t and not t.startswith("--")]
        if len(tokens) < 2:
            continue
        for src in tokens[:-1]:
            clean = src.strip().strip(',').strip('"').strip("'").lstrip("[").rstrip("]")
            if clean and clean not in (".", "./"):
                copy_sources.append(clean)

    if not copy_sources:
        return strategy

    prefix = context_path.rstrip("/") + "/"
    # Source is "repo-root-relative" when (a) it has no path separator and is
    # not under the strategy's prefix, or (b) it is at the repo root according
    # to known_files / on-disk repo, or (c) it begins with a subdir other than
    # the strategy prefix.
    root_relative_count = 0
    prefix_relative_count = 0
    for src in copy_sources:
        if src.startswith(prefix):
            prefix_relative_count += 1
            continue
        # Bare name (no slash) — almost certainly root-relative
        if "/" not in src and "\\" not in src:
            root_relative_count += 1
            continue
        # If known_files lists this exact path at repo root, it's root-relative.
        if src in known_files:
            root_relative_count += 1
            continue
        # On-disk repo check (definitive when available)
        if repo_source_path:
            candidate = _os.path.join(repo_source_path, src)
            if _os.path.exists(candidate):
                root_relative_count += 1
                continue

    if root_relative_count == 0:
        return strategy

    # Even one root-relative COPY means the persisted strategy is incorrect.
    logger.warning(
        "[BuildContext] strategy override for task=%s: persisted=%s context=%s "
        "but %d/%d COPY source(s) resolve at repo root — forcing repo_root_context",
        task_id, strategy.get("strategy"), context_path,
        root_relative_count, len(copy_sources),
    )
    return {
        "strategy": "repo_root_context",
        "context_path": ".",
        "dockerfile_path": "Dockerfile",
        "recommended_copy_prefix": None,
        "_autocorrected_from": {
            "strategy": strategy.get("strategy"),
            "context_path": strategy.get("context_path"),
            "reason": (
                f"{root_relative_count}/{len(copy_sources)} COPY source(s) "
                "are repo-root-relative; persisted strategy targeted subdir."
            ),
        },
    }


def _enforce_prebuild_validation_gate(
    db: Session,
    task,
    state: dict,
    artifacts: dict[str, str],
) -> JSONResponse | None:
    """
    Multi-layer pre-build validation gate.

    Layers (first failure short-circuits):
      A. Unresolved template placeholders ({{ ... }}, {% ... %}, ${{ ... }}, <%= ... %>)
         in ANY artifact — including docker-compose, dockerignore.
      B. RuntimeSemanticValidator errors on the Dockerfile — distro mismatch,
         exec form, healthcheck dependency, undefined build stage.
      C. DockerBuildStaticValidator — COPY-source resolution against known_files.

    Returns a structured **HTTP 422** ``JSONResponse`` when the build is blocked
    (carrying ``{phase, status, reason, details, ...}`` + the relevant validation
    payload), or ``None`` when the build may proceed. The 422 is the contract
    that lets the frontend surface *why* a build was blocked instead of opening a
    WebSocket against a build that never started.
    """
    dockerfile = artifacts.get("dockerfile") or ""
    if not dockerfile:
        return None

    infra_state = state.get("infrastructure") or {}
    agent_context = state.get("agent_context") or {}
    known_files: list[str] = (
        (infra_state.get("known_files") or [])
        or (agent_context.get("infrastructure_context") or {}).get("known_files")
        or []
    )

    # ── Layer A: unresolved templates (always runs) ───────────────────────────
    try:
        from backend.app.services.artifact_generation.validators.template_artifact_validator import (
            TemplateArtifactValidator,
        )
        template_result = TemplateArtifactValidator().validate(artifacts)
    except Exception as exc:
        logger.warning("[PrebuildGate] Template validation crashed: %s", exc)
        template_result = None

    if template_result is not None and not template_result.valid:
        payload = template_result.to_dict()
        return _block_build(
            db=db,
            task=task,
            state=state,
            failure_kind="template_validation",
            event_type="build_blocked_template_validation",
            payload_key="template_validation",
            payload=payload,
            message=(
                "Pre-build template validation blocked Docker build: "
                f"{payload.get('issue_count', 0)} unresolved template "
                "placeholder(s) found in artifacts."
            ),
        )

    # ── Layer B: RuntimeSemanticValidator (always runs) ───────────────────────
    try:
        from backend.app.services.artifact_generation.validators.runtime_semantic_validator import (
            RuntimeSemanticValidator,
        )
        runtime_result = RuntimeSemanticValidator().validate(dockerfile)
    except Exception as exc:
        logger.warning("[PrebuildGate] Runtime validation crashed: %s", exc)
        runtime_result = None

    if runtime_result is not None and not runtime_result.valid:
        payload = runtime_result.to_dict()
        # Highlight the most actionable error first
        error_count = len([i for i in payload.get("issues", []) if i.get("severity") == "error"])
        return _block_build(
            db=db,
            task=task,
            state=state,
            failure_kind="runtime_validation",
            event_type="build_blocked_runtime_validation",
            payload_key="runtime_validation",
            payload=payload,
            message=(
                "Pre-build runtime validation blocked Docker build: "
                f"{error_count} fatal Dockerfile issue(s) detected "
                "(distro mismatch / exec form / healthcheck / stage / template)."
            ),
        )

    # ── Layer C: COPY source resolution (requires known_files) ────────────────
    if not known_files:
        logger.info(
            "[PrebuildGate] No known_files available — skipping static COPY validation (task=%s)",
            task.id,
        )
        return None

    build_strategy = (infra_state.get("build_artifact_context") or {}).get("strategy") or {}
    build_context = (
        build_strategy.get("context_path")
        or (infra_state.get("repository_build_context") or {}).get("docker", {}).get("context_path")
        or "."
    )

    try:
        from backend.app.services.artifact_generation.validators.docker_static_validator import (
            DockerBuildStaticValidator,
        )
        result = DockerBuildStaticValidator().validate(
            dockerfile_content=dockerfile,
            build_context=build_context,
            known_files=known_files,
        )
    except Exception as exc:
        logger.warning("[PrebuildGate] Static validation crashed: %s", exc)
        return None

    if result.valid:
        logger.info(
            "[PrebuildGate] All validation layers passed — proceeding with build (task=%s)",
            task.id,
        )
        return None

    issues_payload = result.to_dict()
    return _block_build(
        db=db,
        task=task,
        state=state,
        failure_kind="static_validation",
        event_type="build_blocked_static_validation",
        payload_key="static_validation",
        payload=issues_payload,
        message=(
            "Pre-build static validation blocked Docker build: "
            f"{issues_payload.get('issue_count', 0)} unresolved "
            "COPY/build-context issue(s) detected."
        ),
    )


# failure_kind → (machine-readable reason code, human-readable summary).
_BLOCK_REASON: dict[str, tuple[str, str]] = {
    "template_validation": (
        "UNRESOLVED_TEMPLATE_TOKEN",
        "Generated artifacts still contain unresolved template token(s).",
    ),
    "runtime_validation": (
        "RUNTIME_VALIDATION_FAILED",
        "The Dockerfile failed runtime validation (distro / exec form / healthcheck / stage).",
    ),
    "static_validation": (
        "UNRESOLVED_BUILD_CONTEXT",
        "One or more COPY sources cannot be resolved against the build context.",
    ),
}


def _block_reason_and_details(
    failure_kind: str,
    payload: dict[str, Any],
) -> tuple[str, list[str]]:
    """Derive the structured ``reason`` code + human-readable ``details`` list."""
    reason = payload.get("reason") or _BLOCK_REASON.get(failure_kind, (failure_kind.upper(), ""))[0]

    # Prefer the validator's own ``details`` (e.g. ["dockerfile"]); otherwise
    # build a concise list from the issue messages so the UI always has content.
    details = [d for d in (payload.get("details") or []) if d]
    if not details:
        details = [
            str(issue.get("message") or issue.get("artifact") or "").strip()
            for issue in (payload.get("issues") or [])
            if (issue.get("message") or issue.get("artifact"))
        ]
    return reason, details[:20]


def _block_build(
    *,
    db: Session,
    task,
    state: dict,
    failure_kind: str,
    event_type: str,
    payload_key: str,
    payload: dict[str, Any],
    message: str,
) -> JSONResponse:
    """Persist a blocked-build state + return a structured HTTP 422 response.

    The build job is intentionally NOT enqueued. Rather than silently returning
    200 (which made the frontend open a WebSocket against a build that never
    started — the "No active stream" dead state), we respond 422 with a
    structured payload so the UI can render exactly why the build is blocked.
    """
    issue_count = payload.get("issue_count", len(payload.get("issues") or []))
    reason, details = _block_reason_and_details(failure_kind, payload)
    logger.warning(
        "[PrebuildGate] %s BLOCKED build for task=%s reason=%s with %d issue(s) → HTTP 422",
        failure_kind, task.id, reason, issue_count,
    )

    infra_store = state.setdefault("infrastructure", {})
    infra_gen = infra_store.setdefault("infrastructure_generation", {})
    infra_gen[payload_key] = payload
    infra_gen["validation_blocked"] = True
    infra_gen["validation_blocked_kind"] = failure_kind
    state["current_phase"] = "human_review_required"

    execution = state.setdefault("execution", {})
    history = execution.setdefault("history", [])
    history.append({
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "phase": "human_review_required",
        "status": "blocked",
        "message": message,
        "metadata": {
            "failure_kind": failure_kind,
            "reason": reason,
            "issue_count": issue_count,
            "issues": (payload.get("issues") or [])[:5],
        },
    })

    TaskService.save_workflow_state(db, task, state)

    # Mirror the blocked outcome onto the authoritative Workflow.phases_state.
    # Guarded for the unit test, which calls the gate with db=None.
    if db is not None:
        try:
            from backend.app.services.core.workflow_orchestration_service import (
                WorkflowOrchestrationService,
            )
            WorkflowOrchestrationService.record_build_result(
                db, task, status="blocked",
                extra={"failure_kind": failure_kind, "reason": reason},
            )
        except Exception as exc:  # noqa: BLE001 — mirroring must not fail the block
            logger.warning(
                "[Execution] record_build_result (block) failed: %s",
                exc.__class__.__name__,
            )

    return JSONResponse(
        status_code=422,
        content={
            # ── Structured contract (top-level, per spec) ─────────────────────
            "phase": "DOCKER",
            "status": "blocked",
            "reason": reason,
            "details": details,
            # ── Backward-compatible diagnostics ───────────────────────────────
            "blocked": True,
            "failure_kind": failure_kind,
            "message": message,
            "current_phase": "human_review_required",
            "execution_phase": "prebuild_validation",
            "ws_url": f"/ws/execution/{task.id}",
            "task_id": str(task.id),
            "logs": [],
            "image_tag": None,
            payload_key: payload,
        },
    )


def _save_execution_state(db: Session, task, result: DockerBuildResult, is_retry: bool = False) -> None:
    """Persist execution state into workflow_state.execution.docker."""
    task_obj = TaskService.get_task(db, str(task.id))
    if not task_obj:
        return
    state: dict = dict(TaskService.load_workflow_state(db, task_obj) or {})

    execution = state.setdefault("execution", {})
    docker_exec = execution.setdefault("docker", {})

    previous_logs = docker_exec.get("logs", []) if is_retry else []

    new_logs = [e.to_dict() for e in result.logs]
    existing_timestamps = {log.get("timestamp") for log in previous_logs}
    merged_logs = list(previous_logs)
    for log in new_logs:
        if log.get("timestamp") not in existing_timestamps:
            merged_logs.append(log)

    result_dict = result.to_db_dict()
    result_dict["logs"] = merged_logs
    execution["docker"] = result_dict

    docker_exec = execution["docker"]
    docker_exec["retries"] = docker_exec.get("retries", 0)
    docker_exec["build_number"] = docker_exec.get("build_number", 1)

    _wf_status: str | None = None
    if result.status == ExecutionStatus.SUCCESS:
        state["current_phase"] = "docker_build_success"
        _wf_status = "completed"
    elif result.status == ExecutionStatus.FAILED:
        state["current_phase"] = "docker_build_failed"
        _wf_status = "failed"

    logger.info(
        "[Execution] Persisted logs count=%d status=%s task=%s",
        len(merged_logs), result.status, task.id,
    )
    TaskService.save_workflow_state(db, task_obj, state)

    # Single source of truth: mirror the build outcome onto the authoritative
    # Workflow.phases_state. Task.workflow_state is scratch only — without this
    # the Workflow row never learns whether the build passed.
    if _wf_status:
        try:
            from backend.app.services.core.workflow_orchestration_service import (
                WorkflowOrchestrationService,
            )
            WorkflowOrchestrationService.record_build_result(
                db, task_obj, status=_wf_status,
                extra={
                    "build_number": docker_exec.get("build_number", 1),
                    "image_tag": getattr(result, "image_tag", None),
                },
            )
        except Exception as exc:  # noqa: BLE001 — mirroring must not fail the build
            logger.warning(
                "[Execution] record_build_result failed: %s", exc.__class__.__name__,
            )


# ── Background build task ──────────────────────────────────────────────────────

async def _run_build_background(
    task_id: str,
    artifacts: dict[str, str],
    image_tag: str,
    is_retry: bool = False,
    build_number: int = 1,
    build_strategy: dict | None = None,
    repo_source_path: str | None = None,
    execution_session_id: str | None = None,
    repo_url: str | None = None,
    repository_visibility: str = "public",
    github_token: str | None = None,
) -> None:
    """Coroutine that runs the full build lifecycle and persists results."""
    session_id = (
        execution_session_id
        or f"{task_id[:8]}-r{build_number}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    )
    logger.info(
        "[Execution] Build background task started: task=%s build_number=%d session=%s",
        task_id, build_number, session_id,
    )

    # ── Reset the stream's session metadata for this retry iteration ──────────
    # Subscribers connected after this point will replay history but new events
    # will be tagged with the new session_id + retry_iteration.
    stream = log_stream_manager.get_or_create(task_id)
    stream.set_session(retry_iteration=build_number, execution_session_id=session_id)

    if is_retry:
        await emit_execution_event(
            task_id,
            "retry_started",
            message=f"Retry #{build_number}/3 started — streaming fresh execution",
            iteration=build_number,
            max_iterations=3,
            phase="retrying",
            status="running",
            metadata={
                "retry_iteration": build_number,
                "execution_session_id": session_id,
            },
        )
        separator_entry = ExecutionLogEntry(
            level=LogLevel.INFO,
            message=f"========== RETRY BUILD #{build_number} (session={session_id}) ==========",
        )
        await stream.publish(separator_entry)

    executor = DockerExecutor(
        task_id=task_id,
        artifacts=artifacts,
        image_tag=image_tag,
        registry_url=settings.DOCKER_REGISTRY_URL,
        registry_username=settings.DOCKER_REGISTRY_USERNAME,
        registry_password=settings.DOCKER_REGISTRY_PASSWORD,
        push_on_success=settings.DOCKER_PUSH_ON_SUCCESS,
        build_strategy=build_strategy or {},
        finish_stream=False,
        repo_source_path=repo_source_path,
        retry_iteration=build_number,
        execution_session_id=session_id,
        repo_url=repo_url,
        repository_visibility=repository_visibility,
        github_token=github_token,
    )

    result = await executor.build_image()

    db = SessionLocal()
    try:
        task = TaskService.get_task(db, task_id)
        if task:
            _save_execution_state(db, task, result, is_retry=is_retry)
    finally:
        db.close()

    logger.info(
        "[Execution] Stream completed: task=%s status=%s exit_code=%s",
        task_id, result.status, result.exit_code,
    )

    # ── Emit retry_completed / retry_failed terminal event ────────────────────
    terminal_event = "retry_completed" if result.status == ExecutionStatus.SUCCESS else "retry_failed"
    await emit_execution_event(
        task_id,
        terminal_event,
        message=(
            f"Retry #{build_number} {'succeeded' if result.status == ExecutionStatus.SUCCESS else 'failed'}"
        ),
        iteration=build_number,
        max_iterations=3,
        phase=("success" if result.status == ExecutionStatus.SUCCESS else "analyzing_failure"),
        status=("success" if result.status == ExecutionStatus.SUCCESS else "failed"),
        metadata={
            "retry_iteration": build_number,
            "execution_session_id": session_id,
            "exit_code": result.exit_code,
        },
    )

    # ── Corrector hook: trigger analysis on every build failure ───────────────
    if result.status == ExecutionStatus.FAILED:
        await _run_corrector_on_failure(task_id, result)
        await log_stream_manager.finish(task_id)
    else:
        await log_stream_manager.finish(task_id)


# ── POST /api/execution/docker/build/{task_id} ─────────────────────────────────

@router.get("/api/execution/docker/health", response_model=None)
async def docker_health(
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Diagnose Docker daemon connectivity from the backend/worker process.

    Returns the structured :class:`DockerHealth` (reachable, client/server version,
    effective endpoint + transport, and a remediation message when unreachable).
    Use this to tell apart "Docker isn't installed", "daemon not running", and
    "the backend process can't see the daemon (PATH / named-pipe / group)".
    """
    health = await docker_health_check()
    return health.to_dict()


@router.post("/api/execution/docker/build/{task_id}", response_model=None)
async def start_docker_build(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
) -> dict[str, Any] | JSONResponse:
    """Start an async Docker build for the given task.

    Always responds with ONE of two deterministic outcomes:
      * **enqueue success** (200) — a durable build job is enqueued and the WS
        stream will begin; the response carries ``ws_url`` + ``job_id``.
      * **blocked** (422) — pre-build validation failed; the response carries
        ``{phase, status:"blocked", reason, details}`` and NO job is enqueued.

    There is no silent third outcome: a passing gate ALWAYS reaches
    ``JobService.enqueue`` below.
    """
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = TaskService.load_workflow_state(db, task)
    if not state:
        raise HTTPException(status_code=422, detail="No workflow state found for this task")

    current_phase = state.get("current_phase", "")
    if current_phase in _BLOCKED_BUILD_PHASES:
        raise HTTPException(
            status_code=409,
            detail=f"Build already in progress or workflow completed. Current phase: '{current_phase}'",
        )
    if current_phase not in _ALLOWED_BUILD_PHASES:
        raise HTTPException(
            status_code=409,
            detail=f"Expected phase one of {_ALLOWED_BUILD_PHASES}, got '{current_phase}'",
        )

    plan = state.get("plan") or {}
    project_name = (
        plan.get("project_name")
        or plan.get("name")
        or str(task.prompt)[:32]
        or "app"
    )

    artifacts = _extract_docker_artifacts(state)
    if not artifacts.get("dockerfile"):
        raise HTTPException(
            status_code=422,
            detail="No Dockerfile found in task artifacts. Run the Docker phase first.",
        )

    # ── Pre-build validation gate ─────────────────────────────────────────────
    # Re-run template / runtime / COPY-path validation against the LATEST
    # (possibly user-edited) Dockerfile + known_files. If issues remain we refuse
    # to start the build and return a structured HTTP 422 (NOT a silent 200) so
    # the UI can show the user exactly why the build is blocked, instead of
    # burning a retry on a build we already know will fail. When the gate passes,
    # execution falls through to JobService.enqueue below — there is no silent
    # block path.
    gate_failure = _enforce_prebuild_validation_gate(
        db=db, task=task, state=state, artifacts=artifacts,
    )
    if gate_failure is not None:
        return gate_failure

    # Audit: log which artifact versions will be used for this build
    artifact_meta = (state.get("infrastructure") or {}).get("artifacts") or state.get("artifacts") or {}
    for key in artifacts:
        meta = artifact_meta.get(key) or {}
        logger.info(
            "[Execution] Using artifact=%s version=%s modified_by=%s checksum=%s task=%s",
            key,
            meta.get("version", "legacy"),
            meta.get("last_modified_by", "generated"),
            meta.get("checksum", "n/a"),
            task_id,
        )

    image_tag = generate_image_tag(
        project_name=project_name,
        task_id=task_id,
        registry_url=settings.DOCKER_REGISTRY_URL,
        registry_username=settings.DOCKER_REGISTRY_USERNAME,
    )

    execution = state.setdefault("execution", {})
    docker_exec = execution.setdefault("docker", {})

    is_retry = current_phase in ("docker_build_failed", "human_review_required", "corrector_analysis_completed")
    build_number = docker_exec.get("build_number", 0) + 1
    previous_logs = docker_exec.get("logs", []) if is_retry else []

    state["current_phase"] = "docker_build_running"
    execution.update({
        "state": "retrying" if is_retry else "building",
        "active_iteration": build_number,
        "max_iterations": 3,
        "current_message": "Docker build running",
        "last_retry_timestamp": datetime.now(timezone.utc).isoformat() if is_retry else execution.get("last_retry_timestamp"),
    })
    docker_exec.update({
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "image": image_tag,
        "exit_code": None,
        "build_number": build_number,
        "retries": docker_exec.get("retries", 0) + (1 if is_retry else 0),
        "logs": previous_logs,
    })
    TaskService.save_workflow_state(db, task, state)

    # Extract build strategy + cloned repo path for executor tracing.
    infra_state = state.get("infrastructure") or {}
    _build_strategy: dict = (
        (infra_state.get("build_artifact_context") or {}).get("strategy")
        or {}
    )
    # Repository on disk — CodebaseAnalysisAgent stores it at analysis.repo_path,
    # which the orchestrator now propagates into state.repo_path and the
    # docker phase mirrors into state.infrastructure.repo_source_path.
    repo_source_path = (
        infra_state.get("repo_source_path")
        or state.get("repo_path")
        or (state.get("codebase_analysis") or {}).get("repo_path")
        or (state.get("agent_context") or {}).get("repo_path")
    )
    logger.info("[RepoTrace] start_docker_build resolved repo_source_path=%s task=%s", repo_source_path, task_id)

    # ── Re-clone fallback ─────────────────────────────────────────────────────
    # If the persisted path is missing OR no longer exists on disk (OS may have
    # garbage-collected the temp clone, or this task survived a server restart),
    # re-clone from the original repo_url so the build phase is always
    # self-sufficient. Failing here is preferable to a silent repo_mirrored=0.
    #
    # Phase 4 — the GitHub token is NO LONGER read from state. It is fetched
    # from the encrypted credentials store using the task's project_id at
    # the exact moment we need it; never re-persisted. The local
    # ``_runtime_gh_token`` lives only for the duration of this request.
    import os as _os
    from backend.app.services.core.credentials_service import CredentialsService

    _runtime_gh_token: str | None = None
    try:
        _runtime_gh_token = CredentialsService.get_credential(
            db, project_id=task.project_id, provider="github_pat",
        )
    except Exception as exc:
        logger.warning(
            "[Credentials] github_pat fetch failed for project=%s task=%s — "
            "build will proceed without a clone token: %s",
            task.project_id, task_id, exc.__class__.__name__,
        )

    if (not repo_source_path or not _os.path.isdir(repo_source_path)):
        repo_url = state.get("repo_url") or state.get("repository_url")
        if repo_url:
            try:
                from backend.app.services.repository.github_service import GitHubService
                logger.warning(
                    "[RepoTrace] repo_source_path missing or not on disk (%s) — "
                    "re-cloning from %s for task=%s",
                    repo_source_path, repo_url, task_id,
                )
                gh = GitHubService()
                repo_source_path = gh.clone_repository(
                    repo_url=repo_url,
                    repository_visibility=state.get("repository_visibility", "public"),
                    github_token=_runtime_gh_token,
                )
                # Persist the fresh path so subsequent retries reuse it.
                # The save_workflow_state call scrubs any secret keys that
                # the orchestrator may have re-introduced, so this write
                # is safe by construction.
                state.setdefault("infrastructure", {})["repo_source_path"] = repo_source_path
                state["repo_path"] = repo_source_path
                TaskService.save_workflow_state(db, task, state)
                logger.info("[RepoTrace] re-cloned repo to %s task=%s", repo_source_path, task_id)
            except Exception as exc:
                logger.error("[RepoTrace] Re-clone failed for task=%s: %s", task_id, exc)
                repo_source_path = None

    # ── Dockerfile-aware build-context auto-correction ────────────────────────
    # If the persisted strategy says backend_context (sub-directory) but the
    # actual Dockerfile uses repo-root-relative COPY paths AND the file exists
    # at the repo root, the strategy is wrong. Force repo_root_context so the
    # mirror covers the whole repo and docker build sees the right context.
    _build_strategy = _autocorrect_build_strategy(
        strategy=_build_strategy,
        dockerfile=artifacts.get("dockerfile") or "",
        repo_source_path=repo_source_path,
        known_files=infra_state.get("known_files") or [],
        task_id=task_id,
    )

    # Generate a fresh execution session id so the frontend can reset its
    # terminal segment when it sees this new id.
    execution_session_id = (
        f"{task_id[:8]}-r{build_number}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    )

    # Pull repo_url + visibility from state. The token is NOT stored in the
    # job context — the worker's docker_build handler re-fetches it from the
    # encrypted credentials store at run time (Phase 4).
    state_repo_url = state.get("repo_url") or state.get("repository_url")
    state_visibility = state.get("repository_visibility") or "public"

    # Phase 3 — enqueue a DURABLE job instead of asyncio.create_task. The
    # in-process worker claims it and runs the build under the per-project
    # run-lock + heartbeat + crash-recovery machinery. The idempotency key
    # (task + build_number) dedupes a double-click that would otherwise
    # enqueue two identical builds.
    job = JobService.enqueue(
        db,
        project_id=task.project_id,
        workflow_id=task.workflow_id,
        task_id=task_id,
        phase="docker_build",
        idempotency_key=f"docker_build:{task_id}:{build_number}",
        logs_reference="workflow_state.execution.docker.logs",
        execution_context={
            "task_id": task_id,
            "artifacts": artifacts,
            "image_tag": image_tag,
            "is_retry": is_retry,
            "build_number": build_number,
            "build_strategy": _build_strategy,
            "repo_source_path": repo_source_path,
            "execution_session_id": execution_session_id,
            "repo_url": state_repo_url,
            "repository_visibility": state_visibility,
            # NOTE: github_token is deliberately absent — see Phase 4.
        },
    )

    logger.info(
        "[Execution] Docker build job enqueued: job=%s task=%s image=%s build_number=%d session=%s repo=%s",
        job.id, task_id, image_tag, build_number, execution_session_id, repo_source_path,
    )

    return {
        "status": "running",
        "logs": [],
        "image_tag": image_tag,
        "execution_phase": "docker_build",
        "ws_url": f"/ws/execution/{task_id}",
        "task_id": task_id,
        "build_number": build_number,
        "retry_iteration": build_number,
        "execution_session_id": execution_session_id,
        "job_id": job.id,
    }


# ── GET /api/execution/docker/status/{task_id} ─────────────────────────────────

@router.post("/api/tasks/{task_id}/retry-build", response_model=None)
async def retry_docker_build(
    task_id: str,
    db: Session = Depends(get_db),
    gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
) -> dict[str, Any] | JSONResponse:
    """Retry Docker build using the latest saved editable artifacts.

    The gate has already validated project membership; forward the resolved
    tuple to ``start_docker_build`` so the shared handler does not re-check.
    """
    logger.info("[Execution] Retry build requested for task=%s", task_id)
    return await start_docker_build(task_id, db, gate)


@router.get("/api/execution/docker/status/{task_id}")
def get_docker_build_status(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_member),
) -> dict[str, Any]:
    """Return persisted Docker execution state (logs survive page refresh)."""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    state = TaskService.load_workflow_state(db, task) or {}
    execution = state.get("execution", {})
    docker_exec = execution.get("docker", {})

    started_at = docker_exec.get("started_at")
    finished_at = docker_exec.get("finished_at")
    duration_seconds = None
    if started_at and finished_at:
        try:
            start_dt = datetime.fromisoformat(started_at)
            end_dt = datetime.fromisoformat(finished_at)
            duration_seconds = int((end_dt - start_dt).total_seconds())
        except (ValueError, TypeError):
            pass
    elif started_at and docker_exec.get("status") == "running":
        try:
            start_dt = datetime.fromisoformat(started_at)
            duration_seconds = int((datetime.now(timezone.utc) - start_dt).total_seconds())
        except (ValueError, TypeError):
            pass

    logs = docker_exec.get("logs", [])
    logger.info(
        "[Execution] Replay persisted logs: task=%s count=%d status=%s",
        task_id, len(logs), docker_exec.get("status", "pending"),
    )

    return {
        "status": docker_exec.get("status", "pending"),
        "logs": logs,
        "image_tag": docker_exec.get("image"),
        "exit_code": docker_exec.get("exit_code"),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "retries": docker_exec.get("retries", 0),
        "build_number": docker_exec.get("build_number", 0),
        "execution_phase": "docker_build",
        "current_phase": state.get("current_phase", ""),
        "task_id": task_id,
        "failure_reason": docker_exec.get("failure_reason"),
        "docker_command": docker_exec.get("docker_command"),
        "last_error_line": docker_exec.get("last_error_line"),
        "failed_step": docker_exec.get("failed_step"),
    }


# ── WebSocket /ws/execution/{task_id} ──────────────────────────────────────────

async def _ws_authenticate(
    websocket: WebSocket,
    task_id: str,
    token: str | None,
) -> tuple[Task, ProjectMember] | None:
    """Authenticate + authorize a WebSocket handshake against a task.

    Browsers cannot attach custom headers to the WS handshake, so this
    endpoint accepts the access token via the ``?token=`` query string
    instead of the ``Authorization`` header. The token is decoded, the
    user is loaded, and ``resolve_task_membership`` enforces the same
    project-membership gate that the HTTP routes use.

    On failure we close the socket with a meaningful code (1008 = policy
    violation) without ever streaming any log data, then return None so
    the caller can short-circuit.
    """
    if not token:
        await websocket.close(code=1008, reason="missing token")
        return None

    try:
        payload = decode_token(token, expected_type="access")
    except TokenError:
        await websocket.close(code=1008, reason="invalid token")
        return None

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=1008, reason="invalid token")
        return None

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None or not user.is_active_bool:
            await websocket.close(code=1008, reason="account unavailable")
            return None
        try:
            gate = resolve_task_membership(
                db,
                task_id=task_id,
                user=user,
                allowed_roles={"DEVELOPER", "CLOUD_ARCHITECT", "VIEWER"},
            )
        except HTTPException as exc:
            # 404 → log stream is not visible to this caller. 403 → role.
            # Either way the close-code is 1008 (policy violation); we
            # avoid disclosing which one to a foreign caller.
            logger.info(
                "[WS] handshake denied user=%s task=%s status=%s",
                user_id, task_id, exc.status_code,
            )
            await websocket.close(code=1008, reason="forbidden")
            return None
        return gate
    finally:
        db.close()


@router.websocket("/ws/execution/{task_id}")
async def ws_execution_logs(
    websocket: WebSocket,
    task_id: str,
    token: str | None = Query(default=None),
):
    """
    Stream live Docker build logs to the frontend.

    Authentication
    --------------
    The client MUST pass a valid access JWT via the ``?token=`` query
    parameter on the handshake URL. The handshake resolves the task's
    owning project and enforces the same role gate as the HTTP routes
    (DEVELOPER+/VIEWER read). Unauthorized handshakes are closed with
    code 1008 (policy violation) BEFORE any log content is sent.

    Payload format (standardized):
      log entry:  {"type": "log", "timestamp": "...", "level": "INFO", "message": "..."}
      complete:   {"type": "complete", "status": "success|failed", "exit_code": 0}
      error:      {"type": "error", "message": "...", "exit_code": 1}
      heartbeat:  {"type": "pong"}

    Protocol:
      - Reconnect-safe: replays full log history from DB, then streams live.
      - Separate asyncio task handles ping/close messages concurrently so the
        main stream loop is NEVER blocked waiting for client input.
    """
    # Authenticate BEFORE accepting — closing pre-accept doesn't run a
    # close handshake but does refuse the upgrade. We accept first because
    # FastAPI's WebSocket.close() before accept() is awkward across browsers;
    # post-accept close with code 1008 is the cleanest negative signal.
    await websocket.accept()
    gate = await _ws_authenticate(websocket, task_id, token)
    if gate is None:
        return
    logger.info("[WS] Client connected: task_id=%s", task_id)

    # Shared cancellation flag — set by ping-receiver task on disconnect/close
    closed = asyncio.Event()

    async def _ping_receiver() -> None:
        """Background task: handle ping/close from client without blocking log streaming."""
        while not closed.is_set():
            try:
                raw = await websocket.receive_text()
                data = json.loads(raw)
                if data.get("type") == "ping":
                    try:
                        await websocket.send_text(json.dumps({"type": "pong"}))
                    except Exception:
                        closed.set()
                        break
                elif data.get("type") == "close":
                    closed.set()
                    break
            except WebSocketDisconnect:
                closed.set()
                break
            except Exception:
                closed.set()
                break

    async def _send(payload: dict) -> bool:
        """Send a JSON payload; returns False if the connection is gone."""
        if closed.is_set():
            return False
        try:
            await websocket.send_text(json.dumps(payload))
            return True
        except Exception:
            closed.set()
            return False

    try:
        # ── Load persisted state ──────────────────────────────────────────────
        db = SessionLocal()
        try:
            task = TaskService.get_task(db, task_id)
            state = TaskService.load_workflow_state(db, task) if task else {}
            execution = (state or {}).get("execution", {})
            docker_exec = execution.get("docker", {})
            persisted_logs: list[dict] = docker_exec.get("logs", [])
            final_status: str = docker_exec.get("status", "")
        finally:
            db.close()

        logger.info(
            "[WS] Task %s: final_status=%s buffered_logs=%d",
            task_id, final_status or "none", len(persisted_logs),
        )

        # Start ping-receiver concurrently (never blocks the log stream)
        ping_task = asyncio.create_task(_ping_receiver())

        # ── Case 1: Build already finished — replay persisted logs from DB ────
        if final_status in ("success", "failed"):
            logger.info("[WS] Replaying %d persisted logs (build finished)", len(persisted_logs))
            for i, entry in enumerate(persisted_logs):
                if closed.is_set():
                    break
                logger.debug("[WS] Sending persisted log %d/%d", i + 1, len(persisted_logs))
                # Mark every replayed entry so the frontend can render it in
                # the history pane rather than the live retry terminal.
                await _send({**entry, "type": "log", "is_replay": True})

            if not closed.is_set():
                logger.info("[WS] Sending complete event: status=%s", final_status)
                await _send({
                    "type": "complete",
                    "status": final_status,
                    "exit_code": docker_exec.get("exit_code"),
                    "is_replay": True,
                })

            # Keep alive briefly for the client to receive done message
            try:
                await asyncio.wait_for(ping_task, timeout=30.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                ping_task.cancel()
            return

        # ── Case 2: Build running or not yet started ──────────────────────────
        # Send any persisted logs first (previous retry segments), all marked
        # as replay so the frontend keeps them in history and doesn't mix them
        # with live output of the current retry.
        if persisted_logs:
            logger.info("[WS] Sending %d persisted logs before live stream", len(persisted_logs))
            for entry in persisted_logs:
                if closed.is_set():
                    break
                await _send({**entry, "type": "log", "is_replay": True})

        # Wait up to 5 seconds for the stream to be created by the executor
        stream = None
        for attempt in range(20):
            if closed.is_set():
                break
            stream = log_stream_manager.get(task_id)
            if stream is not None:
                logger.info("[WS] Stream found after %d polls for task %s", attempt, task_id)
                break
            await asyncio.sleep(0.25)

        if stream is None or closed.is_set():
            logger.info("[WS] No active stream for task %s, serving info", task_id)
            await _send({"type": "info", "message": "Build not currently running. Reconnect when build starts."})
            ping_task.cancel()
            return

        # ── Stream live logs (no blocking wait between entries) ───────────────
        logger.info("[WS] Starting live log stream: task=%s", task_id)
        log_count = 0
        async for entry in stream.subscribe():
            if closed.is_set():
                break
            entry_dict = entry.to_dict()  # already has type="log" from model
            logger.debug(
                "[WS] Sending live log #%d: level=%s msg=%.60s",
                log_count, entry_dict.get("level"), entry_dict.get("message", ""),
            )
            if not await _send(entry_dict):
                break
            log_count += 1

        logger.info("[WS] Stream finished: task=%s total_lines=%d", task_id, log_count)
        ping_task.cancel()

        if closed.is_set():
            return

        # ── Determine final status from DB and send complete event ────────────
        db2 = SessionLocal()
        try:
            task2 = TaskService.get_task(db2, task_id)
            state2 = TaskService.load_workflow_state(db2, task2) if task2 else {}
            exec2 = (state2 or {}).get("execution", {}).get("docker", {})
            done_status = exec2.get("status", "failed")
            exit_code = exec2.get("exit_code")
        finally:
            db2.close()

        logger.info("[WS] Build complete: task=%s status=%s exit_code=%s", task_id, done_status, exit_code)
        await _send({
            "type": "complete",
            "status": done_status,
            "exit_code": exit_code,
        })

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected: task_id=%s", task_id)
    except Exception as exc:
        logger.exception("[WS] Unexpected error: task_id=%s error=%s", task_id, exc)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(exc), "exit_code": 1}))
        except Exception:
            pass


# ── WebSocket /ws/terraform/{task_id}/{job_phase} ──────────────────────────────

_TF_WS_PHASES = {"terraform_validate", "terraform_plan"}
_TF_JOB_TO_WORKFLOW_PHASE = {
    "terraform_validate": "TERRAFORM_VALIDATION",
    "terraform_plan": "TERRAFORM_PLAN",
}


@router.websocket("/ws/terraform/{task_id}/{job_phase}")
async def ws_terraform_logs(
    websocket: WebSocket,
    task_id: str,
    job_phase: str,
    token: str | None = Query(default=None),
):
    """Stream live Terraform validation / plan logs.

    Reuses the same ``log_stream_manager`` + auth gate + protocol as the Docker
    build socket — this is the SAME streaming system, namespaced by phase so
    Terraform output never collides with Docker build output on a shared task.
    """
    await websocket.accept()
    gate = await _ws_authenticate(websocket, task_id, token)
    if gate is None:
        return
    if job_phase not in _TF_WS_PHASES:
        await websocket.send_text(
            json.dumps({"type": "error", "message": f"unknown phase '{job_phase}'"})
        )
        await websocket.close(code=1008)
        return

    stream_key = f"{task_id}::{job_phase}"
    logger.info("[WS-TF] Client connected: stream=%s", stream_key)

    closed = asyncio.Event()

    async def _ping_receiver() -> None:
        while not closed.is_set():
            try:
                raw = await websocket.receive_text()
                data = json.loads(raw)
                if data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif data.get("type") == "close":
                    closed.set()
                    break
            except (WebSocketDisconnect, Exception):
                closed.set()
                break

    async def _send(payload: dict) -> bool:
        if closed.is_set():
            return False
        try:
            await websocket.send_text(json.dumps(payload))
            return True
        except Exception:
            closed.set()
            return False

    ping_task = asyncio.create_task(_ping_receiver())
    try:
        # Wait briefly for the worker to create the stream after enqueue.
        stream = None
        for _ in range(40):  # up to 10s
            if closed.is_set():
                break
            stream = log_stream_manager.get(stream_key)
            if stream is not None:
                break
            await asyncio.sleep(0.25)

        if stream is None or closed.is_set():
            await _send({
                "type": "info",
                "message": "Terraform phase not currently running. Reconnect when it starts.",
            })
            ping_task.cancel()
            return

        async for entry in stream.subscribe():
            if closed.is_set():
                break
            if not await _send(entry.to_dict()):
                break

        ping_task.cancel()
        if closed.is_set():
            return

        # Determine final status from the persisted phase result.
        wf_phase = _TF_JOB_TO_WORKFLOW_PHASE[job_phase]
        db2 = SessionLocal()
        try:
            task2 = TaskService.get_task(db2, task_id)
            state2 = TaskService.load_workflow_state(db2, task2) if task2 else {}
            result = ((state2 or {}).get("terraform_pipeline") or {}).get(wf_phase) or {}
        finally:
            db2.close()
        ok = bool(result.get("ok"))
        await _send({
            "type": "complete",
            "status": "success" if ok else "failed",
            "exit_code": 0 if ok else 1,
        })
    except WebSocketDisconnect:
        logger.info("[WS-TF] Client disconnected: stream=%s", stream_key)
    except Exception as exc:
        logger.exception("[WS-TF] Unexpected error stream=%s: %s", stream_key, exc)
        try:
            await websocket.send_text(
                json.dumps({"type": "error", "message": str(exc), "exit_code": 1})
            )
        except Exception:
            pass
    finally:
        ping_task.cancel()


# ── Corrector orchestration hook ───────────────────────────────────────────────

async def _run_corrector_on_failure(
    task_id: str,
    build_result: DockerBuildResult,
) -> None:
    """
    Trigger corrector analysis after a Docker build failure.

    State transitions driven by this function:
      docker_build_failed
        → corrector_analysis_running   (immediately)
        → human_review_required        (retry budget remaining)
        → execution_failed             (retry_count >= max_retries)

    Retry lifecycle:
      retry_count is incremented each time a build fails and corrector runs.
      When retry_count reaches max_retries, the workflow moves to execution_failed
      so no further automatic or manual retries are allowed without operator intervention.
    """
    logger.info("[Corrector] Starting analysis for task=%s", task_id)

    # ── Step 1: Read current state, increment retry_count, set phase ──────────
    db = SessionLocal()
    retry_count: int = 0
    max_retries: int = 3
    artifacts: dict = {}

    try:
        task = TaskService.get_task(db, task_id)
        if not task:
            logger.warning("[Corrector] Task not found: task=%s", task_id)
            return

        state: dict = dict(TaskService.load_workflow_state(db, task) or {})
        execution = state.setdefault("execution", {})
        corrector: dict = execution.setdefault("corrector", {})

        retry_count = corrector.get("retry_count", 0) + 1
        max_retries = corrector.get("max_retries", 3)

        corrector.update({
            "status": "running",
            "retry_count": retry_count,
            "max_retries": max_retries,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
        })
        state["current_phase"] = "corrector_analysis_running"
        TaskService.save_workflow_state(db, task, state)
        artifacts = _extract_docker_artifacts(state)
    finally:
        db.close()

    logger.info(
        "[Corrector] Retry count=%d/%d for task=%s",
        retry_count, max_retries, task_id,
    )
    await emit_execution_event(
        task_id,
        "corrector_analysis",
        message=f"Corrector analyzing Docker build failure ({retry_count}/{max_retries})",
        iteration=retry_count,
        max_iterations=max_retries,
        phase="analyzing_failure",
        status="running",
    )

    # ── Step 2: Reconstruct log text from DockerBuildResult ───────────────────
    raw_logs = "\n".join(entry.message for entry in build_result.logs)

    # ── Step 3: Run corrector analysis ────────────────────────────────────────
    try:
        from backend.app.services.corrector.docker_corrector import DockerCorrectorAgent
        from backend.app.services.llm.provider_factory import ProviderFactory

        try:
            # GPT-5-mini primary → Groq fallback (single call). See
            # AGENT_PROVIDER_MAP["DockerCorrectorAgent"]. Drop-in for the old
            # Groq-only LLMService — identical chat_json signature, same budget.
            llm = ProviderFactory.for_agent("DockerCorrectorAgent")
        except Exception as llm_exc:
            llm = None
            logger.warning(
                "[Corrector] LLM unavailable — using deterministic analysis only: %s",
                llm_exc,
            )

        # Enrich corrector context with repository build context for phase-8 diagnosis
        infra_state_for_corrector = state.get("infrastructure") or {}
        repo_build_ctx_for_corrector = infra_state_for_corrector.get("repository_build_context") or {}
        build_artifact_ctx_for_corrector = infra_state_for_corrector.get("build_artifact_context") or {}
        static_val_for_corrector = (
            (infra_state_for_corrector.get("infrastructure_generation") or {})
            .get("static_validation") or {}
        )

        agent = DockerCorrectorAgent(llm_service=llm)
        await emit_execution_event(
            task_id,
            "generating_patch",
            message="GPT-5-mini generating remediation patch preview",
            iteration=retry_count,
            max_iterations=max_retries,
            phase="generating_patch",
            status="running",
        )
        analysis = await agent.analyze(
            raw_logs=raw_logs,
            artifacts=artifacts,
            context={
                "task_id": task_id,
                "exit_code": build_result.exit_code,
                "failed_step": build_result.failed_step,
                "build_number": retry_count,
                "repository_build_context": repo_build_ctx_for_corrector,
                "build_artifact_context": build_artifact_ctx_for_corrector,
                "static_validation": static_val_for_corrector,
            },
        )

    except Exception as exc:
        logger.exception(
            "[Corrector] Analysis failed for task=%s: %s", task_id, exc
        )
        analysis = None

    # ── Step 4: Persist result and advance workflow phase ─────────────────────
    db2 = SessionLocal()
    try:
        task2 = TaskService.get_task(db2, task_id)
        if not task2:
            return

        state2: dict = dict(TaskService.load_workflow_state(db2, task2) or {})
        execution2 = state2.setdefault("execution", {})
        corrector2: dict = execution2.get("corrector", {})

        if analysis is not None:
            analysis_dict = analysis.to_dict()
            fixes = analysis_dict.get("fixes") or []
            structured_patches = analysis_dict.get("structured_patches") or []
            await emit_execution_event(
                task_id,
                "patch_generated",
                message=f"Corrector generated {len(fixes)} fix suggestion(s)",
                iteration=retry_count,
                max_iterations=max_retries,
                phase="generating_patch",
                status="completed",
                metadata={
                    "fix_count": len(fixes),
                    "structured_patch_count": len(structured_patches),
                    "root_cause": analysis_dict.get("root_cause"),
                },
            )
            corrector2.update({
                "status": "completed",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "analysis": analysis_dict,
                "error": None,
            })
        else:
            await emit_execution_event(
                task_id,
                "execution_failed",
                message="Corrector analysis failed unexpectedly.",
                iteration=retry_count,
                max_iterations=max_retries,
                phase="failed",
                status="failed",
            )
            corrector2.update({
                "status": "error",
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": "Corrector analysis failed unexpectedly.",
            })

        execution2["corrector"] = corrector2

        if retry_count >= max_retries:
            state2["current_phase"] = "execution_failed"
            await emit_execution_event(
                task_id,
                "max_retries_reached",
                message=f"Maximum retry budget reached ({retry_count}/{max_retries})",
                iteration=retry_count,
                max_iterations=max_retries,
                phase="max_retries_reached",
                status="failed",
            )
            logger.warning(
                "[Corrector] Max retries exceeded: task=%s %d/%d → execution_failed",
                task_id, retry_count, max_retries,
            )
        else:
            state2["current_phase"] = "human_review_required"
            await emit_execution_event(
                task_id,
                "corrector_analysis",
                message="Corrector analysis completed. Human review required before retry.",
                iteration=retry_count,
                max_iterations=max_retries,
                phase="human_review_required",
                status="completed",
            )
            logger.info(
                "[Corrector] Analysis complete: task=%s retry=%d/%d → human_review_required",
                task_id, retry_count, max_retries,
            )

        latest_state_for_history = TaskService.load_workflow_state(db2, task2) or {}
        latest_execution = (latest_state_for_history.get("execution") or {})
        execution2["history"] = latest_execution.get("history", execution2.get("history", []))
        for key in (
            "state",
            "state_machine",
            "active_iteration",
            "max_iterations",
            "current_message",
            "current_phase_label",
            "last_event_at",
        ):
            if key in latest_execution:
                execution2[key] = latest_execution[key]

        TaskService.save_workflow_state(db2, task2, state2)
        if analysis is not None:
            ArtifactService.store_ai_patch_suggestions(db2, task2, analysis_dict)
    finally:
        db2.close()
