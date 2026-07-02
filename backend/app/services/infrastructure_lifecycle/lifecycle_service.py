"""InfrastructureLifecycleService — the post-deployment operational layer.

The FINAL operational phase (after Monitoring). It is pure COMPOSITION over
capabilities the platform already has — it adds no new orchestration engine, no
workers, and never runs Terraform:

* status + state + inventory + history  →  read projection (``get_status``)
* retry bootstrap                       →  re-dispatch bootstrap.yml (GitHub Actions)
* destroy                               →  reuse ``InfrastructureDestroyService.run``
* monitoring of all of the above        →  reuse the read-only monitoring client

Every action appends an immutable :class:`InfrastructureLifecycleEvent`, and the
read path reconciles import/recovery/destroy outcomes into that same history
(idempotently) so "every recovery attempt" is visible without modifying the
import/recovery services.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.schemas.infrastructure_lifecycle_phase import (
    EVENT_BOOTSTRAP_RETRY,
    EVENT_BOOTSTRAP_RETRY_FAILED,
    EVENT_DESTROY_COMPLETED,
    EVENT_DESTROY_FAILED,
    EVENT_DESTROY_REQUESTED,
    EVENT_IMPORT_COMPLETED,
    EVENT_RECOVERY_COMPLETED,
    INFRA_DESTROYED,
    INFRA_FAILED,
    INFRA_HEALTHY,
    INFRA_PENDING,
    InfrastructureLifecyclePhaseResponse,
    LifecycleActionResult,
    LifecycleActionView,
    LifecycleEventView,
    RecoveryAttemptView,
    TerraformStateView,
)
from backend.app.schemas.workflow_monitoring_phase import PipelineRunView
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.infrastructure_destroy import InfrastructureDestroyService
from backend.app.services.infrastructure_lifecycle.lifecycle_event_service import (
    LifecycleEventService,
)
from backend.app.services.infrastructure_lifecycle.resource_inventory import (
    build_inventory,
    parse_state_location,
)
from backend.app.services.repository.github_service import GitHubService
from backend.app.services.repository_installation.workflow_dispatch_client import (
    dispatch_workflow,
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

# A genuine provisioning failure (excludes user cancellation).
_FAILED_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}

Dispatcher = Callable[..., object]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InfrastructureLifecycleService:
    """Read projection + lifecycle actions. Read path never raises."""

    # ─── Read projection (the dashboard) ───────────────────────────────────────

    @staticmethod
    def get_status(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        can_manage: bool = False,
        client: Optional[GitHubActionsClient] = None,
    ) -> InfrastructureLifecyclePhaseResponse:
        """Aggregate the whole lifecycle dashboard. Never raises."""
        base = dict(
            workflow_id=workflow.id,
            project_id=project.id,
            task_id=getattr(task, "id", None),
            current_phase=workflow.current_phase,
            status=workflow.status,
            can_manage=can_manage,
        )
        try:
            return InfrastructureLifecycleService._build(
                db, project=project, workflow=workflow, task=task,
                base=base, can_manage=can_manage, client=client,
            )
        except Exception as exc:  # noqa: BLE001 — dashboard must never 500
            logger.warning(
                "[Lifecycle] unexpected failure project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            return InfrastructureLifecyclePhaseResponse(
                **base, error="Could not load the infrastructure lifecycle right now."
            )

    @staticmethod
    def _build(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        base: dict,
        can_manage: bool,
        client: Optional[GitHubActionsClient],
    ) -> InfrastructureLifecyclePhaseResponse:
        repo_url = project.repository_url
        has_repo = bool(repo_url)

        tf_files = ArtifactPersistenceService.get_terraform_files(db, project_id=project.id)
        has_tf = bool(tf_files)
        backend_configured, bucket, key = parse_state_location(tf_files)
        inventory, managed_count = build_inventory(tf_files)

        has_token = False
        try:
            has_token = CredentialsService.has_credential(
                db, project_id=project.id, provider="github_pat",
            )
        except Exception:  # noqa: BLE001
            has_token = False

        if client is None and has_repo and has_token:
            try:
                token = CredentialsService.get_credential(
                    db, project_id=project.id, provider="github_pat",
                )
                client = GitHubActionsClient(token) if token else None
            except Exception:  # noqa: BLE001
                client = None

        boot, boot_avail = InfrastructureLifecycleService._observe(project, client, "bootstrap")
        deploy, deploy_avail = InfrastructureLifecycleService._observe(project, client, "deploy")
        destroy_obs, destroy_avail = InfrastructureLifecycleService._observe(project, client, "destroy")
        monitoring_available = boot_avail or deploy_avail or destroy_avail

        boot_failed = bool(boot and boot.found and boot.status == "completed"
                           and boot.conclusion in _FAILED_CONCLUSIONS)
        boot_success = bool(boot and boot.found and boot.status == "completed"
                            and boot.conclusion == "success")
        boot_running = bool(boot and boot.found and boot.status in ACTIVE_RUN_STATUSES)

        guard = InfrastructureDestroyService.infrastructure_state(db, project)
        destroy_run_success = bool(destroy_obs and destroy_obs.found
                                   and destroy_obs.status == "completed"
                                   and destroy_obs.conclusion == "success")
        destroyed = bool(guard.get("destroy_succeeded")) or destroy_run_success

        # Reconcile import/recovery/destroy outcomes into immutable history.
        import_rec = InfrastructureLifecycleService._read_json(
            db, project.id, "infrastructure_import", "import_recovery.json")
        recovery_rec = InfrastructureLifecycleService._read_json(
            db, project.id, "infrastructure_recovery", "recovery.json")
        InfrastructureLifecycleService._reconcile_events(
            db, project=project, workflow=workflow,
            import_rec=import_rec, recovery_rec=recovery_rec,
            destroy_obs=destroy_obs, destroyed=destroy_run_success,
        )

        # Infrastructure status.
        if destroyed:
            infra_status = INFRA_DESTROYED
        elif boot_failed:
            infra_status = INFRA_FAILED
        elif boot_success:
            infra_status = INFRA_HEALTHY
        else:
            infra_status = INFRA_PENDING

        imported_count = int((import_rec or {}).get("imported_count") or 0)

        terraform_state = TerraformStateView(
            backend_configured=backend_configured,
            backend_type="s3" if backend_configured else None,
            state_bucket=bucket,
            state_key=key,
            workspace="default",
            last_apply=(boot.completed_at if boot_success else None),
            last_destroy=(destroy_obs.completed_at if destroy_run_success else None),
            managed_resources_count=managed_count,
            imported_resources_count=imported_count,
            drift_status="unavailable",
        )

        events = LifecycleEventService.list_for_project(db, project_id=project.id)
        lifecycle_history = [_event_view(e) for e in events]
        recovery_history = InfrastructureLifecycleService._recovery_history(
            events, import_rec=import_rec, recovery_rec=recovery_rec)
        recommendations = InfrastructureLifecycleService._recommendations(recovery_rec)

        # Action availability.
        retry_available = bool(can_manage and boot_failed and has_repo and has_token)

        destroy_block_reason: Optional[str] = None
        if not can_manage:
            destroy_block_reason = "You need engineer or administrator access to destroy."
        elif destroyed:
            destroy_block_reason = "The infrastructure has already been destroyed."
        elif boot_failed:
            destroy_block_reason = "Destroy is blocked while bootstrap is in a failed state — retry or recover first."
        elif boot_running:
            destroy_block_reason = "A run is in progress — wait for it to finish before destroying."
        elif not (has_repo and has_tf and has_token):
            destroy_block_reason = "Destroy needs a repository, generated Terraform, and a GitHub token."
        destroy_available = destroy_block_reason is None

        actions = [
            LifecycleActionView(
                id="retry_bootstrap", label="Retry Bootstrap",
                enabled=retry_available, requires_confirmation=False,
                reason=None if retry_available else "Available only after a failed bootstrap.",
            ),
            LifecycleActionView(
                id="destroy", label="Destroy Infrastructure",
                enabled=destroy_available, requires_confirmation=True,
                reason=destroy_block_reason,
            ),
            LifecycleActionView(id="refresh", label="Refresh", enabled=True),
        ]

        return InfrastructureLifecyclePhaseResponse(
            **base,
            infrastructure_status=infra_status,
            has_repo_url=has_repo,
            has_github_token=has_token,
            has_terraform=has_tf,
            retry_bootstrap_available=retry_available,
            destroy_available=destroy_available,
            destroy_block_reason=destroy_block_reason,
            terraform_state=terraform_state,
            inventory=inventory,
            recovery_history=recovery_history,
            recovery_recommendations=recommendations,
            lifecycle_history=lifecycle_history,
            actions=actions,
            monitoring_available=monitoring_available,
            bootstrap_run=_to_view(boot) if boot else None,
            deploy_run=_to_view(deploy) if deploy else None,
            destroy_run=_to_view(destroy_obs) if destroy_obs else None,
        )

    # ─── Action: retry bootstrap ───────────────────────────────────────────────

    @staticmethod
    def retry_bootstrap(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        actor_id: Optional[str] = None,
        client: Optional[GitHubActionsClient] = None,
        dispatcher: Optional[Dispatcher] = None,
    ) -> LifecycleActionResult:
        """Re-dispatch bootstrap.yml — ONLY when the last bootstrap failed."""
        dispatcher = dispatcher or dispatch_workflow
        repo_url = project.repository_url
        if not repo_url:
            return LifecycleActionResult(status="blocked", message="The project has no repository URL.")
        token = CredentialsService.get_credential(db, project_id=project.id, provider="github_pat")
        if not token:
            return LifecycleActionResult(status="blocked", message="A GitHub token is required to dispatch bootstrap.yml.")

        # Build a client to verify the failed state if not supplied.
        if client is None:
            try:
                client = GitHubActionsClient(token)
            except Exception:  # noqa: BLE001
                client = None
        boot, _ = InfrastructureLifecycleService._observe(project, client, "bootstrap")
        boot_failed = bool(boot and boot.found and boot.status == "completed"
                           and boot.conclusion in _FAILED_CONCLUSIONS)
        if not boot_failed:
            return LifecycleActionResult(
                status="blocked",
                message="Retry is only available after a failed bootstrap run.",
            )

        ref = InfrastructureLifecycleService._default_branch(project)
        try:
            owner, repo = GitHubService._extract_owner_and_repo(repo_url)
        except ValueError as exc:
            return LifecycleActionResult(status="failed", message=str(exc))

        outcome = dispatcher(
            owner=owner, repo=repo, token=token, workflow_file="bootstrap.yml", ref=ref,
        )
        dispatched = bool(getattr(outcome, "dispatched", False))
        event = LifecycleEventService.record(
            db, project_id=project.id, workflow_id=workflow.id,
            event_type=EVENT_BOOTSTRAP_RETRY if dispatched else EVENT_BOOTSTRAP_RETRY_FAILED,
            status="success" if dispatched else "failure",
            summary=("Re-dispatched bootstrap.yml after a failed bootstrap."
                     if dispatched else
                     f"Bootstrap retry not dispatched: {getattr(outcome, 'error', 'unknown error')}"),
            actor_id=actor_id,
            metadata={"ref": ref, "dispatched": dispatched,
                      "error": getattr(outcome, "error", None)},
        )
        return LifecycleActionResult(
            status="ok" if dispatched else "failed",
            message=("Bootstrap re-dispatched — monitoring will show the new run."
                     if dispatched else
                     f"Could not dispatch bootstrap.yml: {getattr(outcome, 'error', 'unknown error')}"),
            event_id=event.id,
            dispatched=dispatched,
        )

    # ─── Action: destroy (two-step confirmation + guards) ──────────────────────

    @staticmethod
    def request_destroy(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        confirm: bool,
        acknowledge_data_loss: bool,
        actor_id: Optional[str] = None,
        client: Optional[GitHubActionsClient] = None,
        installer=None,
        dispatcher=None,
    ) -> LifecycleActionResult:
        """Dispatch destroy.yml after two confirmations + lifecycle guards.

        Never destroys automatically, after a bootstrap failure, while a run is
        in progress, or when already destroyed.
        """
        # Two-step confirmation.
        if not (confirm and acknowledge_data_loss):
            return LifecycleActionResult(
                status="blocked",
                message="Destroy requires explicit two-step confirmation.",
            )

        # Guard: never after bootstrap failure / during a run / when destroyed.
        token = CredentialsService.get_credential(db, project_id=project.id, provider="github_pat")
        if client is None and project.repository_url and token:
            try:
                client = GitHubActionsClient(token)
            except Exception:  # noqa: BLE001
                client = None
        boot, _ = InfrastructureLifecycleService._observe(project, client, "bootstrap")
        if boot and boot.found and boot.status == "completed" and boot.conclusion in _FAILED_CONCLUSIONS:
            return LifecycleActionResult(
                status="blocked",
                message="Cannot destroy after a failed bootstrap — retry or recover first.",
            )
        if boot and boot.found and boot.status in ACTIVE_RUN_STATUSES:
            return LifecycleActionResult(
                status="blocked",
                message="Cannot destroy while a run is in progress.",
            )
        guard = InfrastructureDestroyService.infrastructure_state(db, project)
        if guard.get("destroy_succeeded"):
            return LifecycleActionResult(
                status="blocked", message="The infrastructure has already been destroyed.",
            )

        # Dispatch via the existing destroy service (GitHub Actions runs Terraform).
        try:
            InfrastructureDestroyService.run(
                db, project=project, workflow=workflow, task=task,
                installer=installer, dispatcher=dispatcher,
            )
        except ValueError as exc:
            return LifecycleActionResult(status="blocked", message=str(exc))

        event = LifecycleEventService.record(
            db, project_id=project.id, workflow_id=workflow.id,
            event_type=EVENT_DESTROY_REQUESTED, status="requested",
            summary="Destroy requested — destroy.yml committed and dispatched.",
            actor_id=actor_id,
        )
        return LifecycleActionResult(
            status="ok",
            message="Destroy requested — monitoring will observe the destroy.yml run.",
            event_id=event.id,
        )

    # ─── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _observe(
        project: Project, client: Optional[GitHubActionsClient], kind: str,
    ) -> Tuple[Optional[RunObservation], bool]:
        """Read one pipeline's latest run via the monitoring client. Never raises."""
        if not project.repository_url or client is None:
            return None, False
        try:
            owner, repo = GitHubService._extract_owner_and_repo(project.repository_url)
        except ValueError:
            return None, False
        try:
            obs = WorkflowMonitoringService._observe(client, owner, repo, kind)
        except Exception as exc:  # noqa: BLE001 — observation must never raise
            logger.warning("[Lifecycle] observe %s failed project=%s: %s",
                           kind, project.id, exc.__class__.__name__)
            return None, False
        return obs, obs.available

    @staticmethod
    def _read_json(db: Session, project_id: str, artifact_type: str, subtype: str) -> Optional[dict]:
        row = (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.artifact_type == artifact_type,
                Artifact.artifact_subtype == subtype,
            )
            .first()
        )
        if row is None or not row.content:
            return None
        try:
            return json.loads(row.content)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _default_branch(project: Project) -> str:
        meta = project.project_metadata or {}
        return str(meta.get("default_branch") or "").strip() or "main"

    @staticmethod
    def _reconcile_events(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        import_rec: Optional[dict],
        recovery_rec: Optional[dict],
        destroy_obs: Optional[RunObservation],
        destroyed: bool,
    ) -> None:
        """Materialise import/recovery/destroy outcomes as immutable events once."""
        try:
            if import_rec and int(import_rec.get("imported_count") or 0) >= 0 and import_rec.get("status"):
                key = f"import:{import_rec.get('generated_at') or import_rec.get('status')}:{import_rec.get('imported_count')}"
                count = int(import_rec.get("imported_count") or 0)
                LifecycleEventService.record(
                    db, project_id=project.id, workflow_id=workflow.id,
                    event_type=EVENT_IMPORT_COMPLETED,
                    status="success" if import_rec.get("status") in ("recovered", "partial") else "info",
                    summary=f"Automatic import: {count} resource(s) imported ({import_rec.get('status')}).",
                    duration_ms=import_rec.get("duration_ms"),
                    metadata={"imported_count": count, "result_status": import_rec.get("status")},
                    dedup_key=key, commit=False,
                )

            if recovery_rec and recovery_rec.get("failure_type"):
                key = f"recovery:{recovery_rec.get('generated_at') or recovery_rec.get('failure_type')}"
                LifecycleEventService.record(
                    db, project_id=project.id, workflow_id=workflow.id,
                    event_type=EVENT_RECOVERY_COMPLETED, status="info",
                    summary=f"Recovery analysis: {recovery_rec.get('root_cause') or recovery_rec.get('failure_type')}",
                    metadata={
                        "failure_type": recovery_rec.get("failure_type"),
                        "recommended_action": recovery_rec.get("recommended_action_label"),
                        "recoverable": recovery_rec.get("recoverable"),
                    },
                    dedup_key=key, commit=False,
                )

            if destroyed and destroy_obs and destroy_obs.run_id:
                LifecycleEventService.record(
                    db, project_id=project.id, workflow_id=workflow.id,
                    event_type=EVENT_DESTROY_COMPLETED, status="success",
                    summary="Infrastructure destroy completed successfully.",
                    metadata={"run_id": destroy_obs.run_id},
                    dedup_key=f"destroy_completed:{destroy_obs.run_id}", commit=False,
                )
            elif destroy_obs and destroy_obs.found and destroy_obs.status == "completed" \
                    and destroy_obs.conclusion in _FAILED_CONCLUSIONS and destroy_obs.run_id:
                LifecycleEventService.record(
                    db, project_id=project.id, workflow_id=workflow.id,
                    event_type=EVENT_DESTROY_FAILED, status="failure",
                    summary="Infrastructure destroy run failed.",
                    metadata={"run_id": destroy_obs.run_id, "conclusion": destroy_obs.conclusion},
                    dedup_key=f"destroy_failed:{destroy_obs.run_id}", commit=False,
                )
            db.commit()
        except Exception as exc:  # noqa: BLE001 — reconcile is best-effort
            logger.warning("[Lifecycle] event reconcile failed project=%s: %s",
                           project.id, exc.__class__.__name__)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _recovery_history(
        events, *, import_rec: Optional[dict], recovery_rec: Optional[dict],
    ) -> List[RecoveryAttemptView]:
        """Build the Recovery History table from events + the latest artifacts."""
        recovery_event_types = {
            EVENT_IMPORT_COMPLETED, EVENT_RECOVERY_COMPLETED,
            EVENT_BOOTSTRAP_RETRY, EVENT_BOOTSTRAP_RETRY_FAILED,
        }
        history: List[RecoveryAttemptView] = []
        for e in events:
            if e.event_type not in recovery_event_types:
                continue
            meta = e.event_metadata or {}
            history.append(RecoveryAttemptView(
                timestamp=e.created_at.isoformat() if e.created_at else None,
                detected_issue=meta.get("failure_type") or meta.get("result_status") or e.event_type,
                action_taken=meta.get("recommended_action") or e.summary,
                status=e.status,
                duration_ms=e.duration_ms,
                source="recovery" if e.event_type == EVENT_RECOVERY_COMPLETED
                else "import" if e.event_type == EVENT_IMPORT_COMPLETED else "lifecycle",
            ))
        return history

    @staticmethod
    def _recommendations(recovery_rec: Optional[dict]) -> List[str]:
        if not recovery_rec:
            return []
        recs: List[str] = []
        label = recovery_rec.get("recommended_action_label")
        if label:
            recs.append(label)
        explanation = recovery_rec.get("explanation")
        if explanation:
            recs.append(explanation)
        return recs


# ── Module helpers ───────────────────────────────────────────────────────────


def _event_view(e) -> LifecycleEventView:
    return LifecycleEventView(
        id=e.id,
        event_type=e.event_type,
        status=e.status,
        summary=e.summary or "",
        duration_ms=e.duration_ms,
        actor_id=e.actor_id,
        created_at=e.created_at.isoformat() if e.created_at else None,
        metadata=dict(e.event_metadata or {}),
    )


def _to_view(obs: RunObservation) -> PipelineRunView:
    return PipelineRunView(
        pipeline=obs.pipeline, kind=obs.pipeline, name=obs.name,
        workflow_file=obs.workflow_file, workflow_url=obs.workflow_url,
        available=obs.available, found=obs.found,
        run_id=obs.run_id, run_number=obs.run_number,
        status=obs.status, conclusion=obs.conclusion,
        branch=obs.branch, commit_sha=obs.commit_sha, actor=obs.actor, event=obs.event,
        started_at=obs.started_at, completed_at=obs.completed_at,
        duration_seconds=obs.duration_seconds, html_url=obs.html_url,
        current_job=obs.current_job, current_step=obs.current_step, error=obs.error,
    )
