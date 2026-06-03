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

# Phase → durable job phase string consumed by the worker handler registry.
_TF_JOB_PHASE = {
    PHASE_TF_VALIDATION: "terraform_validate",
    PHASE_TF_PLAN: "terraform_plan",
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
    def start_workflow(
        db: Session,
        *,
        project: Project,
        user: User,
        prompt: str,
        execution_mode: str = "full",
    ) -> Tuple[Workflow, Task, dict]:
        """Begin a new workflow run for a project.

        Runs the architecture-decision phase (analysis + planning + cost) and
        pauses for user plan selection. Creates both a ``Workflow`` row and a
        backing ``Task`` row (the orchestrator persists state on the Task,
        which we keep so the legacy ``/workflow/*`` router can also resume it).
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
        )
        TaskService.save_plan_awaiting_validation(db, task, state)

        WorkflowOrchestrationService._record_phase(
            workflow,
            phase="ARCHITECTURE_DECISION",
            status="awaiting_input",
            extra={"task_id": task.id},
        )
        workflow.current_phase = "ARCHITECTURE_DECISION"
        workflow.status = "awaiting_input"

        # Capture analysis + architecture-decision digests into ProjectContext.
        # Done before commit so it lands in the same transaction as the workflow row.
        ProjectContextService.capture_from_state(
            db,
            project_id=project.id,
            state=state,
            phase="ARCHITECTURE_DECISION",
            generated_by="OrchestratorAgent",
        )

        db.commit()
        db.refresh(workflow)
        db.refresh(task)
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
        """Run a single phase by name.

        Loads state from the backing Task, delegates to the OrchestratorAgent's
        per-phase method, persists state back to the Task, persists generated
        artifacts to the project, and updates ``Workflow.phases_state``.

        Returns ``(state, persisted_artifact_ids)``.
        """
        # Infrastructure Lifecycle phases run through a dedicated path: the
        # template MVP pipeline + (for validation/plan) the durable job system.
        # They do NOT touch the OrchestratorAgent / LLM terraform phase.
        if phase.upper() in _TF_PIPELINE_PHASES:
            return WorkflowOrchestrationService._run_terraform_pipeline_phase(
                db, project=project, workflow=workflow, task=task,
                phase=phase.upper(),
            )

        prior_state = TaskService.load_workflow_state(db, task) or {}
        # Phase 4 — re-hydrate runtime-only secrets. Stays in memory for
        # this request only; never re-persisted.
        prior_state = CredentialsService.hydrate_state(
            db, prior_state, project_id=project.id,
        )
        orchestrator = OrchestratorAgent()

        phase_upper = phase.upper()
        agent_name = ""

        if phase_upper == PHASE_DOCKER:
            state = orchestrator.run_docker_phase(prior_state)
            agent_name = "InfrastructureAgent"
        elif phase_upper == PHASE_TERRAFORM:
            state = orchestrator.run_terraform_phase_only(prior_state, task_id=task.id)
            agent_name = "TerraformAgent"
        elif phase_upper == PHASE_KUBERNETES:
            state = orchestrator.run_kubernetes_phase_only(prior_state)
            agent_name = "KubernetesAgent"
        elif phase_upper == PHASE_CICD:
            state = orchestrator.run_cicd_and_finalize_phase(prior_state)
            agent_name = "CICDAgent"
        else:
            raise ValueError(f"Unknown phase: {phase}")

        TaskService.save_workflow_state(db, task, state)

        artifacts = ArtifactPersistenceService.persist_state_artifacts(
            db,
            project_id=project.id,
            workflow_id=workflow.id,
            state=state,
            generated_by_agent=agent_name,
        )

        phase_succeeded = not state.get("current_phase", "").endswith("_failed")
        WorkflowOrchestrationService._record_phase(
            workflow,
            phase=phase_upper,
            status="completed" if phase_succeeded else "failed",
            extra={
                "artifact_count": len(artifacts),
                "current_phase": state.get("current_phase"),
            },
        )
        workflow.current_phase = phase_upper
        workflow.status = "running" if phase_upper != PHASE_CICD else "completed"
        if phase_upper == PHASE_CICD:
            workflow.finished_at = datetime.now(timezone.utc)

        if state.get("result"):
            TaskService.save_result(db, task, state["result"])
        if state.get("plan"):
            TaskService.save_plan(db, task, state["plan"])

        # Per-phase ProjectContext capture — docker/terraform/k8s hints,
        # infrastructure summary, and validation rollup.
        ProjectContextService.capture_from_state(
            db,
            project_id=project.id,
            state=state,
            phase=phase_upper,
            generated_by=agent_name,
        )

        db.commit()
        db.refresh(workflow)
        return state, [a.id for a in artifacts]

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
        from backend.app.services.core.artifact_persistence_service import (
            classify_artifact,
        )
        from backend.app.services.terraform_pipeline import TerraformPipelineService

        state = TaskService.load_workflow_state(db, task) or {}
        plan = state.get("plan") or {}
        blueprint = plan.get("infrastructure_blueprint") or {}

        architecture = (
            blueprint.get("architecture_style")
            or plan.get("architecture_style")
            or state.get("architecture_style")
        )
        if not architecture:
            raise ValueError(
                "Cannot run TERRAFORM_GENERATION: no architecture style found in "
                "the selected plan. Run architecture-decision + select-plan first."
            )

        # The MVP pipeline only supports the 'balanced' tier; pass it explicitly
        # rather than the selected strategy id (low_cost/high_performance), which
        # the template renderer does not implement.
        project_name = (plan.get("project_name") or project.name or "app")[:32]

        svc = TerraformPipelineService()
        result = svc.generate(
            architecture=str(architecture),
            tier="balanced",
            project_name=project_name,
        )

        # Persist generated .tf into the project DB artifact store so the
        # timeline counts them, alongside the filesystem copy generate() wrote.
        persisted: List[str] = []
        for filename, content in result.files.items():
            row = ArtifactPersistenceService.upsert_artifact(
                db,
                project_id=project.id,
                workflow_id=workflow.id,
                artifact_type=classify_artifact(filename) or "terraform",
                artifact_subtype=filename,
                content=content,
                generated_by_agent="TerraformPipelineService",
            )
            persisted.append(row.id)
        db.commit()

        # Record the pipeline artifact id so validation/plan can locate the dir.
        tf_state = state.setdefault("terraform_pipeline", {})
        tf_state["artifact_id"] = result.id
        tf_state["architecture"] = str(architecture)
        tf_state["tier"] = "balanced"
        tf_state["files"] = sorted(result.files.keys())
        tf_state["metadata"] = result.metadata
        TaskService.save_workflow_state(db, task, state)

        WorkflowOrchestrationService._record_phase(
            workflow,
            phase=PHASE_TF_GENERATION,
            status="completed",
            extra={
                "artifact_id": result.id,
                "artifact_count": len(persisted),
                "architecture": str(architecture),
            },
        )
        workflow.current_phase = PHASE_TF_GENERATION
        workflow.status = "running"
        db.commit()
        db.refresh(workflow)

        logger.info(
            "[TerraformPipeline] generation complete project=%s artifact=%s files=%d",
            project.id, result.id, len(persisted),
        )
        return state, persisted

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
                    "results": results,
                }
                if phase == PHASE_TF_PLAN and infrastructure_summary is not None:
                    tf_state[phase]["infrastructure_summary"] = infrastructure_summary
                TaskService.save_workflow_state(db, task, state)

        # 3a. Validation report artifact (text JSON).
        if phase == PHASE_TF_VALIDATION:
            import json as _json

            report = _json.dumps(
                {"ok": ok, "error": error, "results": results}, indent=2, default=str
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
