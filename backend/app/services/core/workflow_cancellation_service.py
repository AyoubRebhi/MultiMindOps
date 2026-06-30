"""WorkflowCancellationService — cancel a deployment/observation workflow.

An engineer may cancel a workflow that is at one of the post-generation phases —
``GITHUB_ACTIONS_GENERATION``, ``REPOSITORY_INSTALLATION`` or
``WORKFLOW_MONITORING``. Cancellation:

1. cancels any GitHub Actions run still IN FLIGHT for the installed pipelines
   (bootstrap.yml / deploy.yml) via the GitHub Actions *cancel* API — reusing the
   monitoring observation to find the active runs (observe → cancel),
2. marks the workflow ``status = cancelled`` (terminal) + records an audit entry,
3. PRESERVES every generated artifact and the full ``phases_state`` — nothing is
   deleted, no phase's ``completed`` status is overwritten.

Because the artifacts + phase records survive, a cancelled workflow can later be
RESUMED: opening it and re-running any previous phase flips ``status`` back to
``running`` (the phase runners always set it), continuing from where it left off.

The backend never executes Terraform/Docker here; cancellation only talks to the
GitHub Actions API (best-effort) and flips the workflow's own status.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.repository.github_service import GitHubService
from backend.app.services.workflow_monitoring.github_actions_cancel_client import (
    CancelRunOutcome,
    cancel_workflow_run,
)
from backend.app.services.workflow_monitoring.github_actions_client import (
    GitHubActionsClient,
)
from backend.app.services.workflow_monitoring.models import ACTIVE_RUN_STATUSES
from backend.app.services.workflow_monitoring.monitoring_service import (
    WorkflowMonitoringService,
)

logger = logging.getLogger(__name__)

# Phases an engineer may cancel (the deployment + observation tail).
CANCELLABLE_PHASES = {
    "GITHUB_ACTIONS_GENERATION",
    "REPOSITORY_INSTALLATION",
    "WORKFLOW_MONITORING",
}

# The installed pipelines whose live runs a cancellation stops. Each maps to a
# monitoring pipeline ``kind`` (so we reuse the exact observation codepath).
_CANCELLABLE_PIPELINES = ("bootstrap", "deploy")

CANCELLED_STATUS = "cancelled"
_CANCEL_EVENT = "workflow_cancelled"

# Injectable seams (tests pass fakes; production uses the real callables).
Canceller = Callable[..., CancelRunOutcome]


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowCancellationService:
    @staticmethod
    def cancel(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task] = None,
        user_id: Optional[str] = None,
        client: Optional[GitHubActionsClient] = None,
        canceller: Optional[Canceller] = None,
    ) -> dict:
        """Cancel ``workflow`` (at a cancellable phase) — idempotent + non-fatal.

        Raises ``ValueError`` (→ HTTP 400) only when the workflow is not at a
        cancellable phase. Cancelling an already-cancelled workflow is a no-op
        that returns the current state. The GitHub run-cancel is best-effort: a
        permission/network failure never prevents the workflow being marked
        cancelled.
        """
        current = (workflow.current_phase or "").upper()
        if current not in CANCELLABLE_PHASES:
            raise ValueError(
                "This workflow cannot be cancelled from its current phase "
                f"('{workflow.current_phase or 'unknown'}'). Cancellation is "
                "available at the GitHub Actions Generation, Repository "
                "Installation and Workflow Monitoring phases."
            )

        # Idempotent: already cancelled → return current state, cancel nothing.
        if workflow.status == CANCELLED_STATUS:
            return WorkflowCancellationService._summary(
                workflow, cancelled_runs=[], already=True,
            )

        cancelled_runs = WorkflowCancellationService._cancel_active_runs(
            db, project=project, client=client, canceller=canceller,
        )

        # Mark the workflow cancelled. phases_state + artifacts are left UNTOUCHED
        # so the run can be resumed from any previous phase.
        workflow.status = CANCELLED_STATUS
        workflow.finished_at = datetime.now(timezone.utc)
        WorkflowCancellationService._record_cancellation(
            workflow, phase=current, cancelled_runs=cancelled_runs, user_id=user_id,
        )
        db.commit()
        db.refresh(workflow)

        logger.info(
            "[Cancel] workflow=%s project=%s cancelled at phase=%s (runs cancelled=%d)",
            workflow.id, project.id, current,
            sum(1 for r in cancelled_runs if r.get("requested")),
        )
        return WorkflowCancellationService._summary(
            workflow, cancelled_runs=cancelled_runs, already=False,
        )

    # ── GitHub run cancellation (observe → cancel; best-effort) ──────────────

    @staticmethod
    def _cancel_active_runs(
        db: Session,
        *,
        project: Project,
        client: Optional[GitHubActionsClient],
        canceller: Optional[Canceller],
    ) -> List[dict]:
        """Cancel every in-flight bootstrap/deploy run. Never raises.

        Reuses ``WorkflowMonitoringService._observe`` to find each pipeline's
        latest run, then cancels it via the GitHub Actions cancel API only when
        it is still active. Returns one record per pipeline that had an active run.
        """
        repo_url = project.repository_url
        if not repo_url:
            return []
        try:
            owner, repo = GitHubService._extract_owner_and_repo(repo_url)
        except ValueError:
            return []

        token = None
        try:
            token = CredentialsService.get_credential(
                db, project_id=project.id, provider="github_pat",
            )
        except Exception as exc:  # noqa: BLE001 — token read must never break cancel
            logger.warning(
                "[Cancel] github_pat fetch failed project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            token = None
        if not token:
            return []

        client = client or GitHubActionsClient(token)
        canceller = canceller or cancel_workflow_run

        records: List[dict] = []
        for kind in _CANCELLABLE_PIPELINES:
            try:
                obs = WorkflowMonitoringService._observe(client, owner, repo, kind)
            except Exception as exc:  # noqa: BLE001 — observation must never raise
                logger.warning(
                    "[Cancel] observe %s failed project=%s: %s",
                    kind, project.id, exc.__class__.__name__,
                )
                continue
            if obs.found and obs.run_id and obs.status in ACTIVE_RUN_STATUSES:
                outcome = canceller(
                    owner=owner, repo=repo, token=token, run_id=obs.run_id,
                )
                records.append(outcome.to_record(pipeline=kind))
        return records

    # ── Persistence (status + audit log; phases_state untouched) ─────────────

    @staticmethod
    def _record_cancellation(
        workflow: Workflow,
        *,
        phase: str,
        cancelled_runs: List[dict],
        user_id: Optional[str],
    ) -> None:
        """Append a cancellation audit entry to ``Workflow.logs`` (no migration).

        Deliberately does NOT modify ``phases_state``: each phase keeps its
        recorded status (e.g. ``completed``) so the prerequisite gate still lets
        the workflow resume from a previous phase.
        """
        entry = {
            "event": _CANCEL_EVENT,
            "phase": phase,
            "cancelled_runs": list(cancelled_runs),
            "cancelled_by": user_id,
            "cancelled_at": _utcnow_iso(),
        }
        workflow.logs = list(workflow.logs or []) + [entry]

    @staticmethod
    def _summary(workflow: Workflow, *, cancelled_runs: List[dict], already: bool) -> dict:
        requested = sum(1 for r in cancelled_runs if r.get("requested"))
        if already:
            message = "This workflow was already cancelled."
        elif requested:
            message = (
                f"Workflow cancelled. {requested} running GitHub Actions "
                f"run{'s' if requested != 1 else ''} cancelled. All generated "
                "artifacts are preserved."
            )
        else:
            message = (
                "Workflow cancelled. No GitHub Actions run was active. All "
                "generated artifacts are preserved."
            )
        return {
            "workflow_id": workflow.id,
            "project_id": workflow.project_id,
            "status": workflow.status,
            "current_phase": workflow.current_phase,
            "cancelled_at": (
                workflow.finished_at.isoformat()
                if getattr(workflow, "finished_at", None)
                else None
            ),
            "cancelled_runs": cancelled_runs,
            "resumable": True,
            "message": message,
        }
