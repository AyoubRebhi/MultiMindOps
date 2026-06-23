"""GitHubActionsPhaseProjectionService — read-only projection of the phase.

Assembles the ONE payload the GitHub Actions surface consumes
(``GET /api/projects/{pid}/workflows/{wid}/github-actions``) by RESHAPING data
the GITHUB_ACTIONS_GENERATION phase already persisted. It is the deployment
analogue of ``DockerPhaseProjectionService``:

* reads the backing task's ``workflow_state["github_actions"]`` (rendered YAML for
  each pipeline, deployment context, inline validation),
* reads ``Workflow.phases_state`` for the authoritative phase status,
* reads the DB-backed ``github_actions`` ``Artifact`` rows (one per file:
  ``bootstrap.yml`` + ``deploy.yml``) for each file's version + approval +
  validation status (source of truth for the persisted bytes).

It NEVER re-runs generation and NEVER calls an LLM. A workflow that has not
reached the phase projects to ``generated=False`` with well-formed empty
sub-objects (200, not 404). The response exposes the bootstrap/deploy split as
``pipelines`` and keeps ``workflow_file`` pointed at the delivery file for
backward compatibility.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.schemas.github_actions_phase import (
    DeploymentContextView,
    GitHubActionsArtifact,
    GitHubActionsPhaseResponse,
    PipelineFileView,
    WorkflowYamlValidation,
)
from backend.app.services.core.task_service import TaskService

_PHASE_KEY = "GITHUB_ACTIONS_GENERATION"
_BOOTSTRAP_PATH = ".github/workflows/bootstrap.yml"
_DEPLOY_PATH = ".github/workflows/deploy.yml"

# Path → (kind, human name). Used to reconstruct pipeline identity when projecting
# from DB rows alone (e.g. a legacy run with no scratch ``pipelines`` block).
_PIPELINE_BY_PATH: Dict[str, tuple[str, str]] = {
    _BOOTSTRAP_PATH: ("bootstrap", "Infrastructure Pipeline"),
    _DEPLOY_PATH: ("deploy", "Delivery Pipeline"),
}


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

        rows_by_path = GitHubActionsPhaseProjectionService._artifact_rows(
            db, project_id=project_id
        )

        pipelines = GitHubActionsPhaseProjectionService._build_pipelines(
            gh, phase_entry, rows_by_path
        )
        generated = any(p.content.strip() for p in pipelines)

        # Back-compat: the delivery (deploy.yml) file as the legacy single artifact.
        deploy_view = next(
            (p for p in pipelines if p.kind == "deploy" and p.content.strip()), None
        )
        workflow_file: Optional[GitHubActionsArtifact] = None
        if deploy_view is not None:
            workflow_file = GitHubActionsArtifact(
                path=deploy_view.path or _DEPLOY_PATH,
                content=deploy_view.content,
                version=deploy_view.version,
                approval_state=deploy_view.approval_state,
                validation_status=deploy_view.validation_status,
            )

        context_view = GitHubActionsPhaseProjectionService._context_view(gh, phase_entry)
        # Top-level validation mirrors the delivery file (legacy single-file field).
        validation = (
            deploy_view.validation if deploy_view is not None
            else GitHubActionsPhaseProjectionService._validation(gh, phase_entry)
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
            pipelines=pipelines,
            workflow_file=workflow_file,
            infrastructure_summary=(
                gh.get("deployment_context", {}).get("infrastructure_summary")
                if isinstance(gh.get("deployment_context"), dict)
                else {}
            ) or {},
        )

    # ── Pipelines (bootstrap + deploy) ────────────────────────────────────────

    @staticmethod
    def _build_pipelines(
        gh: Dict[str, Any],
        phase_entry: Dict[str, Any],
        rows_by_path: Dict[str, Artifact],
    ) -> List[PipelineFileView]:
        """Reconstruct both pipeline files, preferring DB bytes over scratch.

        Source order:
          1. scratch ``github_actions.pipelines`` (carries rendered content +
             inline validation per file) — the normal path,
          2. the DB-backed ``github_actions`` Artifact rows (canonical bytes /
             version / approval) merged in,
          3. a legacy single-file scratch render (``gh['content']``) as a last
             resort so old runs still project.
        """
        scratch_pipelines = gh.get("pipelines")
        views: List[PipelineFileView] = []
        seen_paths: set[str] = set()

        if isinstance(scratch_pipelines, list) and scratch_pipelines:
            for item in scratch_pipelines:
                if not isinstance(item, dict):
                    continue
                path = item.get("path") or ""
                row = rows_by_path.get(path)
                views.append(
                    GitHubActionsPhaseProjectionService._pipeline_view(item, path, row)
                )
                seen_paths.add(path)

        # Merge any DB rows not represented in scratch (e.g. scratch lost).
        for path, row in rows_by_path.items():
            if path in seen_paths:
                continue
            views.append(
                GitHubActionsPhaseProjectionService._pipeline_view({}, path, row)
            )
            seen_paths.add(path)

        # Legacy fallback: a single-file run with no per-pipeline block.
        if not views:
            legacy_content = str(gh.get("content") or "")
            if legacy_content.strip():
                kind, name = _PIPELINE_BY_PATH.get(
                    _DEPLOY_PATH, ("deploy", "Delivery Pipeline")
                )
                views.append(
                    PipelineFileView(
                        name=name,
                        kind=kind,
                        path=gh.get("workflow_path") or _DEPLOY_PATH,
                        content=legacy_content,
                        template=gh.get("template"),
                        validation=GitHubActionsPhaseProjectionService._validation(
                            gh, phase_entry
                        ),
                        enrichment_applied=bool(gh.get("enrichment_applied")),
                    )
                )

        # Stable order: bootstrap first, then deploy, then anything else.
        order = {_BOOTSTRAP_PATH: 0, _DEPLOY_PATH: 1}
        views.sort(key=lambda v: order.get(v.path, 99))
        return views

    @staticmethod
    def _pipeline_view(
        item: Dict[str, Any], path: str, row: Optional[Artifact]
    ) -> PipelineFileView:
        """Build one :class:`PipelineFileView`, preferring DB content over scratch."""
        kind, default_name = _PIPELINE_BY_PATH.get(path, ("", ""))
        db_content = str(getattr(row, "content", "") or "") if row else ""
        content = db_content or str(item.get("content") or "")

        val = item.get("validation")
        validation = (
            WorkflowYamlValidation(
                status=val.get("status", "not_run"),
                valid=val.get("status", "") != "failed",
                errors=list(val.get("errors") or []),
                warnings=list(val.get("warnings") or []),
            )
            if isinstance(val, dict) and val
            else WorkflowYamlValidation()
        )

        return PipelineFileView(
            name=item.get("name") or default_name,
            kind=item.get("kind") or kind,
            path=path,
            content=content,
            template=item.get("template"),
            version=getattr(row, "version", None) if row else None,
            approval_state=getattr(row, "approval_state", None) if row else None,
            validation_status=getattr(row, "validation_status", None) if row else None,
            validation=validation,
            enrichment_applied=bool(item.get("enrichment_applied")),
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _artifact_rows(db: Session, *, project_id: str) -> Dict[str, Artifact]:
        """Return the project's ``github_actions`` Artifact rows keyed by path."""
        rows = (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.artifact_type == "github_actions",
            )
            .all()
        )
        return {row.artifact_subtype: row for row in rows if row.artifact_subtype}

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
