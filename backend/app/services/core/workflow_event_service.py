"""WorkflowEventService — append + read the immutable phase event log.

API surface
-----------
* :meth:`append` writes one event. Never updates an existing row.
* :meth:`list_for_workflow` reads the timeline in oldest-first order.
* :meth:`latest` returns the most recent event for a workflow.
* :meth:`derived_current_phase` reconstructs the current phase from the
  event timeline. Equivalent to ``Workflow.current_phase`` when both are
  consistent; preferred over the mutable column for governance decisions
  because it cannot be silently overwritten.

Standardised vocabulary
-----------------------
``phase`` and ``status`` are strings (free-form) so adding a new phase
doesn't require a migration, but call-sites should use the constants below
where applicable so the timeline UI can group events without parsing
ad-hoc strings.
"""

from __future__ import annotations

import logging
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.workflow_event import WorkflowPhaseEvent

logger = logging.getLogger(__name__)


# Well-known phase identifiers — extend as new phases land.
class Phase:
    ARCHITECTURE_DECISION = "ARCHITECTURE_DECISION"
    PLAN_SELECTED         = "PLAN_SELECTED"
    DOCKER                = "DOCKER"
    DOCKER_BUILD          = "DOCKER_BUILD"
    TERRAFORM             = "TERRAFORM"
    TERRAFORM_PLAN        = "TERRAFORM_PLAN"
    TERRAFORM_APPLY       = "TERRAFORM_APPLY"
    TERRAFORM_DESTROY     = "TERRAFORM_DESTROY"
    KUBERNETES            = "KUBERNETES"
    CICD                  = "CICD"
    RELEASE_APPROVED      = "RELEASE_APPROVED"
    RELEASE_REJECTED      = "RELEASE_REJECTED"


class Status:
    STARTED         = "started"
    SUCCEEDED       = "succeeded"
    FAILED          = "failed"
    CANCELLED       = "cancelled"
    AWAITING_INPUT  = "awaiting_input"
    APPROVED        = "approved"
    REJECTED        = "rejected"
    SUPERSEDED      = "superseded"


class WorkflowEventService:
    @staticmethod
    def append(
        db: Session,
        *,
        project_id: str,
        workflow_id: str,
        phase: str,
        status: str,
        actor_user_id: Optional[str] = None,
        message: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> WorkflowPhaseEvent:
        """Insert one immutable event. Returns the persisted row.

        Commits its own unit of work so a partial failure cannot corrupt
        an in-flight transaction in the caller.
        """
        event = WorkflowPhaseEvent(
            project_id=project_id,
            workflow_id=workflow_id,
            phase=phase,
            status=status,
            actor_user_id=actor_user_id,
            message=message,
            payload=payload or {},
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        logger.info(
            "[WorkflowEvent] workflow=%s phase=%s status=%s actor=%s",
            workflow_id, phase, status, actor_user_id,
        )
        return event

    @staticmethod
    def list_for_workflow(
        db: Session, workflow_id: str, *, limit: int = 200,
    ) -> List[WorkflowPhaseEvent]:
        """Return the workflow's timeline oldest-first (chronological)."""
        return (
            db.query(WorkflowPhaseEvent)
            .filter(WorkflowPhaseEvent.workflow_id == workflow_id)
            .order_by(WorkflowPhaseEvent.created_at.asc())
            .limit(limit)
            .all()
        )

    @staticmethod
    def latest(db: Session, workflow_id: str) -> Optional[WorkflowPhaseEvent]:
        return (
            db.query(WorkflowPhaseEvent)
            .filter(WorkflowPhaseEvent.workflow_id == workflow_id)
            .order_by(WorkflowPhaseEvent.created_at.desc())
            .first()
        )

    @staticmethod
    def derived_current_phase(
        db: Session, workflow_id: str,
    ) -> Optional[tuple[str, str]]:
        """Return ``(phase, status)`` derived from the event log.

        This is the canonical truth — the mutable ``Workflow.current_phase``
        column is a denormalised cache. Future code paths that need to
        gate execution decisions should call this, not the column.
        """
        latest = WorkflowEventService.latest(db, workflow_id)
        if latest is None:
            return None
        return (latest.phase, latest.status)
