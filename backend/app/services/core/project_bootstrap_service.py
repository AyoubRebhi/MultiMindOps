"""ProjectBootstrapService.

Encapsulates the AI bootstrap phase that runs immediately after a user creates
a project. The bootstrap is a small state machine driven by the
``Project.bootstrap_status`` column:

    pending → analyzing → context_building → ready
                                          ↘ failed

``ProjectBootstrapService.create_project_and_bootstrap`` does the synchronous
part (insert Project + ProjectMember + Workflow + Task), which is fast enough
to fit in an HTTP request. ``run_bootstrap_analysis`` runs the slow part
(clone repo, codebase analysis, architecture decision) and is intended to be
scheduled via FastAPI ``BackgroundTasks`` so the create-project response
returns immediately.

Important design notes
----------------------
1. The bootstrap REUSES ``WorkflowOrchestrationService.get_or_create_workflow``.
   We do NOT re-implement orchestration; we wrap it. Going through
   get_or_create (rather than start_workflow directly) enforces one active
   workflow per project, so the bootstrap and the explicit API endpoint can
   never both create one. If a future bootstrap step needs a deviation from the
   workflow path, add a hook here — do not fork the orchestrator.
2. Background tasks run OUTSIDE the request scope. Callers MUST pass a
   factory that yields a fresh ``Session`` (``SessionLocal``) — never reuse
   the request-scoped session. The factory is wired in the route.
3. Failure handling is loud and structured (P9): a single try/except around
   the orchestration call records the exception trace into
   ``Project.bootstrap_error`` and flips ``bootstrap_status`` to ``failed``,
   so the ProjectDetail UI can render a retry action. Never swallow.
"""

from __future__ import annotations

import logging
import traceback
from typing import Callable, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.schemas.project import ProjectCreate
from backend.app.services.core.project_service import ProjectService
from backend.app.services.core.workflow_orchestration_service import (
    WorkflowOrchestrationService,
)

logger = logging.getLogger(__name__)


# Default bootstrap prompt used when the user does not supply one (the new
# minimal create form does not). The orchestrator only really uses this as
# context for the architecture-decision LLM; the heavy lifting is driven by
# the repository analysis.
_DEFAULT_BOOTSTRAP_PROMPT = (
    "Analyze the connected repository, infer the application architecture, "
    "and propose 1-3 deployment strategies with cost estimates."
)


# State machine values — duplicated as constants here to keep the transition
# logic readable and to give callers a typo-proof set.
STATUS_PENDING          = "pending"
STATUS_ANALYZING        = "analyzing"
STATUS_CONTEXT_BUILDING = "context_building"
STATUS_READY            = "ready"
STATUS_FAILED           = "failed"


SessionFactory = Callable[[], Session]


class ProjectBootstrapService:
    """Synchronous create + asynchronous bootstrap analysis.

    Each public method is a single transaction boundary. Background analysis
    opens its own session via the ``session_factory`` callable so it never
    races with the request-scoped session.
    """

    # ─── Synchronous create ──────────────────────────────────────────────────

    @staticmethod
    def create_project_and_bootstrap(
        db: Session,
        owner: User,
        payload: ProjectCreate,
    ) -> Project:
        """Create the Project + owner membership and seed bootstrap state.

        The project is returned with ``bootstrap_status='pending'`` (when no
        repo URL is provided — nothing to analyze) or ``'pending'`` ready to
        flip to ``'analyzing'`` as soon as the caller schedules
        ``run_bootstrap_analysis`` via BackgroundTasks.

        Reuses ``ProjectService.create_project`` for membership insertion so
        owner-bootstrapping rules live in exactly one place.
        """
        project = ProjectService.create_project(db, owner, payload)
        logger.info(
            "[BOOTSTRAP] Created project=%s owner=%s repo=%s visibility=%s",
            project.id,
            owner.id,
            project.repository_url or "(none)",
            project.repository_visibility or "(unspecified)",
        )
        return project

    # ─── Background analysis ─────────────────────────────────────────────────

    @staticmethod
    def run_bootstrap_analysis(
        session_factory: SessionFactory,
        *,
        project_id: str,
        user_id: str,
        prompt: Optional[str] = None,
    ) -> None:
        """Long-running bootstrap step — call from a BackgroundTask.

        Opens a fresh DB session, transitions the project through
        ``analyzing → context_building → ready``, and persists a structured
        ``bootstrap_error`` on failure. Never re-raises: this runs outside the
        request scope, so an uncaught exception would only end up in the
        server log without informing the client. Exceptions are caught,
        logged, and persisted.
        """
        if prompt is None or not prompt.strip():
            prompt = _DEFAULT_BOOTSTRAP_PROMPT

        db = session_factory()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if project is None:
                logger.error(
                    "[BOOTSTRAP] project=%s not found — abandoning analysis",
                    project_id,
                )
                return
            user = db.query(User).filter(User.id == user_id).first()
            if user is None:
                ProjectBootstrapService._fail(
                    db, project,
                    reason=f"Bootstrap user {user_id} not found",
                )
                return

            if not project.repository_url:
                # No repo URL means there's nothing the analyzer can do. Mark
                # the project as ``ready`` (empty bootstrap) so the UI does
                # not get stuck on a spinner — the user can attach a repo
                # later via PATCH /api/projects/{id} and re-trigger.
                project.bootstrap_status = STATUS_READY
                project.bootstrap_error  = None
                db.commit()
                logger.info(
                    "[BOOTSTRAP] project=%s has no repository_url — marked ready",
                    project.id,
                )
                return

            project.bootstrap_status = STATUS_ANALYZING
            project.bootstrap_error  = None
            db.commit()
            logger.info("[BOOTSTRAP] project=%s status=%s", project.id, STATUS_ANALYZING)

            try:
                # get_or_create enforces one active workflow per project: if the
                # user already kicked off a workflow via the API before this
                # background bootstrap ran, we reuse it instead of creating a
                # duplicate (and vice-versa).
                workflow, task, state = WorkflowOrchestrationService.get_or_create_workflow(
                    db,
                    project=project,
                    user=user,
                    prompt=prompt,
                    execution_mode="full",
                )
            except Exception as exc:
                ProjectBootstrapService._fail(
                    db, project,
                    reason=f"{exc.__class__.__name__}: {exc}",
                    trace=traceback.format_exc(),
                )
                return

            # The orchestrator already invoked ProjectContextService inside
            # start_workflow, so the context-building step is effectively
            # complete by the time we get here. We still flip through
            # context_building → ready as discrete states so the frontend can
            # render a richer progress indicator.
            project.bootstrap_status = STATUS_CONTEXT_BUILDING
            db.commit()
            logger.info(
                "[BOOTSTRAP] project=%s status=%s workflow=%s task=%s",
                project.id, STATUS_CONTEXT_BUILDING, workflow.id, task.id,
            )

            project.bootstrap_status = STATUS_READY
            project.bootstrap_error  = None
            project.current_status   = "active"
            db.commit()
            logger.info(
                "[BOOTSTRAP] project=%s status=%s (analysis complete, state=%s)",
                project.id, STATUS_READY, state.get("current_phase") or "n/a",
            )

        finally:
            db.close()

    # ─── Retry helper (used by a future POST /projects/{id}/bootstrap) ──────

    @staticmethod
    def reset_for_retry(db: Session, project: Project) -> Project:
        """Clear failure state so a fresh bootstrap can be scheduled.

        Does NOT itself schedule the retry — the caller still needs to push
        a BackgroundTask. Splitting it that way keeps the route handler in
        charge of asynchrony.
        """
        project.bootstrap_status = STATUS_PENDING
        project.bootstrap_error  = None
        db.commit()
        db.refresh(project)
        logger.info("[BOOTSTRAP] project=%s reset to %s for retry", project.id, STATUS_PENDING)
        return project

    # ─── Internal failure recorder ──────────────────────────────────────────

    @staticmethod
    def _fail(
        db: Session,
        project: Project,
        *,
        reason: str,
        trace: Optional[str] = None,
    ) -> None:
        """Persist a structured bootstrap failure.

        The reason goes in the first line so the frontend can render a short
        message; the (optional) traceback is appended for operator
        diagnostics. Truncated to keep the column tidy — full stack lives in
        the server log.
        """
        body = reason if not trace else f"{reason}\n\n{trace}"
        project.bootstrap_status = STATUS_FAILED
        project.bootstrap_error  = body[:8000]
        project.current_status   = "failed"
        db.commit()
        logger.error(
            "[BOOTSTRAP] project=%s FAILED reason=%s",
            project.id, reason,
        )


# ─── Helpers used by route handlers ─────────────────────────────────────────


def get_session_factory() -> SessionFactory:
    """Return a callable that yields a fresh DB session.

    Defined here (not imported at module load) so test code can monkeypatch
    ``SessionLocal`` without our import order biting back.
    """
    from backend.app.database.session import SessionLocal  # noqa: WPS433

    def _factory() -> Session:
        return SessionLocal()

    return _factory


def schedule_bootstrap(
    background_tasks,
    *,
    project_id: str,
    user_id: str,
    prompt: Optional[str] = None,
) -> None:
    """Push the bootstrap task onto FastAPI's BackgroundTasks.

    Thin wrapper so route handlers don't have to know about the session
    factory plumbing. Importing ``BackgroundTasks`` here would create a
    runtime dep; we type it as ``Any`` instead.
    """
    factory = get_session_factory()
    background_tasks.add_task(
        ProjectBootstrapService.run_bootstrap_analysis,
        session_factory=factory,
        project_id=project_id,
        user_id=user_id,
        prompt=prompt,
    )


__all__ = [
    "ProjectBootstrapService",
    "schedule_bootstrap",
    "get_session_factory",
    "STATUS_PENDING",
    "STATUS_ANALYZING",
    "STATUS_CONTEXT_BUILDING",
    "STATUS_READY",
    "STATUS_FAILED",
]
