"""InfrastructureRecoveryService — read-only diagnosis of a failed provisioning.

When ``bootstrap.yml`` fails during ``terraform apply``, this service produces a
STRUCTURED RECOVERY REPORT. It is purely diagnostic:

    observe the failed bootstrap run   (read-only — reuses the monitoring client)
    → inspect the persisted Terraform artifacts + remote state backend
    → classify the failure              (recovery_classifier — pure function)
    → produce a RecoveryReport + persist it as a recovery artifact

Hard invariants
---------------
* READ-ONLY. It NEVER runs ``terraform apply`` / ``destroy`` / ``import``, never
  triggers/cancels a GitHub Actions run, never touches AWS or the repository.
* NEVER raises. Every failure degrades to a best-effort response (like the
  monitoring surface) — a diagnosis failure must never fail the workflow.
* It does NOT overwrite Terraform artifacts. The report is persisted under its
  own artifact type (``infrastructure_recovery`` / ``recovery.json``).

The persisted ``phases_state[INFRASTRUCTURE_RECOVERY]`` entry is a diagnostic
marker only — it carries no execution semantics and does not gate any phase.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.schemas.infrastructure_recovery_phase import (
    NO_FAILURE_DETECTED,
    RECOVERY_AVAILABLE,
    DetectedResource,
    InfrastructureRecoveryPhaseResponse,
    RecoveryAction,
    RecoveryReport,
)
from backend.app.schemas.workflow_monitoring_phase import PipelineRunView
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.infrastructure_recovery.recovery_classifier import (
    ACTION_IMPORT,
    ACTION_REBUILD_STATE,
    ACTION_RETRY,
    FailureClassification,
    classify_failure,
)
from backend.app.services.repository.github_service import GitHubService
from backend.app.services.workflow_monitoring.github_actions_client import (
    GitHubActionsApiError,
    GitHubActionsClient,
)
from backend.app.services.workflow_monitoring.models import RunObservation
from backend.app.services.workflow_monitoring.monitoring_service import (
    WorkflowMonitoringService,
)

logger = logging.getLogger(__name__)

PHASE = "INFRASTRUCTURE_RECOVERY"
_RECORD_TYPE = "infrastructure_recovery"
_RECORD_SUBTYPE = "recovery.json"

# GitHub run conclusions that count as a recovery-relevant provisioning failure.
# A user-cancelled run is deliberately excluded (it is not a failure to diagnose).
_FAILED_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InfrastructureRecoveryService:
    """Pure, read-only diagnosis. No execution, never raises."""

    # ─── Public read projection ───────────────────────────────────────────────

    @staticmethod
    def get_status(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        client: Optional[GitHubActionsClient] = None,
        failure_log: Optional[str] = None,
    ) -> InfrastructureRecoveryPhaseResponse:
        """Diagnose the failed bootstrap and return a recovery projection.

        Never raises: any failure degrades to a response with ``error`` set and
        ``recovery_available=False``. When a failure is diagnosed, the report is
        persisted (recovery artifact + a diagnostic ``phases_state`` marker).
        """
        base = dict(
            workflow_id=workflow.id,
            project_id=project.id,
            task_id=getattr(task, "id", None),
            current_phase=workflow.current_phase,
            status=workflow.status,
        )
        try:
            return InfrastructureRecoveryService._build(
                db, project=project, workflow=workflow, task=task,
                base=base, client=client, failure_log=failure_log,
            )
        except Exception as exc:  # noqa: BLE001 — diagnosis must never raise
            logger.warning(
                "[InfraRecovery] unexpected failure project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            return InfrastructureRecoveryPhaseResponse(
                **base,
                phase_status=None,
                recovery_available=False,
                error="Could not analyze the failed provisioning right now.",
            )

    # ─── Pure report builder (no I/O — testable in isolation) ──────────────────

    @staticmethod
    def build_report(
        *,
        failure_text: Optional[str],
        terraform_state_available: bool,
        terraform_outputs_available: bool = False,
    ) -> RecoveryReport:
        """Turn a failure blob + inspected state into a structured RecoveryReport.

        Pure function of its inputs — the heart of the diagnosis, kept free of DB
        and network so it is trivially testable.
        """
        cls: FailureClassification = classify_failure(failure_text)
        explanation = InfrastructureRecoveryService._compose_explanation(
            cls, terraform_state_available=terraform_state_available,
        )
        return RecoveryReport(
            status=RECOVERY_AVAILABLE,
            failure_type=cls.failure_type,
            root_cause=cls.root_cause,
            terraform_state_available=terraform_state_available,
            terraform_outputs_available=terraform_outputs_available,
            recoverable=cls.recoverable,
            recommended_action=cls.recommended_action,
            recommended_action_label=cls.recommended_action_label,
            confidence=cls.confidence,
            detected_resources=[
                DetectedResource(
                    resource_type=r.resource_type,
                    identifier=r.identifier,
                    raw=r.raw,
                )
                for r in cls.detected_resources
            ],
            explanation=explanation,
            available_actions=InfrastructureRecoveryService._placeholder_actions(cls),
            generated_at=_utcnow_iso(),
        )

    # ─── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        base: dict,
        client: Optional[GitHubActionsClient],
        failure_log: Optional[str],
    ) -> InfrastructureRecoveryPhaseResponse:
        repo_url = project.repository_url
        has_repo = bool(repo_url)

        tf_files = ArtifactPersistenceService.get_terraform_files(
            db, project_id=project.id
        )
        has_tf = bool(tf_files)
        state_available = _state_backend_available(tf_files)
        outputs_available = bool((tf_files.get("outputs.tf") or "").strip())

        has_token = False
        try:
            has_token = CredentialsService.has_credential(
                db, project_id=project.id, provider="github_pat",
            )
        except Exception:  # noqa: BLE001 — existence probe must never raise
            has_token = False

        # Build the read-only client ONCE (injectable for tests) when possible.
        if client is None and has_repo and has_token:
            try:
                token = CredentialsService.get_credential(
                    db, project_id=project.id, provider="github_pat",
                )
                client = GitHubActionsClient(token) if token else None
            except Exception:  # noqa: BLE001 — degrade if the token can't be read
                client = None

        # Observe the bootstrap run read-only (exactly like monitoring).
        obs, monitoring_available = InfrastructureRecoveryService._observe_bootstrap(
            project, client
        )
        run_failed = bool(
            obs and obs.found and obs.status == "completed"
            and obs.conclusion in _FAILED_CONCLUSIONS
        )

        # Gather every available failure signal for the classifier.
        failure_text = InfrastructureRecoveryService._collect_failure_text(
            workflow=workflow, obs=obs, client=client, project=project,
            failure_log=failure_log,
        )

        # A failure is diagnosable if the run concluded failure OR an explicit
        # failure log/persisted error was supplied.
        diagnosable = run_failed or bool((failure_log or "").strip())

        run_view = _to_view(obs) if obs is not None else None

        if not diagnosable:
            return InfrastructureRecoveryPhaseResponse(
                **base,
                phase_status=NO_FAILURE_DETECTED,
                recovery_available=False,
                failed=False,
                has_repo_url=has_repo,
                has_github_token=has_token,
                has_terraform=has_tf,
                monitoring_available=monitoring_available,
                run=run_view,
                report=None,
            )

        report = InfrastructureRecoveryService.build_report(
            failure_text=failure_text,
            terraform_state_available=state_available,
            terraform_outputs_available=outputs_available,
        )

        # Persist the recovery artifact + a diagnostic phase marker (best-effort).
        InfrastructureRecoveryService._persist(
            db, project=project, workflow=workflow, report=report,
        )

        return InfrastructureRecoveryPhaseResponse(
            **base,
            phase_status=RECOVERY_AVAILABLE,
            recovery_available=True,
            failed=True,
            has_repo_url=has_repo,
            has_github_token=has_token,
            has_terraform=has_tf,
            monitoring_available=monitoring_available,
            run=run_view,
            report=report,
        )

    @staticmethod
    def _observe_bootstrap(
        project: Project, client: Optional[GitHubActionsClient],
    ) -> Tuple[Optional[RunObservation], bool]:
        """Read bootstrap.yml's latest run via the monitoring client. Never raises."""
        repo_url = project.repository_url
        if not repo_url or client is None:
            return None, False
        try:
            owner, repo = GitHubService._extract_owner_and_repo(repo_url)
        except ValueError:
            return None, False
        try:
            obs = WorkflowMonitoringService._observe(client, owner, repo, "bootstrap")
        except Exception as exc:  # noqa: BLE001 — observation must never raise
            logger.warning(
                "[InfraRecovery] observe failed project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            return None, False
        return obs, obs.available

    @staticmethod
    def _collect_failure_text(
        *,
        workflow: Workflow,
        obs: Optional[RunObservation],
        client: Optional[GitHubActionsClient],
        project: Project,
        failure_log: Optional[str],
    ) -> str:
        """Assemble the richest available failure signal for classification.

        Priority order (concatenated, most-specific first):
          1. an explicit failure log supplied by the caller,
          2. persisted ``error`` strings from phases_state,
          3. the failed job/step names from the run (read-only), and the run error.

        The detailed ``terraform apply`` AWS error lives in the GitHub Actions run
        logs (which the backend does not download); when only the run conclusion
        is known, the text is weak and the classification degrades to ``unknown``.
        """
        parts: List[str] = []
        if (failure_log or "").strip():
            parts.append(failure_log.strip())  # type: ignore[union-attr]

        for entry in (workflow.phases_state or {}).values():
            if isinstance(entry, dict) and entry.get("error"):
                parts.append(str(entry["error"]))

        if obs is not None:
            if obs.error:
                parts.append(str(obs.error))
            failed_step = InfrastructureRecoveryService._failed_step(
                project, obs, client
            )
            if failed_step:
                parts.append(f"failed step: {failed_step}")

        return "\n".join(p for p in parts if p)

    @staticmethod
    def _failed_step(
        project: Project,
        obs: RunObservation,
        client: Optional[GitHubActionsClient],
    ) -> Optional[str]:
        """Best-effort name of the failed job/step (read-only). Never raises."""
        if client is None or not obs.run_id or not project.repository_url:
            return None
        try:
            owner, repo = GitHubService._extract_owner_and_repo(project.repository_url)
            jobs = client.run_jobs(owner, repo, obs.run_id)
        except (GitHubActionsApiError, ValueError):
            return None
        except Exception:  # noqa: BLE001 — enrichment is best-effort
            return None
        for job in jobs or []:
            for step in (job or {}).get("steps") or []:
                if (step or {}).get("conclusion") == "failure":
                    name = step.get("name")
                    return f"{job.get('name')} · {name}" if name else job.get("name")
        return None

    @staticmethod
    def _compose_explanation(
        cls: FailureClassification, *, terraform_state_available: bool,
    ) -> str:
        """Augment the class explanation with state-availability context."""
        suffix = (
            " A remote Terraform state backend is configured, so importing the "
            "existing resources into state is possible."
            if terraform_state_available
            else " No remote Terraform state backend was found, so the state may "
            "need to be rebuilt before resources can be reconciled."
        )
        # State context is only meaningful for the resource/state classes.
        from backend.app.schemas.infrastructure_recovery_phase import (
            FAILURE_EXISTING_RESOURCE,
            FAILURE_MISSING_STATE,
        )
        if cls.failure_type in (FAILURE_EXISTING_RESOURCE, FAILURE_MISSING_STATE):
            return cls.explanation + suffix
        return cls.explanation

    @staticmethod
    def _placeholder_actions(cls: FailureClassification) -> List[RecoveryAction]:
        """The three disabled placeholder actions (no backend execution yet)."""
        import_recommended = cls.recommended_action in (ACTION_IMPORT, ACTION_REBUILD_STATE)
        retry_recommended = cls.recommended_action == ACTION_RETRY
        return [
            RecoveryAction(
                id="retry",
                label="Retry",
                description="Re-run the infrastructure provisioning.",
                enabled=False,
                recommended=retry_recommended,
            ),
            RecoveryAction(
                id="import",
                label="Import Existing Resources",
                description="Adopt the already-existing AWS resources into Terraform state.",
                enabled=False,
                recommended=import_recommended,
            ),
            RecoveryAction(
                id="destroy",
                label="Destroy Infrastructure",
                description="Tear down whatever was partially created and start clean.",
                enabled=False,
                recommended=False,
            ),
        ]

    @staticmethod
    def _persist(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        report: RecoveryReport,
    ) -> None:
        """Upsert the recovery.json artifact + a diagnostic phase marker.

        Best-effort: a persistence failure must never affect the response, so it
        is logged and swallowed. Never overwrites Terraform artifacts — the record
        lives under its own ``infrastructure_recovery`` artifact type.
        """
        try:
            ArtifactPersistenceService.upsert_artifact(
                db,
                project_id=project.id,
                workflow_id=workflow.id,
                artifact_type=_RECORD_TYPE,
                artifact_subtype=_RECORD_SUBTYPE,
                content=report.model_dump_json(indent=2),
                generated_by_agent="InfrastructureRecoveryService",
                validation_status="passed",
            )
            phases = dict(workflow.phases_state or {})
            phases[PHASE] = {
                "status": RECOVERY_AVAILABLE,
                "failure_type": report.failure_type,
                "recommended_action": report.recommended_action,
                "recoverable": report.recoverable,
                "confidence": report.confidence,
                "updated_at": _utcnow_iso(),
            }
            workflow.phases_state = phases
            db.commit()
        except Exception as exc:  # noqa: BLE001 — persistence is non-critical
            logger.warning(
                "[InfraRecovery] persist failed project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass


# ── Module helpers ───────────────────────────────────────────────────────────


_BACKEND_S3_RE = re.compile(r'backend\s+"s3"', re.I)
_BACKEND_BUCKET_RE = re.compile(r'bucket\s*=\s*"[^"]+"', re.I)


def _state_backend_available(tf_files: dict) -> bool:
    """True when a real S3 remote-state backend is configured (not a placeholder)."""
    backend = tf_files.get("backend.tf") or ""
    if not backend or "placeholder" in backend.lower():
        return False
    return bool(_BACKEND_S3_RE.search(backend) and _BACKEND_BUCKET_RE.search(backend))


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
