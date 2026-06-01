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
