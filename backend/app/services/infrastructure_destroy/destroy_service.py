"""InfrastructureDestroyService — generate → install → dispatch → observe destroy.yml.

The backend NEVER executes Terraform; it commits ``destroy.yml`` to the repo and
asks GitHub Actions to run ``terraform destroy``. Every step reuses an existing
building block (renderer / RepositoryInstallationService / workflow_dispatch /
the monitoring GitHub Actions client), so this service is pure composition + the
lifecycle persistence.

Lifecycle persisted in ``Workflow.phases_state[INFRASTRUCTURE_DESTROY].status``:

    destroy_requested  destroy.yml committed, run not yet confirmed (dispatch 404
                       because it is not on the default branch, or not dispatched)
    destroy_running    dispatched / a GitHub Actions run is in flight
    destroy_succeeded  the destroy.yml run concluded success (reconciled on read)
    destroy_failed     install/dispatch failed, OR the run concluded failure

The two terminal states are reconciled from the live run on the read path
(:meth:`get_status`) — the same read-only observation the monitoring surface uses
for bootstrap.yml.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.schemas.infrastructure_destroy_phase import (
    DESTROY_FAILED,
    DESTROY_REQUESTED,
    DESTROY_RUNNING,
    DESTROY_SUCCEEDED,
    InfrastructureDestroyPhaseResponse,
)
from backend.app.schemas.workflow_monitoring_phase import PipelineRunView
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.core.task_service import TaskService
from backend.app.services.github_actions_generation.models import DeploymentContext
from backend.app.services.github_actions_generation.renderer import render_workflow
from backend.app.services.github_actions_generation.terraform_identifiers import (
    extract_terraform_identifiers,
)
from backend.app.services.github_actions_generation.yaml_validator import (
    validate_workflow_yaml,
)
from backend.app.services.repository.github_service import GitHubService
from backend.app.services.repository_installation.installation_files import (
    TERRAFORM_DIR,
    is_installable_terraform_file,
)
from backend.app.services.repository_installation.installation_service import (
    RepositoryInstallationService,
)
from backend.app.services.repository_installation.models import (
    DEFAULT_DESTROY_BRANCH,
    DEFAULT_DESTROY_COMMIT_MESSAGE,
    DEFAULT_DESTROY_PR_TITLE,
    DESTROY_PATH,
    InstallationPrerequisiteError,
    InstallationResult,
    WorkflowDispatchOutcome,
)
from backend.app.services.repository_installation.workflow_dispatch_client import (
    dispatch_workflow,
)
from backend.app.services.terraform_generation.utils.naming import (
    sanitize_resource_name,
)
from backend.app.services.workflow_monitoring.github_actions_client import (
    GitHubActionsClient,
)
from backend.app.services.workflow_monitoring.models import (
    ACTIVE_RUN_STATUSES,
    RunObservation,
)
from backend.app.services.workflow_monitoring.monitoring_service import (
    WorkflowMonitoringService,
)

logger = logging.getLogger(__name__)

PHASE = "INFRASTRUCTURE_DESTROY"
REPO_INSTALL_PHASE = "REPOSITORY_INSTALLATION"
_DESTROY_FILE = "destroy.yml"
_RECORD_TYPE = "infrastructure_destroy"
_RECORD_SUBTYPE = "destroy.json"
_COMPLETED_STATUSES = {"completed", "completed_with_fallback", "completed_no_files"}
_TERMINAL_DESTROY = {DESTROY_SUCCEEDED, DESTROY_FAILED}
# GitHub run conclusions (other than ``success``) that mean the destroy failed.
_FAILED_CONCLUSIONS = {
    "failure", "cancelled", "timed_out", "startup_failure", "stale", "action_required",
}

# Injectable seams (tests pass fakes; production uses the real callables).
Installer = Callable[..., InstallationResult]
Dispatcher = Callable[..., WorkflowDispatchOutcome]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InfrastructureDestroyService:
    # ─── Phase execution (generate → install → dispatch) ─────────────────────

    @staticmethod
    def run(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        installer: Optional[Installer] = None,
        dispatcher: Optional[Dispatcher] = None,
        create_pr: bool = True,
    ) -> Tuple[dict, List[str]]:
        """Generate + install + dispatch ``destroy.yml`` for one workflow.

        Mirrors ``WorkflowOrchestrationService._run_repository_installation``'s
        contract: caller-fixable preconditions raise ``ValueError`` (→ HTTP 400);
        operational install/dispatch failures are recorded as ``destroy_failed``
        WITHOUT raising (the phase can be re-run). Returns ``(state, artifact_ids)``
        so it slots into the generic ``run_phase`` path unchanged.
        """
        installer = installer or RepositoryInstallationService.install
        dispatcher = dispatcher or dispatch_workflow

        # 1. Preconditions — repo + terraform + token (all reused).
        repo_url = project.repository_url
        if not repo_url:
            raise ValueError(
                f"Cannot run {PHASE}: the project has no repository URL."
            )
        terraform_files = ArtifactPersistenceService.get_terraform_files(
            db, project_id=project.id
        )
        if not terraform_files:
            raise ValueError(
                f"Cannot run {PHASE}: no Terraform artifacts found — there is no "
                "infrastructure configuration to destroy."
            )
        github_token = CredentialsService.get_credential(
            db, project_id=project.id, provider="github_pat",
        )
        if not github_token:
            raise ValueError(
                f"Cannot run {PHASE}: a GitHub token (github_pat credential) is "
                "required to push and dispatch the destroy workflow."
            )

        # 2. Render destroy.yml (region/terraform-dir from the generated TF).
        context = InfrastructureDestroyService._build_context(project, terraform_files)
        _template, content = render_workflow(context, "destroy")
        logs: List[str] = [
            {"step": "infrastructure_destroy",
             "message": "Rendered .github/workflows/destroy.yml from the generated Terraform."}
        ]

        # 3. Validate before persisting/installing.
        validation = validate_workflow_yaml(content)
        if not validation.valid:
            return InfrastructureDestroyService._record_failed(
                db, project=project, workflow=workflow, task=task,
                error="destroy.yml failed validation: " + "; ".join(validation.errors),
                logs=logs, install=None, dispatch=None,
            )

        # 4. Persist destroy.yml as a DB-backed artifact (source of truth).
        persisted_ids: List[str] = []
        artifact = ArtifactPersistenceService.upsert_artifact(
            db,
            project_id=project.id,
            workflow_id=workflow.id,
            artifact_type="github_actions",
            artifact_subtype=DESTROY_PATH,
            content=content,
            generated_by_agent="InfrastructureDestroyService",
            validation_status="passed",
        )
        persisted_ids.append(artifact.id)

        # 5. Install destroy.yml + terraform/ (so `terraform init` works in CI).
        files = InfrastructureDestroyService._installation_files(content, terraform_files)
        base_branch = InfrastructureDestroyService._resolve_default_branch(project)
        try:
            result = installer(
                repo_url=repo_url,
                github_token=github_token,
                files=files,
                base_branch=base_branch,
                install_branch=DEFAULT_DESTROY_BRANCH,
                commit_message=DEFAULT_DESTROY_COMMIT_MESSAGE,
                create_pr=create_pr,
                pr_title=DEFAULT_DESTROY_PR_TITLE,
                pr_body=(
                    "This workflow tears down the infrastructure provisioned by "
                    "MultiMinds. Running it permanently removes the AWS resources "
                    "Terraform created."
                ),
            )
        except InstallationPrerequisiteError as exc:
            raise ValueError(str(exc)) from exc

        logs += [{"step": "infrastructure_destroy", "message": m} for m in result.logs]

        if not result.success:
            return InfrastructureDestroyService._record_failed(
                db, project=project, workflow=workflow, task=task,
                error=result.error or "Failed to commit destroy.yml to the repository.",
                logs=logs, install=result, dispatch=None, persisted_ids=persisted_ids,
            )

        # 6. Auto-dispatch destroy.yml (best-effort, reuses workflow_dispatch).
        dispatch = InfrastructureDestroyService._dispatch(
            repo_url=repo_url, token=github_token, ref=result.install_branch,
            dispatcher=dispatcher,
        )

        # 7. Lifecycle: running when GitHub accepted the trigger, else requested
        #    (committed but the run is not confirmed — e.g. not yet on the default
        #    branch; the user merges the PR, then it dispatches / is observed).
        status = DESTROY_RUNNING if dispatch.dispatched else DESTROY_REQUESTED
        if not dispatch.dispatched and dispatch.error:
            logs.append({"step": "infrastructure_destroy",
                         "message": f"destroy.yml dispatch not confirmed: {dispatch.error}"})

        InfrastructureDestroyService._record_phase(
            workflow, status=status,
            extra=InfrastructureDestroyService._provenance(result, dispatch),
        )
        workflow.current_phase = PHASE
        workflow.status = "running"

        state, record_id = InfrastructureDestroyService._persist_record(
            db, project=project, workflow=workflow, task=task,
            status=status, result=result, dispatch=dispatch, logs=logs,
        )
        persisted_ids.append(record_id)

        db.commit()
        db.refresh(workflow)

        logger.info(
            "[InfraDestroy] project=%s status=%s branch=%s commit=%s dispatched=%s",
            project.id, status, result.install_branch, result.commit_sha,
            dispatch.dispatched,
        )
        return state, persisted_ids

    # ─── Read projection (observe + reconcile, like bootstrap.yml) ───────────

    @staticmethod
    def get_status(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        client: Optional[GitHubActionsClient] = None,
    ) -> InfrastructureDestroyPhaseResponse:
        """Read-only destroy projection. Observes destroy.yml + reconciles state.

        Never raises: a monitoring failure degrades to the persisted state. The
        live run is observed with the SAME client/codepath as bootstrap.yml.
        """
        phases = workflow.phases_state or {}
        entry = dict(phases.get(PHASE) or {})
        phase_status = entry.get("status")

        repo_url = project.repository_url
        has_repo = bool(repo_url)
        has_tf = bool(
            ArtifactPersistenceService.get_terraform_files(db, project_id=project.id)
        )
        has_token = False
        try:
            has_token = CredentialsService.has_credential(
                db, project_id=project.id, provider="github_pat",
            )
        except Exception:  # noqa: BLE001 — existence probe must never raise
            has_token = False

        missing: List[str] = []
        if not has_repo:
            missing.append("repository_url")
        if not has_tf:
            missing.append("terraform")
        if not has_token:
            missing.append("github_token")

        run_view: Optional[PipelineRunView] = None
        monitoring_available = False

        # Build the read-only client ONCE (injectable for tests) when we can and
        # the phase has actually run — observing destroy.yml exactly like bootstrap.
        if client is None and phase_status and has_repo and has_token:
            try:
                token = CredentialsService.get_credential(
                    db, project_id=project.id, provider="github_pat",
                )
                client = GitHubActionsClient(token) if token else None
            except Exception:  # noqa: BLE001 — degrade if the token can't be read
                client = None

        # Reconcile the terminal state from the live run when the phase has been
        # triggered and is not already terminal.
        if phase_status and phase_status not in _TERMINAL_DESTROY and client is not None:
            phase_status, run_view, monitoring_available = (
                InfrastructureDestroyService._reconcile(
                    db, project=project, workflow=workflow,
                    entry=entry, client=client,
                )
            )
            entry = dict((workflow.phases_state or {}).get(PHASE) or entry)
        elif phase_status in _TERMINAL_DESTROY and client is not None:
            # Terminal already — still surface the run (read-only, no state change).
            run_view, monitoring_available = (
                InfrastructureDestroyService._observe_only(
                    project=project, client=client,
                )
            )

        return InfrastructureDestroyPhaseResponse(
            workflow_id=workflow.id,
            project_id=project.id,
            task_id=getattr(task, "id", None),
            current_phase=workflow.current_phase,
            status=workflow.status,
            phase_status=phase_status,
            requested=phase_status == DESTROY_REQUESTED,
            running=phase_status == DESTROY_RUNNING,
            succeeded=phase_status == DESTROY_SUCCEEDED,
            failed=phase_status == DESTROY_FAILED,
            prerequisites_met=(has_repo and has_tf and has_token),
            has_repo_url=has_repo,
            has_github_token=has_token,
            has_terraform=has_tf,
            missing_requirements=missing,
            repo_url=repo_url,
            branch=entry.get("branch"),
            base_branch=entry.get("base_branch"),
            commit_sha=entry.get("commit"),
            pr_url=entry.get("pr_url"),
            pr_created=bool(entry.get("pr_created")),
            pr_skipped_reason=entry.get("pr_skipped_reason"),
            dispatched=bool(entry.get("dispatched")),
            dispatch_error=entry.get("dispatch_error"),
            error=entry.get("error"),
            monitoring_available=monitoring_available,
            run=run_view,
            logs=[],
        )

    # ─── Deletion guard (no infra, OR destroy succeeded) ─────────────────────

    @staticmethod
    def infrastructure_state(db: Session, project: Project) -> dict:
        """Whether ``project`` may be deleted, across ALL its workflows.

        ``has_infrastructure`` — some workflow completed REPOSITORY_INSTALLATION
        (the milestone at which bootstrap.yml was installed + dispatched, i.e.
        infrastructure was provisioned). ``destroy_succeeded`` — some workflow's
        INFRASTRUCTURE_DESTROY reached ``destroy_succeeded``. A project is
        deletable iff it never provisioned infrastructure OR that infrastructure
        was successfully destroyed.
        """
        workflows = (
            db.query(Workflow).filter(Workflow.project_id == project.id).all()
        )
        has_infrastructure = False
        destroy_succeeded = False
        for wf in workflows:
            phases = wf.phases_state or {}
            install = (phases.get(REPO_INSTALL_PHASE) or {}).get("status")
            if install in _COMPLETED_STATUSES:
                has_infrastructure = True
            if (phases.get(PHASE) or {}).get("status") == DESTROY_SUCCEEDED:
                destroy_succeeded = True

        deletable = (not has_infrastructure) or destroy_succeeded
        reason = None
        if not deletable:
            reason = (
                "This project has live infrastructure. Destroy it "
                "(Destroy Infrastructure) and wait for the destroy to succeed "
                "before deleting the project."
            )
        return {
            "deletable": deletable,
            "has_infrastructure": has_infrastructure,
            "destroy_succeeded": destroy_succeeded,
            "reason": reason,
        }

    # ─── Internals ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_context(
        project: Project, terraform_files: Dict[str, str],
    ) -> DeploymentContext:
        """Minimal context for the destroy template.

        The destroy template only needs ``project_name``, ``aws_region`` and
        ``terraform_directory``. The region is read from the GENERATED Terraform
        (the source of truth — same principle as the deploy-context fix), so the
        destroy never guesses a region the infrastructure was not created in.
        ``deployment_target`` is irrelevant to destroy (the template is
        target-agnostic) but required by the model, so a valid placeholder is used.
        """
        region = extract_terraform_identifiers(terraform_files).aws_region or "us-east-1"
        return DeploymentContext(
            deployment_target="ecs",  # unused by the destroy template
            aws_region=region,
            project_name=sanitize_resource_name(project.name, fallback="devsecops-app"),
            terraform_directory=TERRAFORM_DIR,
        )

    @staticmethod
    def _installation_files(
        destroy_yaml: str, terraform_files: Dict[str, str],
    ) -> Dict[str, str]:
        """``{repo_path: content}`` to commit: destroy.yml + terraform/*.tf(vars).

        Reuses the installation allow-list helper so only real ``.tf``/``.tfvars``
        config is written (never state, never an arbitrary file).
        """
        files: Dict[str, str] = {DESTROY_PATH: destroy_yaml}
        for filename, content in (terraform_files or {}).items():
            if is_installable_terraform_file(filename) and isinstance(content, str) and content.strip():
                files[f"{TERRAFORM_DIR}/{filename}"] = content
        return files

    @staticmethod
    def _resolve_default_branch(project: Project) -> str:
        meta = project.project_metadata or {}
        branch = str(meta.get("default_branch") or "").strip()
        return branch or "main"

    @staticmethod
    def _dispatch(
        *, repo_url: str, token: str, ref: str, dispatcher: Dispatcher,
    ) -> WorkflowDispatchOutcome:
        """Trigger destroy.yml via workflow_dispatch. Never raises (best-effort)."""
        try:
            owner, repo = GitHubService._extract_owner_and_repo(repo_url)
        except ValueError as exc:
            return WorkflowDispatchOutcome(dispatched=False, error=str(exc))
        return dispatcher(
            owner=owner, repo=repo, token=token,
            workflow_file=_DESTROY_FILE, ref=ref,
        )

    @staticmethod
    def _reconcile(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        entry: dict,
        client: Optional[GitHubActionsClient],
    ) -> Tuple[Optional[str], Optional[PipelineRunView], bool]:
        """Observe destroy.yml + promote the persisted state on a terminal run.

        Returns ``(phase_status, run_view, monitoring_available)``. Reuses the
        monitoring observation (``_observe(..., "destroy")``) so destroy.yml is
        watched EXACTLY like bootstrap.yml. Persists a status change (running →
        succeeded/failed) so it survives and feeds the deletion guard.
        """
        current = entry.get("status")
        obs, available = InfrastructureDestroyService._observe(project, client)
        if obs is None:
            return current, None, available

        new_status = current
        if obs.found and obs.status == "completed":
            new_status = (
                DESTROY_SUCCEEDED if obs.conclusion == "success"
                else DESTROY_FAILED if obs.conclusion in _FAILED_CONCLUSIONS
                else current
            )
        elif obs.found and obs.status in ACTIVE_RUN_STATUSES:
            new_status = DESTROY_RUNNING

        if new_status and new_status != current:
            InfrastructureDestroyService._record_phase(
                workflow, status=new_status,
                extra={k: entry.get(k) for k in (
                    "branch", "base_branch", "commit", "pr_url", "pr_created",
                    "pr_skipped_reason", "dispatched", "dispatch_error",
                ) if entry.get(k) is not None},
            )
            workflow.current_phase = PHASE
            db.commit()
            db.refresh(workflow)

        return new_status, _to_view(obs), available

    @staticmethod
    def _observe_only(
        *, project: Project, client: Optional[GitHubActionsClient],
    ) -> Tuple[Optional[PipelineRunView], bool]:
        obs, available = InfrastructureDestroyService._observe(project, client)
        return (_to_view(obs) if obs is not None else None), available

    @staticmethod
    def _observe(
        project: Project, client: Optional[GitHubActionsClient],
    ) -> Tuple[Optional[RunObservation], bool]:
        """Read destroy.yml's latest run via the monitoring client. Never raises.

        ``client`` is always supplied by the caller (built once in
        :meth:`get_status`, or injected by tests) — this never fetches a token.
        """
        repo_url = project.repository_url
        if not repo_url or client is None:
            return None, False
        try:
            owner, repo = GitHubService._extract_owner_and_repo(repo_url)
        except ValueError:
            return None, False
        try:
            obs = WorkflowMonitoringService._observe(client, owner, repo, "destroy")
        except Exception as exc:  # noqa: BLE001 — observation must never raise
            logger.warning(
                "[InfraDestroy] observe failed project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            return None, False
        return obs, obs.available

    # ── phases_state + record persistence ────────────────────────────────────

    @staticmethod
    def _provenance(result: InstallationResult, dispatch: WorkflowDispatchOutcome) -> dict:
        return {
            "branch": result.install_branch,
            "base_branch": result.base_branch,
            "commit": result.commit_sha,
            "pr_url": result.pr_url,
            "pr_created": result.pr_created,
            "pr_skipped_reason": result.pr_skipped_reason,
            "dispatched": dispatch.dispatched,
            "dispatch_error": dispatch.error,
        }

    @staticmethod
    def _record_phase(workflow: Workflow, *, status: str, extra: Optional[dict] = None) -> None:
        phases = dict(workflow.phases_state or {})
        phases[PHASE] = {
            "status": status,
            "updated_at": _utcnow_iso(),
            **(extra or {}),
        }
        workflow.phases_state = phases

    @staticmethod
    def _record_failed(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        error: str,
        logs: List[dict],
        install: Optional[InstallationResult],
        dispatch: Optional[WorkflowDispatchOutcome],
        persisted_ids: Optional[List[str]] = None,
    ) -> Tuple[dict, List[str]]:
        """Record ``destroy_failed`` without raising; keep the run open to retry."""
        extra: dict = {"error": error}
        if install is not None:
            extra.update({
                "branch": install.install_branch,
                "base_branch": install.base_branch,
                "commit": install.commit_sha,
            })
        InfrastructureDestroyService._record_phase(workflow, status=DESTROY_FAILED, extra=extra)
        workflow.current_phase = PHASE
        workflow.status = "running"  # not terminal — a fix + re-run can complete it

        state, record_id = InfrastructureDestroyService._persist_record(
            db, project=project, workflow=workflow, task=task,
            status=DESTROY_FAILED, result=install, dispatch=dispatch,
            logs=logs + [{"step": "infrastructure_destroy", "message": error}],
        )
        ids = list(persisted_ids or [])
        ids.append(record_id)
        db.commit()
        db.refresh(workflow)
        logger.warning("[InfraDestroy] project=%s destroy_failed: %s", project.id, error)
        return state, ids

    @staticmethod
    def _persist_record(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        status: str,
        result: Optional[InstallationResult],
        dispatch: Optional[WorkflowDispatchOutcome],
        logs: List[dict],
    ) -> Tuple[dict, str]:
        """Upsert the durable ``destroy.json`` record + mirror into scratch state.

        Returns ``(scratch_state, record_artifact_id)``. The record survives
        scratch loss and carries the install + dispatch outcome alongside the
        lifecycle status.
        """
        record = {
            "status": status,
            "updated_at": _utcnow_iso(),
            "repo_url": project.repository_url,
            "branch": getattr(result, "install_branch", None),
            "base_branch": getattr(result, "base_branch", None),
            "commit": getattr(result, "commit_sha", None),
            "pr_url": getattr(result, "pr_url", None),
            "pr_created": getattr(result, "pr_created", False),
            "pr_skipped_reason": getattr(result, "pr_skipped_reason", None),
            "dispatched": getattr(dispatch, "dispatched", False),
            "dispatch_error": getattr(dispatch, "error", None),
            "error": getattr(result, "error", None) if (result and not result.success) else None,
        }
        artifact = ArtifactPersistenceService.upsert_artifact(
            db,
            project_id=project.id,
            workflow_id=workflow.id,
            artifact_type=_RECORD_TYPE,
            artifact_subtype=_RECORD_SUBTYPE,
            content=json.dumps(record, indent=2, default=str),
            generated_by_agent="InfrastructureDestroyService",
            validation_status="passed",
        )

        state = TaskService.load_workflow_state(db, task) if task else {}
        state = state or {}
        destroy_state = state.setdefault("infrastructure_destroy", {})
        destroy_state.update(record)
        state["logs"] = list(state.get("logs", [])) + list(logs)
        if task is not None:
            TaskService.stage_workflow_state(task, state)
        return state, artifact.id


def _to_view(obs: RunObservation) -> PipelineRunView:
    """Map a monitoring RunObservation onto the API PipelineRunView (read-only)."""
    return PipelineRunView(
        pipeline=obs.pipeline,
        kind=obs.pipeline,
        name=obs.name,
        workflow_file=obs.workflow_file,
        workflow_url=obs.workflow_url,
        available=obs.available,
        found=obs.found,
        run_id=obs.run_id,
        run_number=obs.run_number,
        status=obs.status,
        conclusion=obs.conclusion,
        branch=obs.branch,
        commit_sha=obs.commit_sha,
        actor=obs.actor,
        event=obs.event,
        started_at=obs.started_at,
        completed_at=obs.completed_at,
        duration_seconds=obs.duration_seconds,
        html_url=obs.html_url,
        current_job=obs.current_job,
        current_step=obs.current_step,
        error=obs.error,
    )
