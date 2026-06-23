"""GitHubActionsPhaseProjectionService — read-only projection of the phase.

Assembles the ONE payload the GitHub Actions surface consumes
(``GET /api/projects/{pid}/workflows/{wid}/github-actions``) by RESHAPING data
the GITHUB_ACTIONS_GENERATION phase already persisted. It is the deployment
analogue of ``DockerPhaseProjectionService``:

* reads the backing task's ``workflow_state["github_actions"]`` (rendered YAML,
  deployment context, inline validation),
* reads ``Workflow.phases_state`` for the authoritative phase status,
* reads the DB-backed ``github_actions`` ``Artifact`` row for the deploy.yml's
  version + approval + validation status (source of truth for the persisted file).

It NEVER re-runs generation and NEVER calls an LLM. A workflow that has not
reached the phase projects to ``generated=False`` with well-formed empty
sub-objects (200, not 404).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.schemas.github_actions_phase import (
    DeploymentContextView,
    GitHubActionsArtifact,
    GitHubActionsPhaseResponse,
    WorkflowYamlValidation,
)
from backend.app.services.core.task_service import TaskService

_PHASE_KEY = "GITHUB_ACTIONS_GENERATION"
_WORKFLOW_PATH = ".github/workflows/deploy.yml"


class GitHubActionsPhaseProjectionService:
    """Pure read projection — no generation, no orchestration, no LLM."""

    @staticmethod
    def build(
        db: Session,
        *,
        project_id: str,
        workflow: Workflow,
        task: Optional[Task],
    ) -> GitHubActionsPhaseResponse:
        state: Dict[str, Any] = (
            TaskService.load_workflow_state(db, task) if task else {}
        ) or {}
        gh: Dict[str, Any] = state.get("github_actions") or {}

        phases_state = workflow.phases_state or {}
        phase_entry = phases_state.get(_PHASE_KEY) or {}
        phase_status = phase_entry.get("status")

        row = GitHubActionsPhaseProjectionService._artifact_row(
            db, project_id=project_id
        )

        # Prefer the persisted DB content (canonical) but fall back to the
        # scratch render so an un-persisted (e.g. failed-validation) result shows.
        db_content = str(getattr(row, "content", "") or "")
        content = db_content or str(gh.get("content") or "")
        generated = bool(content.strip())

        context_view = GitHubActionsPhaseProjectionService._context_view(gh, phase_entry)
        validation = GitHubActionsPhaseProjectionService._validation(gh, phase_entry)

        workflow_file: Optional[GitHubActionsArtifact] = None
        if generated:
            workflow_file = GitHubActionsArtifact(
                path=_WORKFLOW_PATH,
                content=content,
                version=getattr(row, "version", None),
                approval_state=getattr(row, "approval_state", None),
                validation_status=getattr(row, "validation_status", None),
            )

        return GitHubActionsPhaseResponse(
            workflow_id=workflow.id,
            project_id=project_id,
            task_id=getattr(task, "id", None),
            current_phase=workflow.current_phase,
            status=workflow.status,
            phase_status=phase_status,
            generated=generated,
            deployment_target=context_view.deployment_target
            or phase_entry.get("deployment_target"),
            template=gh.get("template") or phase_entry.get("template"),
            enrichment_applied=bool(
                gh.get("enrichment_applied")
                or phase_entry.get("enrichment_applied")
            ),
            deployment_context=context_view,
            validation=validation,
            workflow_file=workflow_file,
            infrastructure_summary=(
                gh.get("deployment_context", {}).get("infrastructure_summary")
                if isinstance(gh.get("deployment_context"), dict)
                else {}
            ) or {},
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _artifact_row(db: Session, *, project_id: str) -> Optional[Artifact]:
        return (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.artifact_type == "github_actions",
            )
            .first()
        )

    @staticmethod
    def _context_view(
        gh: Dict[str, Any], phase_entry: Dict[str, Any]
    ) -> DeploymentContextView:
        ctx = gh.get("deployment_context")
        if isinstance(ctx, dict) and ctx:
            return DeploymentContextView(
                cloud_provider=ctx.get("cloud_provider", "aws"),
                deployment_target=ctx.get("deployment_target"),
                aws_region=ctx.get("aws_region"),
                project_name=ctx.get("project_name"),
                repository_name=ctx.get("repository_name"),
                cluster_name=ctx.get("cluster_name"),
                service_name=ctx.get("service_name"),
                function_name=ctx.get("function_name"),
                container_port=ctx.get("container_port"),
                terraform_directory=ctx.get("terraform_directory"),
                docker_artifacts=list(ctx.get("docker_artifacts") or []),
                terraform_artifacts=list(ctx.get("terraform_artifacts") or []),
            )
        # Fall back to whatever the phase entry recorded.
        return DeploymentContextView(
            deployment_target=phase_entry.get("deployment_target"),
            docker_artifacts=list(phase_entry.get("docker_artifacts") or []),
            terraform_artifacts=list(phase_entry.get("terraform_artifacts") or []),
        )

    @staticmethod
    def _validation(
        gh: Dict[str, Any], phase_entry: Dict[str, Any]
    ) -> WorkflowYamlValidation:
        val = gh.get("validation")
        if isinstance(val, dict) and val:
            return WorkflowYamlValidation(
                status=val.get("status", "not_run"),
                valid=val.get("status", "") != "failed",
                errors=list(val.get("errors") or []),
                warnings=list(val.get("warnings") or []),
            )
        status = phase_entry.get("validation_status")
        if status:
            return WorkflowYamlValidation(
                status=status,
                valid=status != "failed",
                errors=list(phase_entry.get("validation_errors") or []),
            )
        return WorkflowYamlValidation()
