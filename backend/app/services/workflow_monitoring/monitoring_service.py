"""WorkflowMonitoringService — build the read-only monitoring snapshot.

Responsibilities (in order):

1. Read repository information from the project (``repository_url`` → owner/repo).
2. Fetch the encrypted ``github_pat`` at request time (never persisted to state).
3. Query GitHub Actions for the latest run of ``bootstrap.yml`` + ``deploy.yml``.
4. Match each to its pipeline identity and build the monitoring state.
5. Persist the snapshot as a ``workflow_monitoring`` artifact (best-effort) so a
   later degraded fetch (token revoked, GitHub down) can still show last-known
   state.

Hard invariants:

* READ-ONLY — never triggers/reruns/cancels a workflow, never touches the repo.
* NEVER raises — every failure (no repo, no token, bad token, missing
  permission, deleted repo/workflow, rate limit, network/API error) is captured
  and returned as a degraded :class:`WorkflowMonitoringPhaseResponse`. A
  monitoring failure must never fail the workflow.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.schemas.workflow_monitoring_phase import (
    PipelineRunView,
    WorkflowMonitoringPhaseResponse,
)
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.repository.github_service import GitHubService
from backend.app.services.workflow_monitoring.github_actions_client import (
    GitHubActionsApiError,
    GitHubActionsClient,
)
from backend.app.services.workflow_monitoring.models import (
    ACTIVE_RUN_STATUSES,
    PIPELINES,
    RunObservation,
    compute_duration_seconds,
    now_iso,
)

logger = logging.getLogger(__name__)

_PHASE_KEY = "WORKFLOW_MONITORING"
_ARTIFACT_TYPE = "workflow_monitoring"
_ARTIFACT_SUBTYPE = "monitoring.json"


class WorkflowMonitoringService:
    """Pure observation — no triggering, no mutation, never raises."""

    # ── Public entry point ─────────────────────────────────────────────────────

    @staticmethod
    def build(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        client: Optional[GitHubActionsClient] = None,
    ) -> WorkflowMonitoringPhaseResponse:
        """Assemble the monitoring payload for one workflow. Never raises.

        ``client`` is injectable so tests run without the network; in production
        it is created from the project's ``github_pat``.
        """
        phases_state = workflow.phases_state or {}
        phase_entry = phases_state.get(_PHASE_KEY) or {}
        base = dict(
            workflow_id=workflow.id,
            project_id=project.id,
            task_id=getattr(task, "id", None),
            current_phase=workflow.current_phase,
            status=workflow.status,
            phase_status=phase_entry.get("status"),
            repo_url=project.repository_url,
        )

        try:
            return WorkflowMonitoringService._build_inner(
                db, project=project, workflow=workflow, base=base, client=client,
            )
        except Exception as exc:  # noqa: BLE001 — absolute safety net
            # Monitoring must NEVER raise into the request. Log the class only
            # (never values/secrets) and degrade, falling back to the snapshot.
            logger.warning(
                "[WorkflowMonitoring] unexpected failure project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            return WorkflowMonitoringService._degraded(
                db, base,
                "Could not query GitHub Actions right now. Please try again.",
                project_id=project.id,
            )

    # ── Core build ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_inner(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        base: dict,
        client: Optional[GitHubActionsClient],
    ) -> WorkflowMonitoringPhaseResponse:
        repo_url = project.repository_url
        if not repo_url:
            return WorkflowMonitoringService._degraded(
                db, base,
                "This project has no repository URL, so its GitHub Actions "
                "cannot be monitored.",
                project_id=project.id,
            )

        try:
            owner, repo = GitHubService._extract_owner_and_repo(repo_url)
        except ValueError:
            return WorkflowMonitoringService._degraded(
                db, base,
                "The project repository URL is not a valid GitHub repository.",
                project_id=project.id,
            )

        token = None
        try:
            token = CredentialsService.get_credential(
                db, project_id=project.id, provider="github_pat",
            )
        except Exception as exc:  # noqa: BLE001 — decryption failure → degrade
            logger.warning(
                "[WorkflowMonitoring] github_pat fetch failed project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            token = None
        if not token:
            return WorkflowMonitoringService._degraded(
                db, base,
                "A GitHub token (github_pat credential) is required to read "
                "workflow runs.",
                project_id=project.id,
            )

        client = client or GitHubActionsClient(token)

        # We deliberately do NOT filter by branch: bootstrap runs on a manual
        # workflow_dispatch and deploy on push, so the latest run of each may sit
        # on different branches — report whatever the newest run is.
        boot = WorkflowMonitoringService._observe(client, owner, repo, "bootstrap")
        dep = WorkflowMonitoringService._observe(client, owner, repo, "deploy")

        # Overall availability: only fully unavailable if BOTH pipelines hit a
        # hard (auth/permission/rate-limit/API) error. A 404 (workflow not
        # installed yet / no runs) keeps the surface available.
        monitoring_available = boot.available or dep.available
        overall_error = None
        if not monitoring_available:
            overall_error = boot.error or dep.error

        fetched_at = now_iso()
        WorkflowMonitoringService._persist_snapshot(
            db,
            project=project,
            workflow=workflow,
            boot=boot,
            dep=dep,
            fetched_at=fetched_at,
            monitoring_available=monitoring_available,
            error=overall_error,
        )

        return WorkflowMonitoringPhaseResponse(
            **base,
            monitoring_available=monitoring_available,
            error=overall_error,
            stale=False,
            fetched_at=fetched_at,
            infrastructure=_to_view(boot),
            delivery=_to_view(dep),
        )

    # ── Per-pipeline observation ───────────────────────────────────────────────

    @staticmethod
    def _observe(
        client: GitHubActionsClient,
        owner: str,
        repo: str,
        kind: str,
    ) -> RunObservation:
        """Observe ONE pipeline's latest run. Captures errors, never raises."""
        meta = PIPELINES[kind]
        view = RunObservation(
            pipeline=kind,
            name=meta["name"],
            workflow_file=meta["file"],
            workflow_url=(
                f"https://github.com/{owner}/{repo}/actions/workflows/{meta['file']}"
            ),
            available=True,
        )

        try:
            run = client.latest_run(owner, repo, meta["file"])
        except GitHubActionsApiError as exc:
            if exc.kind == "not_found":
                # The workflow file isn't present yet (not installed / new repo)
                # or there are no runs. Not a hard failure: keep the surface
                # available and report "no runs yet".
                view.found = False
                return view
            # Auth / permission / rate-limit / API → hard error for this pipeline.
            view.available = False
            view.error = str(exc)
            return view

        if not run:
            view.found = False
            return view

        WorkflowMonitoringService._fill_from_run(view, run)

        # OPTIONAL current step — only for an active run, never fail on it.
        if view.status in ACTIVE_RUN_STATUSES and view.run_id:
            try:
                jobs = client.run_jobs(owner, repo, view.run_id)
                job_name, step_name = _current_job_step(jobs)
                view.current_job = job_name
                view.current_step = step_name
            except GitHubActionsApiError:
                pass  # step data is best-effort; the run status still stands

        return view

    @staticmethod
    def _fill_from_run(view: RunObservation, run: dict) -> None:
        """Map a GitHub workflow-run object onto a :class:`RunObservation`."""
        view.found = True
        view.run_id = run.get("id")
        view.run_number = run.get("run_number")
        view.status = run.get("status")
        view.conclusion = run.get("conclusion")
        view.branch = run.get("head_branch")
        view.commit_sha = run.get("head_sha")
        view.event = run.get("event")
        view.html_url = run.get("html_url")
        view.started_at = run.get("run_started_at") or run.get("created_at")
        # The runs list has no explicit completed_at; ``updated_at`` is the run's
        # last transition, which for a completed run is its finish time.
        view.completed_at = (
            run.get("updated_at") if run.get("status") == "completed" else None
        )
        actor = run.get("triggering_actor") or run.get("actor") or {}
        if isinstance(actor, dict):
            view.actor = actor.get("login")
        view.duration_seconds = compute_duration_seconds(
            view.started_at, view.completed_at,
        )

    # ── Persistence + degraded fallback ────────────────────────────────────────

    @staticmethod
    def _persist_snapshot(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        boot: RunObservation,
        dep: RunObservation,
        fetched_at: str,
        monitoring_available: bool,
        error: Optional[str],
    ) -> None:
        """Upsert the durable ``workflow_monitoring`` artifact. Best-effort.

        Persists the last-known monitoring state so a later degraded fetch can
        still render something. A persistence failure must never affect the
        response, so it is logged and swallowed.
        """
        try:
            from backend.app.services.core.artifact_persistence_service import (
                ArtifactPersistenceService,
            )

            payload = {
                "repo_url": project.repository_url,
                "fetched_at": fetched_at,
                "monitoring_available": monitoring_available,
                "error": error,
                "bootstrap": boot.to_dict(),
                "deploy": dep.to_dict(),
            }
            ArtifactPersistenceService.upsert_artifact(
                db,
                project_id=project.id,
                workflow_id=workflow.id,
                artifact_type=_ARTIFACT_TYPE,
                artifact_subtype=_ARTIFACT_SUBTYPE,
                content=json.dumps(payload, indent=2, default=str),
                generated_by_agent="WorkflowMonitoringService",
                validation_status="passed",
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 — persistence is non-critical
            logger.warning(
                "[WorkflowMonitoring] snapshot persist failed project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _load_snapshot(db: Session, project_id: str) -> Optional[dict]:
        """Load the last persisted monitoring snapshot, or None."""
        try:
            row = (
                db.query(Artifact)
                .filter(
                    Artifact.project_id == project_id,
                    Artifact.artifact_type == _ARTIFACT_TYPE,
                    Artifact.artifact_subtype == _ARTIFACT_SUBTYPE,
                )
                .first()
            )
            if row is None or not row.content:
                return None
            return json.loads(row.content)
        except Exception as exc:  # noqa: BLE001 — fallback is best-effort
            logger.warning(
                "[WorkflowMonitoring] snapshot load failed project=%s: %s",
                project_id, exc.__class__.__name__,
            )
            return None

    @staticmethod
    def _degraded(
        db: Session,
        base: dict,
        message: str,
        *,
        project_id: str,
    ) -> WorkflowMonitoringPhaseResponse:
        """Build a degraded response, reusing the last snapshot when available.

        When a prior snapshot exists, its pipeline views are returned with
        ``stale=True`` so the UI shows last-known state alongside the reason the
        live refresh failed. Otherwise it returns empty pipeline placeholders.
        """
        snapshot = WorkflowMonitoringService._load_snapshot(db, project_id)
        if snapshot:
            boot = RunObservation.from_dict(snapshot.get("bootstrap") or {})
            dep = RunObservation.from_dict(snapshot.get("deploy") or {})
            return WorkflowMonitoringPhaseResponse(
                **base,
                monitoring_available=False,
                error=message,
                stale=True,
                fetched_at=snapshot.get("fetched_at"),
                infrastructure=_to_view(boot),
                delivery=_to_view(dep),
            )
        return WorkflowMonitoringPhaseResponse(
            **base,
            monitoring_available=False,
            error=message,
            stale=False,
            fetched_at=None,
            infrastructure=_empty_view("bootstrap"),
            delivery=_empty_view("deploy"),
        )


# ── Module helpers ─────────────────────────────────────────────────────────────


def _current_job_step(jobs: list) -> tuple[Optional[str], Optional[str]]:
    """Derive (current job, current step) from a run's jobs payload.

    Prefers the first in-progress job + its in-progress step (e.g.
    "terraform apply"). Falls back to the last started step of that job so a
    brief gap between steps still shows meaningful progress.
    """
    active = None
    for job in jobs:
        if (job or {}).get("status") in ACTIVE_RUN_STATUSES:
            active = job
            break
    if active is None:
        return None, None

    job_name = active.get("name")
    steps = active.get("steps") or []
    # The actively-executing step is the live one (a queued step is upcoming, not
    # current — so match only ``in_progress`` here, not the broader job-level set).
    for step in steps:
        if (step or {}).get("status") == "in_progress":
            return job_name, step.get("name")
    # Otherwise, the most recent step that has already STARTED (completed or
    # running — never queued/pending) is the best "current" signal.
    started = [
        s for s in steps if (s or {}).get("status") not in (None, "queued", "pending")
    ]
    if started:
        return job_name, started[-1].get("name")
    return job_name, None


def _to_view(obs: RunObservation) -> PipelineRunView:
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


def _empty_view(kind: str) -> PipelineRunView:
    meta = PIPELINES[kind]
    return PipelineRunView(
        pipeline=kind,
        kind=kind,
        name=meta["name"],
        workflow_file=meta["file"],
        available=False,
        found=False,
    )
