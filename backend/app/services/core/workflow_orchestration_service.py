"""WorkflowOrchestrationService.

Glue layer that wraps the existing ``OrchestratorAgent`` phase methods with
DB persistence: creates ``Workflow`` rows, threads execution through the
existing ``Task.workflow_state`` JSONB (so the legacy router keeps working),
and after every phase persists generated artifacts via
``ArtifactPersistenceService``.

The orchestrator itself is NOT modified. This service composes around it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.agents.orchestrator_agent import OrchestratorAgent
from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.services.core.artifact_persistence_service import ArtifactPersistenceService
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.core.project_context_service import ProjectContextService
from backend.app.services.core.task_service import TaskService

logger = logging.getLogger(__name__)


# Phase name → key used in ``Workflow.phases_state``.
PHASE_DOCKER = "DOCKER"
PHASE_TERRAFORM = "TERRAFORM"
PHASE_KUBERNETES = "KUBERNETES"
PHASE_CICD = "CICD"

# Infrastructure Lifecycle phases — template-driven MVP pipeline
# (``TerraformPipelineService``), independent of the LLM/MCP ``PHASE_TERRAFORM``
# above. Designed as standalone phases so a future DAG executor can schedule
# them in parallel with CI/CD or security analysis.
PHASE_TF_GENERATION = "TERRAFORM_GENERATION"
PHASE_TF_VALIDATION = "TERRAFORM_VALIDATION"
PHASE_TF_PLAN = "TERRAFORM_PLAN"

_TF_PIPELINE_PHASES = {PHASE_TF_GENERATION, PHASE_TF_VALIDATION, PHASE_TF_PLAN}

# Deployment orchestration phase — renders a GitHub Actions deploy workflow from
# the validated Docker + Terraform artifacts + the architecture decision. Runs
# INLINE (template render, no external process), like TERRAFORM_GENERATION.
PHASE_GH_ACTIONS = "GITHUB_ACTIONS_GENERATION"

# Repository installation phase — commits the generated bootstrap.yml + deploy.yml
# onto a DEDICATED branch of the user's repository and (best-effort) opens a PR.
# Runs INLINE (clone → write → commit → push).
PHASE_REPO_INSTALL = "REPOSITORY_INSTALLATION"

# Workflow monitoring phase — READ-ONLY observation of the installed pipelines'
# GitHub Actions runs (Generate → Install → Monitor). It does NOT run inline:
# there is no orchestration work here. Installation success simply ADVANCES the
# lifecycle into this phase so the run resumes onto the monitoring surface, which
# queries GitHub live on demand (see WorkflowMonitoringService). The workflow
# stays terminal (``completed``) — monitoring is post-completion observation.
PHASE_WORKFLOW_MONITORING = "WORKFLOW_MONITORING"

# Infrastructure Destroy phase — generates + installs + dispatches a destroy.yml
# GitHub Actions workflow that runs ``terraform destroy``. The backend NEVER runs
# Terraform: GitHub Actions is the execution engine. Inline (render → commit →
# dispatch), reusing the repository-installation + workflow-dispatch machinery.
PHASE_INFRA_DESTROY = "INFRASTRUCTURE_DESTROY"

# Workflow statuses that are TERMINAL — a project may create a new workflow once
# its current one reaches any of these. Everything else (pending, running,
# awaiting_input) is "active", and a project may have at most ONE active workflow
# at a time. Historical (terminal) workflows are never touched by this rule.
# ``blocked`` is terminal: a security-blocked repo cannot proceed, so the run is
# done — but the user can fix the repo and start a FRESH workflow that re-analyses.
TERMINAL_WORKFLOW_STATUSES = {"completed", "failed", "cancelled", "blocked"}

# Phase → durable job phase string consumed by the worker handler registry.
_TF_JOB_PHASE = {
    PHASE_TF_VALIDATION: "terraform_validate",
    PHASE_TF_PLAN: "terraform_plan",
}
# Inverse: durable job phase → workflow phase. Used by the lifecycle reconciler
# to map a terminal terraform JOB back onto its workflow phase.
_WF_PHASE_BY_JOB = {job: wf for wf, job in _TF_JOB_PHASE.items()}
# phases_state statuses that mean a TF phase has SETTLED — the reconciler never
# overwrites one of these (the in-handler finaliser already had the last word).
_TF_SETTLED_STATUSES = {
    "completed", "completed_with_fallback", "completed_no_files",
    "failed", "cancelled",
}


def terraform_stream_key(task_id: str, job_phase: str) -> str:
    """Namespaced ``log_stream_manager`` key for a Terraform phase.

    Keying per (task, phase) keeps Terraform validation/plan output isolated
    from Docker build output (which streams on the bare ``task_id``) so they
    never interleave on the shared stream manager.
    """
    return f"{task_id}::{job_phase}"


class WorkflowOrchestrationService:
    # ─── Workflow lifecycle ──────────────────────────────────────────────────

    @staticmethod
    def get_active_workflow(db: Session, project_id: str) -> Optional[Workflow]:
        """Return the project's single ACTIVE (non-terminal) workflow, if any.

        "Active" = status not in :data:`TERMINAL_WORKFLOW_STATUSES`. If more than
        one exists (e.g. duplicates created before this guard shipped), the most
        recently created one is returned so callers converge on a single run.
        """
        return (
            db.query(Workflow)
            .filter(
                Workflow.project_id == project_id,
                Workflow.status.notin_(TERMINAL_WORKFLOW_STATUSES),
            )
            .order_by(Workflow.created_at.desc())
            .first()
        )

    @staticmethod
    def get_or_create_workflow(
        db: Session,
        *,
        project: Project,
        user: User,
        prompt: str,
        execution_mode: str = "full",
    ) -> Tuple[Workflow, Task, dict]:
        """Single-active-workflow entry point used by BOTH creation paths.

        Enforces "one project = one active workflow": if the project already has
        an active (non-terminal) workflow with a backing task, that workflow is
        returned as-is (no second run is started, no architecture-decision is
        re-run). Otherwise a fresh workflow is created via
        :meth:`start_workflow`.

        Both the project-creation bootstrap and the explicit
        ``POST /projects/{id}/workflows`` endpoint funnel through here, which is
        what prevents the duplicate-workflow bug (bootstrap + API each creating
        one). Terminal workflows do not block creation, so a completed/failed/
        cancelled run is preserved and the next call starts a new workflow.
        """
        existing = WorkflowOrchestrationService.get_active_workflow(db, project.id)
        if existing is not None:
            task = WorkflowOrchestrationService.get_backing_task(db, existing)
            if task is not None:
                state = TaskService.load_workflow_state(db, task) or {}
                logger.info(
                    "[Workflow] reusing active workflow=%s for project=%s "
                    "(status=%s) — not creating a duplicate",
                    existing.id, project.id, existing.status,
                )
                return existing, task, state
            # An active workflow with no backing task is a degenerate/broken row
            # that callers cannot use. Fall through and create a usable one.
            logger.warning(
                "[Workflow] active workflow=%s for project=%s has no backing task "
                "— creating a fresh workflow",
                existing.id, project.id,
            )

        return WorkflowOrchestrationService.start_workflow(
            db,
            project=project,
            user=user,
            prompt=prompt,
            execution_mode=execution_mode,
        )

    @staticmethod
    def start_workflow(
        db: Session,
        *,
        project: Project,
        user: User,
        prompt: str,
        execution_mode: str = "full",
        force_reanalysis: bool = False,
    ) -> Tuple[Workflow, Task, dict]:
        """Begin a new workflow run for a project.

        Runs the architecture-decision phase (analysis + planning + cost) and
        pauses for user plan selection. Creates both a ``Workflow`` row and a
        backing ``Task`` row (the orchestrator persists state on the Task,
        which we keep so the legacy ``/workflow/*`` router can also resume it).

        ``force_reanalysis`` is threaded into the codebase-analysis agent so the
        repository-analysis cache is bypassed (used by :meth:`reanalyze`).
        """
        workflow = Workflow(
            project_id=project.id,
            started_by=user.id,
            current_phase="ARCHITECTURE_DECISION",
            status="running",
            execution_mode=execution_mode,
            phases_state={},
            logs=[],
        )
        db.add(workflow)
        db.flush()

        # Phase 1 — Task.project_id is NOT NULL. The Task is created already
        # linked to the project + workflow; the previous pattern of inserting
        # and then patching the FK in is no longer possible.
        task = TaskService.create_task(
            db, prompt, project_id=project.id, workflow_id=workflow.id,
        )
        TaskService.update_task_status(db, task, "in_progress")

        state = WorkflowOrchestrationService._execute_architecture_decision(
            db,
            project=project,
            workflow=workflow,
            task=task,
            prompt=prompt,
            force_reanalysis=force_reanalysis,
        )

        db.commit()
        db.refresh(workflow)
        db.refresh(task)
        return workflow, task, state

    @staticmethod
    def _execute_architecture_decision(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Task,
        prompt: str,
        force_reanalysis: bool = False,
    ) -> dict:
        """Run the architecture-decision phase and persist its outcome.

        Shared by :meth:`start_workflow` (fresh run) and :meth:`reanalyze`
        (in-place re-run on the existing workflow). Runs the codebase analysis
        (``force_reanalysis`` bypasses the repository-analysis cache), records
        the resulting phase on ``workflow``, saves the state onto ``task``, and
        captures the analysis digests into ProjectContext — all WITHOUT
        committing, so the caller owns the transaction boundary.
        """
        # Phase 4 — pull the GitHub PAT (if any) from the encrypted store
        # at request time and pass it directly into the agent call. The
        # token is never written to ``state`` here, and the orchestrator's
        # own writes are scrubbed by ``TaskService._sanitize_for_json``.
        gh_token = None
        try:
            gh_token = CredentialsService.get_credential(
                db, project_id=project.id, provider="github_pat",
            )
        except Exception as exc:
            logger.warning(
                "[Credentials] github_pat fetch failed for project=%s — "
                "architecture-decision will run without a token: %s",
                project.id, exc.__class__.__name__,
            )

        orchestrator = OrchestratorAgent()
        state = orchestrator.run_architecture_decision_phase(
            prompt=prompt,
            repo_url=project.repository_url or None,
            repository_visibility="public",
            github_token=gh_token,
            force_reanalysis=force_reanalysis,
        )

        # A security-blocked repo never produces architecture strategies. It must
        # NOT be advertised as ``ARCHITECTURE_DECISION / awaiting_input`` — the UI
        # resolves that phase to the planning surface, fetches the (non-existent)
        # architecture-decision, and 404s. Mark it BLOCKED at the ANALYSIS phase
        # instead (terminal): the analysis surface is the right home for the
        # security findings, and a fresh workflow can be started after a fix.
        security_blocked = (
            state.get("status") == "blocked"
            or (state.get("repository_security") or {}).get("status") == "blocked"
        )

        if security_blocked:
            TaskService.save_workflow_state(db, task, state)
            TaskService.update_task_status(db, task, "blocked")
            blocked_reasons = (state.get("repository_security") or {}).get("blocked_reasons") or []
            WorkflowOrchestrationService._record_phase(
                workflow,
                phase="ANALYSIS",
                status="blocked",
                extra={"task_id": task.id, "blocked_reasons": blocked_reasons},
            )
            workflow.current_phase = "ANALYSIS"
            workflow.status = "blocked"
            capture_phase = "ANALYSIS"
            logger.info(
                "[Workflow] workflow=%s project=%s BLOCKED by security gate — "
                "marked terminal at ANALYSIS (reasons=%d)",
                workflow.id, project.id, len(blocked_reasons),
            )
        else:
            TaskService.save_plan_awaiting_validation(db, task, state)
            WorkflowOrchestrationService._record_phase(
                workflow,
                phase="ARCHITECTURE_DECISION",
                status="awaiting_input",
                extra={"task_id": task.id},
            )
            workflow.current_phase = "ARCHITECTURE_DECISION"
            workflow.status = "awaiting_input"
            capture_phase = "ARCHITECTURE_DECISION"

        # Capture analysis (+ architecture-decision) digests into ProjectContext.
        # Done before commit so it lands in the same transaction as the workflow row.
        ProjectContextService.capture_from_state(
            db,
            project_id=project.id,
            state=state,
            phase=capture_phase,
            generated_by="OrchestratorAgent",
        )
        return state

    @staticmethod
    def reanalyze(
        db: Session,
        *,
        project: Project,
        user: User,
        prompt: str,
    ) -> Tuple[Workflow, Task, dict]:
        """Force a fresh codebase re-analysis for a project.

        Unlike :meth:`get_or_create_workflow` — which REUSES an active workflow
        and never re-runs analysis — this ALWAYS re-invokes the codebase-analysis
        LLM (bypassing the repository-analysis cache) and overwrites the persisted
        ProjectContext digests.

        Respects the one-active-workflow invariant: it re-runs analysis IN PLACE
        on the project's existing active workflow (resetting its phase state so
        the stale downstream phases are re-run against the new analysis). When no
        active workflow exists (e.g. the previous run is terminal), it starts a
        fresh one with the cache bypass enabled.
        """
        workflow = WorkflowOrchestrationService.get_active_workflow(db, project.id)
        task = (
            WorkflowOrchestrationService.get_backing_task(db, workflow)
            if workflow is not None
            else None
        )

        if workflow is None or task is None:
            return WorkflowOrchestrationService.start_workflow(
                db,
                project=project,
                user=user,
                prompt=prompt,
                force_reanalysis=True,
            )

        # Re-run in place on the existing active workflow. Reset the phase state
        # so downstream phases (docker/terraform/…) produced from the OLD analysis
        # are cleared — they must be re-run against the freshly analyzed repo.
        TaskService.update_task_status(db, task, "in_progress")
        workflow.phases_state = {}
        workflow.status = "running"
        workflow.finished_at = None

        state = WorkflowOrchestrationService._execute_architecture_decision(
            db,
            project=project,
            workflow=workflow,
            task=task,
            prompt=prompt,
            force_reanalysis=True,
        )

        db.commit()
        db.refresh(workflow)
        db.refresh(task)
        logger.info(
            "[Workflow] project=%s workflow=%s RE-ANALYZED in place (phase=%s status=%s)",
            project.id, workflow.id, workflow.current_phase, workflow.status,
        )
        return workflow, task, state

    @staticmethod
    def select_plan(
        db: Session,
        *,
        workflow: Workflow,
        task: Task,
        plan_id: str,
    ) -> dict:
        # Phase 4 — re-hydrate runtime-only secrets before passing state
        # to the orchestrator. The post-call save_workflow_state strips
        # them back out before persistence.
        state = TaskService.load_workflow_state(db, task) or {}
        state = CredentialsService.hydrate_state(db, state, project_id=workflow.project_id)
        orchestrator = OrchestratorAgent()
        state = orchestrator.resume_with_selected_plan(prior_state=state, selected_plan_id=plan_id)
        TaskService.save_workflow_state(db, task, state)

        WorkflowOrchestrationService._record_phase(
            workflow,
            phase="PLAN_SELECTED",
            status="completed",
            extra={"plan_id": plan_id},
        )
        workflow.current_phase = "PLAN_SELECTED"
        workflow.status = "running"

        # Persist the chosen plan + cost into ProjectContext so future reruns
        # and recommendation surfaces can replay without recomputing.
        ProjectContextService.capture_from_state(
            db,
            project_id=workflow.project_id,
            state=state,
            phase="PLAN_SELECTED",
            generated_by="OrchestratorAgent",
        )

        db.commit()
        db.refresh(workflow)
        return state

    # ─── Phase execution ─────────────────────────────────────────────────────

    @staticmethod
    def run_phase(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Task,
        phase: str,
    ) -> Tuple[dict, List[str]]:
        """Run a single phase of the canonical workflow.

        Canonical workflow:
            ANALYSIS → INFRASTRUCTURE (terraform gen → validate → plan) → DOCKER.

        The only LLM agent phase reachable here is DOCKER. Terraform
        generation/validation/plan run through the dedicated pipeline path
        (``_run_terraform_pipeline_phase``). CI/CD and Kubernetes are
        deactivated — they are not part of the supported workflow.

        Every phase is ATOMIC + IDEMPOTENT + retry-safe:
          1. updates ``Workflow.phases_state`` (the single source of truth),
          2. persists generated artifacts to the DB,
          3. writes the orchestrator scratch state,
        all in ONE transaction — a throw rolls the whole phase back. Re-running
        a phase does not duplicate artifacts (upserts dedupe by content hash;
        phase records are last-writer overwrites).

        Returns ``(state, persisted_artifact_ids)``.
        """
        phase_upper = phase.upper()

        # Hard prerequisite gate — phases must run in dependency order.
        WorkflowOrchestrationService._enforce_prerequisites(workflow, phase_upper)

        # Infrastructure Lifecycle phases run through the dedicated pipeline path
        # (LLM generation → DB → rehydrate → durable validate/plan jobs).
        if phase_upper in _TF_PIPELINE_PHASES:
            return WorkflowOrchestrationService._run_terraform_pipeline_phase(
                db, project=project, workflow=workflow, task=task,
                phase=phase_upper,
            )

        # Deployment orchestration — consumes the validated artifacts (no LLM
        # generation, no infra execution), so it runs inline like TF generation.
        if phase_upper == PHASE_GH_ACTIONS:
            return WorkflowOrchestrationService._run_github_actions_generation(
                db, project=project, workflow=workflow, task=task,
            )

        # Repository installation — commits the generated workflows to the repo.
        # Inline (clone → write → commit → push), like the deployment phase.
        if phase_upper == PHASE_REPO_INSTALL:
            return WorkflowOrchestrationService._run_repository_installation(
                db, project=project, workflow=workflow, task=task,
            )

        # Infrastructure destroy — generate destroy.yml → install → dispatch.
        # Inline + GitHub-Actions-executed (no terraform runs in the backend).
        if phase_upper == PHASE_INFRA_DESTROY:
            from backend.app.services.infrastructure_destroy import (
                InfrastructureDestroyService,
            )

            return InfrastructureDestroyService.run(
                db, project=project, workflow=workflow, task=task,
            )

        if phase_upper != PHASE_DOCKER:
            raise ValueError(
                f"Phase '{phase}' is not supported. Valid phases: DOCKER, "
                "TERRAFORM_GENERATION, TERRAFORM_VALIDATION, TERRAFORM_PLAN, "
                "GITHUB_ACTIONS_GENERATION, REPOSITORY_INSTALLATION, "
                "INFRASTRUCTURE_DESTROY."
            )

        prior_state = TaskService.load_workflow_state(db, task) or {}
        # Phase 4 — re-hydrate runtime-only secrets. Stays in memory for
        # this request only; never re-persisted.
        prior_state = CredentialsService.hydrate_state(
            db, prior_state, project_id=project.id,
        )
        orchestrator = OrchestratorAgent()
        agent_name = "InfrastructureAgent"

        state = orchestrator.run_docker_phase(prior_state)
        # Fold the build-critical setup that used to live only in the legacy
        # /workflow run-docker endpoint so the canonical surface produces the
        # same build-ready state (repo_source_path, known_files, editable
        # artifact layer, build-context mirror).
        state = WorkflowOrchestrationService._prepare_docker_build_state(state)

        # ── Atomic phase commit: scratch + artifacts + phase record together ──
        TaskService.stage_workflow_state(task, state)
        artifacts = ArtifactPersistenceService.persist_state_artifacts(
            db,
            project_id=project.id,
            workflow_id=workflow.id,
            state=state,
            generated_by_agent=agent_name,
            commit=False,
        )

        phase_succeeded = not str(state.get("current_phase", "")).endswith("_failed")
        phase_status = "completed" if phase_succeeded else "failed"
        phase_extra: dict = {
            "artifact_count": len(artifacts),
            "current_phase": state.get("current_phase"),
        }
        # DOCKER phase-completion contract: it never fails on LLM problems, but
        # it may complete via deterministic fallback. Surface that distinction.
        docker_meta = state.get("docker_phase") or {}
        phase_extra["used_llm"] = docker_meta.get("used_llm", True)
        phase_extra["fallback_used"] = docker_meta.get("fallback_used", False)
        phase_extra["generation_mode"] = docker_meta.get("generation_mode", "llm")
        if phase_succeeded and docker_meta.get("status") == "completed_with_fallback":
            phase_status = "completed_with_fallback"

        WorkflowOrchestrationService._record_phase(
            workflow, phase=PHASE_DOCKER, status=phase_status, extra=phase_extra,
        )
        workflow.current_phase = PHASE_DOCKER
        workflow.status = "running"

        if state.get("result"):
            task.result = state["result"]
        if state.get("plan"):
            task.plan = state["plan"]

        db.commit()
        db.refresh(workflow)

        # Derived ProjectContext digests are non-critical — capture in a
        # separate best-effort transaction so a digest failure cannot roll back
        # the (already committed) phase.
        WorkflowOrchestrationService._capture_context_best_effort(
            db, project_id=project.id, state=state, phase=PHASE_DOCKER,
            generated_by=agent_name,
        )

        return state, [a.id for a in artifacts]

    # ─── Phase helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _enforce_prerequisites(workflow: Workflow, phase_upper: str) -> None:
        """Reject a phase whose dependency phases have not completed.

        Reads the authoritative ``Workflow.phases_state``. Raises ``ValueError``
        (surfaced as HTTP 400) on an out-of-order request.
        """
        phases = workflow.phases_state or {}

        def _is_completed(name: str) -> bool:
            status = (phases.get(name) or {}).get("status")
            return status in ("completed", "completed_with_fallback", "completed_no_files")

        plan_selected = "PLAN_SELECTED" in phases

        if phase_upper in (PHASE_DOCKER, PHASE_TF_GENERATION):
            if not plan_selected:
                raise ValueError(
                    f"Cannot run {phase_upper}: a plan must be selected first "
                    "(PLAN_SELECTED)."
                )
        elif phase_upper in (PHASE_TF_VALIDATION, PHASE_TF_PLAN):
            if not _is_completed(PHASE_TF_GENERATION):
                raise ValueError(
                    f"Cannot run {phase_upper}: run TERRAFORM_GENERATION first."
                )
        elif phase_upper == PHASE_GH_ACTIONS:
            # The deploy workflow consumes the Docker + Terraform artifacts and
            # the selected architecture decision — all three must be in place.
            if not plan_selected:
                raise ValueError(
                    f"Cannot run {PHASE_GH_ACTIONS}: a plan must be selected first "
                    "(PLAN_SELECTED)."
                )
            if not _is_completed(PHASE_DOCKER):
                raise ValueError(
                    f"Cannot run {PHASE_GH_ACTIONS}: run DOCKER generation first."
                )
            if not _is_completed(PHASE_TF_GENERATION):
                raise ValueError(
                    f"Cannot run {PHASE_GH_ACTIONS}: run TERRAFORM_GENERATION first."
                )
        elif phase_upper == PHASE_REPO_INSTALL:
            # Installation needs the generated pipelines — the deployment phase
            # must have completed (which guarantees bootstrap.yml + deploy.yml
            # exist and validated). The service re-checks the artifacts + token
            # before touching the repository.
            if not _is_completed(PHASE_GH_ACTIONS):
                raise ValueError(
                    f"Cannot run {PHASE_REPO_INSTALL}: run "
                    f"{PHASE_GH_ACTIONS} first to generate bootstrap.yml + deploy.yml."
                )
        elif phase_upper == PHASE_INFRA_DESTROY:
            # Destroy targets the infrastructure the installed pipelines created,
            # so the pipelines must have been installed (REPOSITORY_INSTALLATION
            # completed — which also guarantees terraform/ + repo + token exist).
            # The service re-checks repo + token + terraform before touching the
            # repository, mirroring the installation phase.
            if not _is_completed(PHASE_REPO_INSTALL):
                raise ValueError(
                    f"Cannot run {PHASE_INFRA_DESTROY}: install the pipelines first "
                    f"({PHASE_REPO_INSTALL}). There is no provisioned infrastructure "
                    "to destroy yet."
                )

    @staticmethod
    def _prepare_docker_build_state(state: dict) -> dict:
        """Mirror Docker-agent outputs into the canonical infrastructure store.

        Ported from the (removed) legacy ``/workflow`` run-docker endpoint so
        the project surface yields the same build-ready state: the editable
        artifact layer, the BuildStrategyDetector context, ``known_files`` for
        the pre-build gate, and ``repo_source_path`` for the DockerExecutor.
        """
        from backend.app.services.core.artifact_service import ArtifactService

        generated = dict((state.get("infra") or {}).get("artifacts") or {})
        state = ArtifactService.initialize_from_state(state, generated)

        infra_agent_response = state.get("infra") or {}
        infra_store = state.setdefault("infrastructure", {})
        for key in (
            "repository_build_context",
            "build_artifact_context",
            "topology_summary",
            "infrastructure_generation",
        ):
            value = infra_agent_response.get(key)
            if value is not None:
                infra_store[key] = value

        agent_ctx = (state.get("agent_context") or {}).get("infrastructure_context") or {}
        known_files = agent_ctx.get("known_files")
        if known_files:
            infra_store["known_files"] = list(known_files)

        repo_source_path = (
            state.get("repo_path")
            or (state.get("agent_context") or {}).get("repo_path")
        )
        if repo_source_path:
            infra_store["repo_source_path"] = repo_source_path

        return state

    @staticmethod
    def _capture_context_best_effort(
        db: Session,
        *,
        project_id: str,
        state: dict,
        phase: str,
        generated_by: str,
    ) -> None:
        try:
            ProjectContextService.capture_from_state(
                db, project_id=project_id, state=state, phase=phase,
                generated_by=generated_by,
            )
        except Exception as exc:  # noqa: BLE001 — context capture is non-critical
            logger.warning(
                "[ProjectContext] capture failed for phase=%s: %s",
                phase, exc.__class__.__name__,
            )
            db.rollback()

    @staticmethod
    def record_build_result(
        db: Session,
        task: Task,
        *,
        status: str,
        extra: Optional[dict] = None,
    ) -> Optional[Workflow]:
        """Reflect a Docker BUILD outcome on the authoritative phase record.

        The build runs on the Task-scoped execution surface; this mirrors its
        terminal outcome onto the owning ``Workflow.phases_state`` so phase
        truth lives in exactly ONE place. ``status`` is one of
        ``completed`` | ``failed`` | ``blocked``. A successful build is the
        workflow's terminal state (the canonical workflow ends at DOCKER build).
        """
        workflow_id = getattr(task, "workflow_id", None)
        if not workflow_id:
            return None
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow is None:
            return None

        WorkflowOrchestrationService._record_phase(
            workflow, phase="DOCKER_BUILD", status=status, extra=extra or {},
        )
        workflow.current_phase = "DOCKER_BUILD"
        if status == "completed":
            workflow.status = "completed"
            workflow.finished_at = datetime.now(timezone.utc)
        elif status in ("failed", "blocked"):
            # The run is not done — a fix + rebuild can still complete it.
            workflow.status = "running"
        db.commit()
        return workflow

    # ─── Deployment orchestration (GitHub Actions) ───────────────────────────

    @staticmethod
    def _run_github_actions_generation(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Task,
    ) -> Tuple[dict, List[str]]:
        """Generate the ``.github/workflows/deploy.yml`` deploy workflow.

        Consumes the validated Docker + Terraform artifacts and the selected
        architecture decision (deployment target derived from the blueprint —
        never asked). Pipeline: build context → select template → render →
        optional LLM enrichment → YAML validation. The artifact is persisted
        ONLY when validation passes; an invalid workflow records a ``failed``
        phase with the errors (no artifact), mirroring TERRAFORM_GENERATION's
        non-raising failure contract so the UI can surface it cleanly.

        Atomic: artifact upsert + phase record + scratch state commit together.
        A successful generation is the terminal artifact of the generation
        pipeline, so the workflow is marked ``completed``.
        """
        from backend.app.services.core.artifact_persistence_service import (
            ArtifactPersistenceService as _APS,
        )
        from backend.app.services.github_actions_generation.deployment_context_builder import (
            DeploymentContextNotReady,
        )
        from backend.app.services.github_actions_generation.generation_service import (
            GitHubActionsGenerationService,
        )

        try:
            result = GitHubActionsGenerationService.generate(
                db, project=project, workflow=workflow, task=task,
            )
        except DeploymentContextNotReady as exc:
            # Prerequisite-shaped failure (missing upstream artifacts) → 400.
            raise ValueError(str(exc)) from exc

        ctx = result.deployment_context
        persisted_ids: List[str] = []
        pipelines_meta: List[dict] = []

        # FIX 3 — Architecture consistency guard. The deploy/bootstrap templates
        # are keyed on the deployment target (compute.type) while Terraform is
        # keyed on architecture_style; before persisting anything, verify the
        # Terraform artifacts actually declare the compute resource this target
        # assumes. A mismatch would install a pipeline that can only fail at run
        # time, so fail GITHUB_ACTIONS_GENERATION and persist no artifacts.
        from backend.app.services.github_actions_generation.architecture_consistency import (
            verify_architecture_consistency,
            verify_resource_name_consistency,
        )

        terraform_files = _APS.get_terraform_files(db, project_id=project.id)
        consistency = verify_architecture_consistency(
            ctx.deployment_target, terraform_files
        )
        if not consistency.consistent:
            return WorkflowOrchestrationService._fail_github_actions_inconsistent(
                db,
                project=project,
                workflow=workflow,
                task=task,
                ctx=ctx,
                consistency=consistency,
                logs=result.logs,
            )

        # FIX 3b — resource-NAME consistency. The presence guard above proves the
        # compute resource exists; this proves the rendered pipelines reference the
        # SAME literal identifiers Terraform declares (the ECR repo / cluster /
        # service / function / region). A divergence — e.g. a deploy.yml using
        # ECR_REPOSITORY=tp-devops while Terraform created a differently-named
        # repository — would install a pipeline that can only fail at run time, so
        # fail GITHUB_ACTIONS_GENERATION and persist no artifacts.
        name_consistency = verify_resource_name_consistency(
            deployment_target=ctx.deployment_target,
            terraform_files=terraform_files,
            pipeline_files=[(f.name, f.content) for f in result.files],
        )
        if not name_consistency.consistent:
            return WorkflowOrchestrationService._fail_github_actions_inconsistent(
                db,
                project=project,
                workflow=workflow,
                task=task,
                ctx=ctx,
                consistency=name_consistency,
                logs=result.logs,
            )

        # Persist each file that individually validated (Phase 5 contract). The
        # artifact_type stays "github_actions"; the two files are distinguished by
        # artifact_subtype (their on-disk path) — no new artifact type, no migration.
        for f in result.files:
            if f.valid:
                artifact = _APS.upsert_artifact(
                    db,
                    project_id=project.id,
                    workflow_id=workflow.id,
                    artifact_type="github_actions",
                    artifact_subtype=f.path,
                    content=f.content,
                    generated_by_agent="GitHubActionsGenerationService",
                    validation_status="passed",
                    # Running this phase is an explicit (re)generation. The
                    # renderer is deterministic, so a rerun re-emits identical
                    # bytes; force a new ArtifactVersion anyway so every
                    # regenerate is auditable history instead of a silent no-op
                    # that reuses a stale artifact.
                    force_new_version=True,
                )
                persisted_ids.append(artifact.id)
            pipelines_meta.append({
                "name": f.name,
                "kind": f.kind,
                "path": f.path,
                "template": f.template,
                "validation_status": f.validation.status,
                "validation_errors": f.validation.errors,
                "enrichment_applied": f.enrichment_applied,
                "persisted": f.valid,
            })

        # The phase completes only when BOTH files validated; otherwise the run
        # stays open so it can be re-run after a fix (any valid file is still saved).
        status = "completed" if result.valid else "failed"
        enrichment_applied = any(f.enrichment_applied for f in result.files)

        WorkflowOrchestrationService._record_phase(
            workflow,
            phase=PHASE_GH_ACTIONS,
            status=status,
            extra={
                "deployment_target": ctx.deployment_target,
                "pipelines": pipelines_meta,
                "artifact_count": len(persisted_ids),
                "enrichment_applied": enrichment_applied,
                "docker_artifacts": ctx.docker_artifacts,
                "terraform_artifacts": ctx.terraform_artifacts,
                # Back-compat scalar mirrors of the delivery (deploy) file.
                "template": result.deploy.template,
                "workflow_path": result.deploy.path,
                "validation_status": result.deploy.validation.status,
                "validation_errors": result.deploy.validation.errors,
            },
        )
        workflow.current_phase = PHASE_GH_ACTIONS
        if status == "completed":
            workflow.status = "completed"
            workflow.finished_at = datetime.now(timezone.utc)
        else:
            # Keep the run open so the phase can be re-run after a fix.
            workflow.status = "running"

        # Mirror the result into scratch state so the phase-run response + the
        # read projection can render the generated workflows without a re-run.
        state = TaskService.load_workflow_state(db, task) or {}
        gh_state = state.setdefault("github_actions", {})
        gh_state.update({
            "deployment_target": ctx.deployment_target,
            "deployment_context": ctx.model_dump(),
            "enrichment_applied": enrichment_applied,
            "pipelines": [
                {
                    "name": f.name,
                    "kind": f.kind,
                    "path": f.path,
                    "template": f.template,
                    "content": f.content,
                    "validation": {
                        "status": f.validation.status,
                        "errors": f.validation.errors,
                        "warnings": f.validation.warnings,
                    },
                    "enrichment_applied": f.enrichment_applied,
                }
                for f in result.files
            ],
            # Back-compat scalar mirrors of the delivery (deploy) file.
            "template": result.deploy.template,
            "workflow_path": result.deploy.path,
            "content": result.deploy.content,
            "validation": {
                "status": result.deploy.validation.status,
                "errors": result.deploy.validation.errors,
                "warnings": result.deploy.validation.warnings,
            },
        })
        state["logs"] = list(state.get("logs", [])) + result.logs
        TaskService.stage_workflow_state(task, state)

        db.commit()
        db.refresh(workflow)

        logger.info(
            "[GitHubActions] generation complete project=%s target=%s status=%s "
            "artifacts=%d",
            project.id, ctx.deployment_target, status, len(persisted_ids),
        )
        return state, persisted_ids

    @staticmethod
    def _fail_github_actions_inconsistent(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Task,
        ctx,
        consistency,
        logs: List[dict],
    ) -> Tuple[dict, List[str]]:
        """Record GITHUB_ACTIONS_GENERATION as failed on an architecture mismatch.

        FIX 3 — persists NO workflow artifacts: the deploy/bootstrap pipelines
        assume a compute resource the Terraform never provisions, so installing
        them would only fail at run time. The run stays open (``running``) so the
        phase can be re-run after Terraform is regenerated for the target.
        """
        errors = list(consistency.errors)
        consistency_record = {
            "consistent": False,
            "deployment_target": consistency.deployment_target,
            "required_resource": consistency.required_resource,
            "errors": errors,
        }

        WorkflowOrchestrationService._record_phase(
            workflow,
            phase=PHASE_GH_ACTIONS,
            status="failed",
            extra={
                "deployment_target": ctx.deployment_target,
                "architecture_consistency": consistency_record,
                "artifact_count": 0,
                "validation_status": "failed",
                "validation_errors": errors,
            },
        )
        workflow.current_phase = PHASE_GH_ACTIONS
        workflow.status = "running"  # keep open so it can be re-run after a fix

        state = TaskService.load_workflow_state(db, task) or {}
        gh_state = state.setdefault("github_actions", {})
        gh_state.update({
            "deployment_target": ctx.deployment_target,
            "architecture_consistency": consistency_record,
            "validation": {"status": "failed", "errors": errors, "warnings": []},
        })
        state["logs"] = list(state.get("logs", [])) + list(logs) + [
            {"step": "github_actions", "message": m} for m in errors
        ]
        TaskService.stage_workflow_state(task, state)

        db.commit()
        db.refresh(workflow)

        logger.warning(
            "[GitHubActions] architecture inconsistency project=%s target=%s: %s",
            project.id, ctx.deployment_target, "; ".join(errors),
        )
        return state, []

    # ─── Repository installation (commit workflows to the repo) ──────────────

    @staticmethod
    def _resolve_default_branch(project: Project) -> str:
        """Resolve the project's base (default) branch.

        Persisted in ``Project.project_metadata['default_branch']`` (no schema
        migration — JSONB free-form), defaulting to ``main`` when unset. The
        installation phase writes the resolved value back after a successful run
        so it is remembered for next time.
        """
        meta = project.project_metadata or {}
        branch = str(meta.get("default_branch") or "").strip()
        return branch or "main"

    @staticmethod
    def _dispatch_bootstrap(
        *,
        repo_url: str,
        github_token: str,
        ref: str,
    ) -> dict:
        """FIX 1 — trigger bootstrap.yml via workflow_dispatch. Never raises.

        Returns a compact record ``{dispatched, run_id, ref, workflow_file,
        status_code, error}`` for the installation phase + artifact. Any failure
        (bad repo URL, permission, 404 because bootstrap.yml is not yet on the
        default branch, network) degrades to ``dispatched=False`` with a reason —
        the install itself already succeeded.
        """
        from pathlib import Path

        from backend.app.services.repository.github_service import GitHubService
        from backend.app.services.repository_installation.models import BOOTSTRAP_PATH
        from backend.app.services.repository_installation.workflow_dispatch_client import (
            dispatch_workflow,
        )

        workflow_file = Path(BOOTSTRAP_PATH).name  # "bootstrap.yml"

        try:
            owner, repo = GitHubService._extract_owner_and_repo(repo_url)
        except ValueError as exc:
            return {
                "dispatched": False,
                "run_id": None,
                "ref": ref,
                "workflow_file": workflow_file,
                "status_code": None,
                "error": str(exc),
            }

        outcome = dispatch_workflow(
            owner=owner,
            repo=repo,
            token=github_token,
            workflow_file=workflow_file,
            ref=ref,
        )
        return outcome.to_record(ref=ref, workflow_file=workflow_file)

    @staticmethod
    def _run_repository_installation(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Task,
    ) -> Tuple[dict, List[str]]:
        """Install the generated ``bootstrap.yml`` + ``deploy.yml`` into the repo.

        Reads the DB-backed (validated) GitHub Actions artifacts, the project's
        repository URL, and the encrypted ``github_pat`` credential, then delegates
        to :class:`RepositoryInstallationService` (clone → dedicated branch →
        write → commit → push → optional PR). The service NEVER pushes to a
        protected branch and NEVER force-pushes.

        Missing/unsafe preconditions raise ``ValueError`` (→ HTTP 400). An
        operational git/PR failure is recorded as a ``failed`` phase WITHOUT
        raising (the workflow stays open to retry), mirroring the non-raising
        failure contract of the Terraform / Docker phases. On success the run is
        the terminal artifact of the lifecycle, so the workflow is ``completed``.
        """
        import json as _json

        from backend.app.services.core.artifact_persistence_service import (
            ArtifactPersistenceService as _APS,
        )
        from backend.app.services.repository_installation.installation_service import (
            RepositoryInstallationService,
        )
        from backend.app.services.repository_installation.installation_files import (
            DOCKERFILE_PATH,
            TERRAFORM_DIR,
            build_installation_files,
        )
        from backend.app.services.repository_installation.models import (
            BOOTSTRAP_PATH,
            DEPLOY_PATH,
            InstallationPrerequisiteError,
        )

        # 1. Gather the generated workflows from the DB (source of truth — the
        #    exact validated bytes the deployment phase persisted).
        gh_files = _APS.get_github_actions_files(db, project_id=project.id)
        bootstrap = gh_files.get(BOOTSTRAP_PATH)
        deploy = gh_files.get(DEPLOY_PATH)
        if not bootstrap or not deploy:
            raise ValueError(
                f"Cannot run {PHASE_REPO_INSTALL}: both bootstrap.yml and "
                "deploy.yml must be generated first (run "
                f"{PHASE_GH_ACTIONS})."
            )

        # 1b. Gather the artifacts the pipelines CONSUME and assemble the runnable
        #     file set: the two pipelines + terraform/*.tf(vars) + Dockerfile. The
        #     allow-list is the ONLY place install paths are decided, so no
        #     arbitrary file is ever written. Guard on the BUILT set so a missing
        #     consumed artifact fails loudly here rather than installing a repo
        #     whose pipelines break at run time (e.g. "No such file: terraform/").
        terraform_files = _APS.get_terraform_files(db, project_id=project.id)
        docker_files = _APS.get_docker_artifacts(db, project_id=project.id)
        files = build_installation_files(
            bootstrap=bootstrap,
            deploy=deploy,
            terraform_files=terraform_files,
            docker_files=docker_files,
        )
        if not any(p.startswith(f"{TERRAFORM_DIR}/") for p in files):
            raise ValueError(
                f"Cannot run {PHASE_REPO_INSTALL}: no Terraform artifacts found "
                "— bootstrap.yml needs terraform/ to run 'terraform init'. Run "
                "Terraform Generation first."
            )
        if DOCKERFILE_PATH not in files:
            raise ValueError(
                f"Cannot run {PHASE_REPO_INSTALL}: no Dockerfile artifact found "
                "— the pipelines build from Dockerfile. Run Docker Generation "
                "first."
            )

        repo_url = project.repository_url
        if not repo_url:
            raise ValueError(
                f"Cannot run {PHASE_REPO_INSTALL}: the project has no "
                "repository URL."
            )

        # 2. Pull the GitHub PAT at the moment it is needed — never persisted to
        #    state, decrypted in-memory for this request only.
        github_token = CredentialsService.get_credential(
            db, project_id=project.id, provider="github_pat",
        )
        if not github_token:
            raise ValueError(
                f"Cannot run {PHASE_REPO_INSTALL}: a GitHub token "
                "(github_pat credential) is required to push to the repository."
            )

        base_branch = WorkflowOrchestrationService._resolve_default_branch(project)

        try:
            result = RepositoryInstallationService.install(
                repo_url=repo_url,
                github_token=github_token,
                files=files,
                base_branch=base_branch,
                create_pr=True,
            )
        except InstallationPrerequisiteError as exc:
            # Caller-fixable precondition → 400 (matches the GH-Actions phase).
            raise ValueError(str(exc)) from exc

        status = "completed" if result.success else "failed"
        persisted_ids: List[str] = []

        # FIX 1 — After a successful installation, automatically trigger the
        # Infrastructure pipeline (bootstrap.yml) via the GitHub Actions
        # workflow_dispatch API so infrastructure is provisioned (terraform
        # apply) before the Delivery pipeline runs. Best-effort + non-fatal: a
        # dispatch failure never fails the install. No new credential system
        # (reuses the github_pat above), no polling, no waiting.
        bootstrap_dispatch = (
            WorkflowOrchestrationService._dispatch_bootstrap(
                repo_url=repo_url,
                github_token=github_token,
                ref=result.install_branch,
            )
            if result.success
            else None
        )

        WorkflowOrchestrationService._record_phase(
            workflow,
            phase=PHASE_REPO_INSTALL,
            status=status,
            extra={
                "branch": result.install_branch,
                "base_branch": result.base_branch,
                "commit": result.commit_sha,
                "pr_url": result.pr_url,
                "pr_created": result.pr_created,
                "pr_skipped_reason": result.pr_skipped_reason,
                "pushed": result.pushed,
                "committed": result.committed,
                "no_changes": result.no_changes,
                "files": result.files_written,
                "repo_url": result.repo_url,
                "error": result.error,
                "bootstrap_dispatch": bootstrap_dispatch,
            },
        )
        workflow.current_phase = PHASE_REPO_INSTALL
        if result.success:
            workflow.status = "completed"
            workflow.finished_at = datetime.now(timezone.utc)
            # Remember the resolved base branch for future runs.
            meta = dict(project.project_metadata or {})
            if meta.get("default_branch") != result.base_branch:
                meta["default_branch"] = result.base_branch
                project.project_metadata = meta
            # Durable installation record (survives scratch loss). Carries the
            # FIX 1 bootstrap dispatch outcome alongside the install result.
            installation_record = result.to_artifact_dict()
            installation_record["bootstrap_dispatch"] = bootstrap_dispatch
            artifact = _APS.upsert_artifact(
                db,
                project_id=project.id,
                workflow_id=workflow.id,
                artifact_type="repository_installation",
                artifact_subtype="installation.json",
                content=_json.dumps(installation_record, indent=2, default=str),
                generated_by_agent="RepositoryInstallationService",
                validation_status="passed",
            )
            persisted_ids.append(artifact.id)

            # Advance the lifecycle into observation: Generate → Install →
            # Monitor. The REPOSITORY_INSTALLATION entry stays ``completed`` (its
            # status is unchanged), and the workflow stays terminal
            # (``completed``) — this only points ``current_phase`` at the
            # monitoring surface so a resumed run lands there. No GitHub call
            # happens here; monitoring queries live on demand.
            WorkflowOrchestrationService._record_phase(
                workflow,
                phase=PHASE_WORKFLOW_MONITORING,
                status="monitoring",
                extra={"note": "GitHub Actions runs can now be monitored."},
            )
            workflow.current_phase = PHASE_WORKFLOW_MONITORING
        else:
            # Keep the run open so the phase can be re-run after a fix.
            workflow.status = "running"

        # Mirror the outcome into scratch state for the read projection.
        state = TaskService.load_workflow_state(db, task) or {}
        ri_state = state.setdefault("repository_installation", {})
        ri_state.update({
            "success": result.success,
            "branch": result.install_branch,
            "base_branch": result.base_branch,
            "commit": result.commit_sha,
            "pr_url": result.pr_url,
            "pr_created": result.pr_created,
            "pr_skipped_reason": result.pr_skipped_reason,
            "pushed": result.pushed,
            "committed": result.committed,
            "no_changes": result.no_changes,
            "files": result.files_written,
            "repo_url": result.repo_url,
            "error": result.error,
            "bootstrap_dispatch": bootstrap_dispatch,
        })
        state["logs"] = list(state.get("logs", [])) + [
            {"step": "repository_installation", "message": m} for m in result.logs
        ]
        TaskService.stage_workflow_state(task, state)

        db.commit()
        db.refresh(workflow)

        logger.info(
            "[RepoInstall] project=%s status=%s branch=%s commit=%s pr=%s",
            project.id, status, result.install_branch, result.commit_sha,
            result.pr_url or result.pr_skipped_reason,
        )
        return state, persisted_ids

    # ─── Infrastructure Lifecycle (Terraform MVP pipeline) ───────────────────

    @staticmethod
    def _run_terraform_pipeline_phase(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Task,
        phase: str,
    ) -> Tuple[dict, List[str]]:
        """Dispatch one Infrastructure Lifecycle phase.

        * GENERATION runs inline (fast template render → persist artifacts).
        * VALIDATION / PLAN enqueue a durable job that streams terraform logs
          over the WebSocket and finalises the phase on completion. They
          return immediately with the phase marked ``running``.
        """
        if phase == PHASE_TF_GENERATION:
            return WorkflowOrchestrationService._run_terraform_generation(
                db, project=project, workflow=workflow, task=task,
            )
        return WorkflowOrchestrationService._enqueue_terraform_job(
            db, project=project, workflow=workflow, task=task, phase=phase,
        )

    @staticmethod
    def _run_terraform_generation(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Task,
    ) -> Tuple[dict, List[str]]:
        """Unified Terraform generation: LLM → Artifact DB → rehydrate to disk.

        There is now ONE terraform engine. The LLM ``TerraformAgent`` produces
        the HCL, it is persisted to the DB artifact store (the source of truth),
        then rehydrated onto disk under ``generated_terraform/<artifact_id>/``
        so the durable validate/plan jobs run ``terraform`` against the *real
        generated* artifact — not a separately regenerated template.
        """
        from backend.app.services.core.artifact_persistence_service import (
            classify_artifact,
            extract_artifacts_from_state,
        )
        from backend.app.services.terraform_pipeline import TerraformPipelineService

        prior_state = TaskService.load_workflow_state(db, task) or {}
        prior_state = CredentialsService.hydrate_state(
            db, prior_state, project_id=project.id,
        )

        orchestrator = OrchestratorAgent()
        # project.id keys the per-project S3 remote state so bootstrap + destroy
        # share one persistent, isolated state object.
        state = orchestrator.run_terraform_phase_only(
            prior_state, task_id=task.id, project_id=project.id,
        )

        current = str(state.get("current_phase") or "")
        # ``current_phase`` is a WEAK signal here: the orchestrator's success /
        # degraded path inherits it from prior_state and does NOT reset it, so a
        # genuine FIRST-attempt failure (e.g. the old TemplateSelectionError)
        # leaves a stale ``terraform_failed`` that a later successful re-run
        # carries forward. We therefore treat the PRESENCE OF GENERATED HCL as
        # authoritative for the phase outcome (see STEP 3) and only consult this
        # flag when no HCL was produced at all.
        render_failed = (current == "terraform_failed")
        validation_status = state.get("terraform_validation_status")
        failure_classification = state.get("terraform_failure_classification")

        # STEP 1 — persist EVERY generated artifact to the DB FIRST. This runs
        # unconditionally: artifact creation is never gated on terraform init /
        # validate success. The .tf files land as `terraform` rows inside the
        # atomic phase transaction (source of truth).
        artifacts = ArtifactPersistenceService.persist_state_artifacts(
            db,
            project_id=project.id,
            workflow_id=workflow.id,
            state=state,
            generated_by_agent="TerraformAgent",
            commit=False,
        )

        # Collect the terraform files for the disk rehydration step.
        all_files = extract_artifacts_from_state(state)
        tf_files = {
            fn: content
            for fn, content in all_files.items()
            if isinstance(content, str) and classify_artifact(fn) == "terraform"
        }

        # STEP 2 — attempt rehydration to disk whenever HCL exists, REGARDLESS of
        # validation outcome. Disk durability is decoupled from init success so a
        # registry outage cannot leave validate/plan without a directory to run
        # against (the DB already has the canonical copy as a fallback).
        artifact_id: Optional[str] = None
        if tf_files:
            artifact_id = uuid.uuid4().hex[:12]
            try:
                TerraformPipelineService().rehydrate(
                    artifact_id,
                    tf_files,
                    metadata={
                        "source": "TerraformAgent",
                        "project_id": project.id,
                        "workflow_id": workflow.id,
                        "files": sorted(tf_files),
                        "validation_status": validation_status,
                        "failure_classification": failure_classification,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as exc:  # noqa: BLE001 — disk sync is best-effort
                # The DB copy is authoritative; the worker re-rehydrates from DB
                # before validate/plan. A disk-write failure must not lose the
                # artifacts or fail the phase.
                logger.warning(
                    "[TerraformPipeline] rehydrate to disk failed (DB copy intact): %s",
                    exc,
                )

        # Stash the pipeline artifact id so validate/plan can locate the dir.
        tf_state = state.setdefault("terraform_pipeline", {})
        if artifact_id:
            tf_state["artifact_id"] = artifact_id
            tf_state["files"] = sorted(tf_files)
        TaskService.stage_workflow_state(task, state)

        # STEP 3 — phase status. The PRESENCE OF GENERATED HCL is authoritative:
        # a run that produced .tf files is `completed` REGARDLESS of the
        # validation verdict (degraded OR failed) AND regardless of any stale
        # ``terraform_failed`` a previous attempt may have left on
        # ``current_phase``. The dedicated TERRAFORM_VALIDATION phase owns the
        # validation pass/fail. Only a run that produced NO usable HCL via a
        # genuine generation/contract failure is `failed`; a run where terraform
        # was simply not requested is `completed_no_files`.
        if tf_files:
            status = "completed"
        elif render_failed:
            status = "failed"
        else:
            # Generation ran but produced no terraform files (e.g. the plan did
            # not request terraform). Not an error — there is just nothing to
            # validate/plan.
            status = "completed_no_files"

        WorkflowOrchestrationService._record_phase(
            workflow,
            phase=PHASE_TF_GENERATION,
            status=status,
            extra={
                "artifact_id": artifact_id,
                "artifact_count": len(artifacts),
                "file_count": len(tf_files),
                "current_phase": current,
                "validation_status": validation_status,
                "failure_classification": failure_classification,
            },
        )
        workflow.current_phase = PHASE_TF_GENERATION
        workflow.status = "running"
        db.commit()
        db.refresh(workflow)

        WorkflowOrchestrationService._capture_context_best_effort(
            db, project_id=project.id, state=state, phase="TERRAFORM",
            generated_by="TerraformAgent",
        )

        logger.info(
            "[TerraformPipeline] generation complete project=%s artifact=%s files=%d "
            "status=%s validation=%s classification=%s",
            project.id, artifact_id, len(tf_files), status,
            validation_status, failure_classification,
        )
        return state, [a.id for a in artifacts]

    @staticmethod
    def _enqueue_terraform_job(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Task,
        phase: str,
    ) -> Tuple[dict, List[str]]:
        from backend.app.services.execution.job_service import JobService

        state = TaskService.load_workflow_state(db, task) or {}
        tf_state = state.get("terraform_pipeline") or {}
        artifact_id = tf_state.get("artifact_id")
        if not artifact_id:
            raise ValueError(
                f"Cannot run {phase}: no Terraform artifact found. "
                "Run TERRAFORM_GENERATION first."
            )

        job_phase = _TF_JOB_PHASE[phase]
        stream_key = terraform_stream_key(task.id, job_phase)

        job = JobService.enqueue(
            db,
            project_id=project.id,
            workflow_id=workflow.id,
            task_id=task.id,
            phase=job_phase,
            # No retries: a terraform-logic failure (bad config / missing creds)
            # is deterministic, so re-running wastes the per-project run-lock.
            max_retries=0,
            idempotency_key=f"{job_phase}:{artifact_id}",
            execution_context={
                "artifact_id": artifact_id,
                "task_id": task.id,
                "workflow_id": workflow.id,
                "phase": phase,
                "stream_key": stream_key,
            },
        )

        WorkflowOrchestrationService._record_phase(
            workflow,
            phase=phase,
            status="running",
            extra={
                "artifact_id": artifact_id,
                "job_id": job.id,
                "stream_key": stream_key,
            },
        )
        workflow.current_phase = phase
        workflow.status = "running"
        db.commit()
        db.refresh(workflow)

        logger.info(
            "[TerraformPipeline] %s enqueued job=%s artifact=%s stream=%s",
            phase, job.id, artifact_id, stream_key,
        )
        return state, []

    @staticmethod
    def record_terraform_phase_cancelled(
        db: Session,
        *,
        workflow_id: Optional[str],
        task_id: Optional[str],
        phase: str,
    ) -> None:
        """Mark a streamed Terraform phase as cancelled (Phase 3A).

        Called from the job handler's ``CancelledError`` path: the phase was
        stopped by an operator before validate/plan finished, so
        ``record_terraform_phase_result`` never runs and ``phases_state`` would
        otherwise stay ``running`` forever. Writes a ``cancelled`` status while
        PRESERVING the ``artifact_id`` / ``job_id`` / ``stream_key`` already on the
        phase entry (so the UI can still find the job and offer Replay), and keeps
        the workflow ``running`` so the phase can be re-run / replayed. Best-effort.
        """
        if workflow_id:
            workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
            if workflow is not None:
                prior = (workflow.phases_state or {}).get(phase) or {}
                preserved = {
                    k: prior.get(k)
                    for k in ("artifact_id", "job_id", "stream_key")
                    if prior.get(k) is not None
                }
                WorkflowOrchestrationService._record_phase(
                    workflow,
                    phase=phase,
                    status="cancelled",
                    extra={**preserved, "ok": False, "cancelled": True},
                )
                workflow.current_phase = phase
                workflow.status = "running"
                db.commit()

        if task_id:
            task = TaskService.get_task(db, task_id)
            if task is not None:
                state = TaskService.load_workflow_state(db, task) or {}
                tf_state = state.setdefault("terraform_pipeline", {})
                tf_state[phase] = {"ok": False, "cancelled": True, "results": []}
                TaskService.save_workflow_state(db, task, state)

    @staticmethod
    def reconcile_phase_for_terminal_job(
        db: Session,
        *,
        job,
        terminal_status: str,
    ) -> None:
        """Reflect a terminal durable Terraform JOB onto ``Workflow.phases_state``.

        The in-handler finaliser (``record_terraform_phase_result`` on a normal
        exit, ``record_terraform_phase_cancelled`` on an operator stop) is the
        usual writer of a TF phase's terminal status. But that code only runs if
        the handler coroutine actually reaches it. When the handler never does —
        the worker process was lost (uvicorn ``--reload`` in dev), the job was
        reaped after its heartbeat went stale, or it raised before recording —
        the phase would otherwise stay ``running`` forever, which strands the UI
        (reconnect storm), blocks Replay, and never emits a WS ``complete`` frame.

        This maps the job's terminal state (``cancelled`` / ``failed``) back onto
        its workflow phase, but ONLY while that phase is still ``running`` so it
        can never clobber a status the handler already wrote (fully idempotent —
        the worker-alive cancel path runs the handler's own finaliser first, and
        this is then a no-op). Terraform phases only for now; Docker has its own
        in-handler persistence (``_persist_docker_cancelled``) and can be folded
        in here later. Best-effort: callers wrap it so a reconcile failure never
        breaks the job's own terminal transition.
        """
        if job is None or getattr(job, "phase", None) not in _WF_PHASE_BY_JOB:
            return
        ctx = job.execution_context or {}
        wf_phase = ctx.get("phase") or _WF_PHASE_BY_JOB[job.phase]
        workflow_id = job.workflow_id or ctx.get("workflow_id")
        task_id = job.task_id or ctx.get("task_id")
        if not workflow_id:
            return

        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow is None:
            return
        current = ((workflow.phases_state or {}).get(wf_phase) or {}).get("status")
        if current in _TF_SETTLED_STATUSES:
            # The handler already settled this phase — leave its verdict intact.
            return

        if terminal_status == "cancelled":
            # Reuse the tested cancelled-persistence path (preserves
            # artifact_id/job_id/stream_key for Replay; keeps workflow running).
            WorkflowOrchestrationService.record_terraform_phase_cancelled(
                db, workflow_id=workflow_id, task_id=task_id, phase=wf_phase,
            )
            logger.warning(
                "[TerraformPipeline] reconciled orphaned phase %s → cancelled "
                "(job=%s never ran its in-handler finaliser)",
                wf_phase, getattr(job, "id", "?"),
            )
            return

        # terminal_status == "failed": the job died/was reaped with no real
        # terraform verdict. Record a failed phase (preserving the Replay
        # pointers) and keep the workflow running so it can be re-run / replayed.
        prior = (workflow.phases_state or {}).get(wf_phase) or {}
        preserved = {
            k: prior.get(k)
            for k in ("artifact_id", "job_id", "stream_key")
            if prior.get(k) is not None
        }
        reason = (
            "worker stopped before the phase finished (orphaned/reaped) — "
            "re-run or replay to retry"
        )
        WorkflowOrchestrationService._record_phase(
            workflow,
            phase=wf_phase,
            status="failed",
            extra={**preserved, "ok": False, "error": reason},
        )
        workflow.current_phase = wf_phase
        workflow.status = "running"
        db.commit()
        logger.warning(
            "[TerraformPipeline] reconciled orphaned phase %s → failed (job=%s): %s",
            wf_phase, getattr(job, "id", "?"), reason,
        )

        if task_id:
            task = TaskService.get_task(db, task_id)
            if task is not None:
                state = TaskService.load_workflow_state(db, task) or {}
                tf_state = state.setdefault("terraform_pipeline", {})
                tf_state[wf_phase] = {"ok": False, "results": [], "error": reason}
                TaskService.save_workflow_state(db, task, state)

    @staticmethod
    def record_terraform_phase_result(
        db: Session,
        *,
        workflow_id: Optional[str],
        task_id: Optional[str],
        project_id: str,
        phase: str,
        ok: bool,
        results: List[dict],
        artifact_id: Optional[str] = None,
        error: Optional[str] = None,
        failure_classification: Optional[str] = None,
        plan_json: Optional[str] = None,
        infrastructure_summary: Optional[dict] = None,
    ) -> None:
        """Worker-side finaliser for a streamed Terraform phase.

        Called from the job handler after validation/plan completes. Persists
        the outcome into ``Workflow.phases_state`` and the backing Task's
        workflow_state, and upserts the relevant DB artifacts:

        * validation → a ``validation_report`` artifact.
        * plan (on success) → the raw ``plan.json`` (``terraform show -json``)
          plus a derived ``infrastructure_summary.json`` (categorized resource
          counts). The categorized summary is also embedded into the
          ``TERRAFORM_PLAN`` phase entry so the UI can render the Infrastructure
          Summary card without a second fetch. The binary ``tfplan`` is left on
          the filesystem and is NOT touched.
        """
        from backend.app.services.core.artifact_persistence_service import (
            ArtifactPersistenceService as _APS,
        )

        status = "completed" if ok else "failed"

        # 1. Workflow.phases_state — embed the readable summary on a good plan.
        phase_extra: dict = {
            "artifact_id": artifact_id,
            "ok": ok,
            "error": error,
            "failure_classification": failure_classification,
        }
        if phase == PHASE_TF_PLAN and ok and infrastructure_summary is not None:
            phase_extra["infrastructure_summary"] = infrastructure_summary

        if workflow_id:
            workflow = (
                db.query(Workflow).filter(Workflow.id == workflow_id).first()
            )
            if workflow is not None:
                WorkflowOrchestrationService._record_phase(
                    workflow,
                    phase=phase,
                    status=status,
                    extra=phase_extra,
                )
                workflow.current_phase = phase
                workflow.status = "running"
                db.commit()

        # 2. Backing Task workflow_state
        if task_id:
            task = TaskService.get_task(db, task_id)
            if task is not None:
                state = TaskService.load_workflow_state(db, task) or {}
                tf_state = state.setdefault("terraform_pipeline", {})
                tf_state[phase] = {
                    "ok": ok,
                    "error": error,
                    "failure_classification": failure_classification,
                    "results": results,
                }
                if phase == PHASE_TF_PLAN and infrastructure_summary is not None:
                    tf_state[phase]["infrastructure_summary"] = infrastructure_summary
                TaskService.save_workflow_state(db, task, state)

        # 3a. Validation report artifact (text JSON).
        if phase == PHASE_TF_VALIDATION:
            import json as _json

            report = _json.dumps(
                {
                    "ok": ok,
                    "error": error,
                    "failure_classification": failure_classification,
                    "results": results,
                },
                indent=2,
                default=str,
            )
            _APS.upsert_artifact(
                db,
                project_id=project_id,
                workflow_id=workflow_id,
                artifact_type="validation_report",
                artifact_subtype="terraform_validation.json",
                content=report,
                generated_by_agent="TerraformPipelineService",
                validation_status="passed" if ok else "failed",
            )
            db.commit()

        # 3b. Plan artifacts — raw plan.json + derived infrastructure_summary.json.
        #     Both coexist alongside the binary tfplan on disk.
        if phase == PHASE_TF_PLAN and ok:
            import json as _json

            if plan_json:
                _APS.upsert_artifact(
                    db,
                    project_id=project_id,
                    workflow_id=workflow_id,
                    artifact_type="terraform_plan",
                    artifact_subtype="plan.json",
                    content=plan_json,
                    generated_by_agent="TerraformPipelineService",
                    validation_status="passed",
                )
            if infrastructure_summary is not None:
                _APS.upsert_artifact(
                    db,
                    project_id=project_id,
                    workflow_id=workflow_id,
                    artifact_type="infrastructure_summary",
                    artifact_subtype="infrastructure_summary.json",
                    content=_json.dumps(infrastructure_summary, indent=2, default=str),
                    generated_by_agent="TerraformPipelineService",
                    validation_status="passed",
                )
            db.commit()

        logger.info(
            "[TerraformPipeline] recorded %s result ok=%s task=%s",
            phase, ok, task_id,
        )

    # ─── Helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_workflow(db: Session, workflow_id: str) -> Optional[Workflow]:
        return db.query(Workflow).filter(Workflow.id == workflow_id).first()

    @staticmethod
    def get_workflow_for_project(
        db: Session,
        project_id: str,
        workflow_id: str,
    ) -> Optional[Workflow]:
        return (
            db.query(Workflow)
            .filter(Workflow.id == workflow_id, Workflow.project_id == project_id)
            .first()
        )

    @staticmethod
    def get_backing_task(db: Session, workflow: Workflow) -> Optional[Task]:
        # The Task created by start_workflow has ``workflow_id`` set. There is
        # exactly one per Workflow.
        return db.query(Task).filter(Task.workflow_id == workflow.id).first()

    @staticmethod
    def _record_phase(
        workflow: Workflow,
        *,
        phase: str,
        status: str,
        extra: Optional[dict] = None,
    ) -> None:
        phases = dict(workflow.phases_state or {})
        phases[phase] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **(extra or {}),
        }
        workflow.phases_state = phases
