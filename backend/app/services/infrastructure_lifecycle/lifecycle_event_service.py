"""Append-only persistence for infrastructure-lifecycle events.

Every lifecycle action records ONE immutable row. There is deliberately no
update/delete API — history is never overwritten. ``record`` supports an
optional ``dedup_key`` so reconcile-on-read can materialise an event (e.g. a
destroy run concluding success) exactly once.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.models.lifecycle_event import InfrastructureLifecycleEvent

logger = logging.getLogger(__name__)


class LifecycleEventService:
    """Create + read immutable lifecycle events. No mutation of past rows."""

    @staticmethod
    def record(
        db: Session,
        *,
        project_id: str,
        workflow_id: Optional[str],
        event_type: str,
        status: str = "info",
        summary: str = "",
        duration_ms: Optional[int] = None,
        actor_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        dedup_key: Optional[str] = None,
        commit: bool = True,
    ) -> InfrastructureLifecycleEvent:
        """Append one lifecycle event. Idempotent when ``dedup_key`` is given.

        If a ``dedup_key`` is supplied and a row with it already exists for the
        project, the existing row is returned unchanged (no duplicate, no
        overwrite).
        """
        if dedup_key:
            existing = LifecycleEventService.find_by_dedup(
                db, project_id=project_id, dedup_key=dedup_key
            )
            if existing is not None:
                return existing

        event = InfrastructureLifecycleEvent(
            project_id=project_id,
            workflow_id=workflow_id,
            event_type=event_type,
            status=status,
            summary=summary or "",
            duration_ms=duration_ms,
            actor_id=actor_id,
            event_metadata=dict(metadata or {}),
            dedup_key=dedup_key,
        )
        db.add(event)
        db.flush()
        if commit:
            db.commit()
            db.refresh(event)
        logger.info(
            "[Lifecycle] event project=%s type=%s status=%s",
            project_id, event_type, status,
        )
        return event

    @staticmethod
    def find_by_dedup(
        db: Session, *, project_id: str, dedup_key: str
    ) -> Optional[InfrastructureLifecycleEvent]:
        return (
            db.query(InfrastructureLifecycleEvent)
            .filter(
                InfrastructureLifecycleEvent.project_id == project_id,
                InfrastructureLifecycleEvent.dedup_key == dedup_key,
            )
            .first()
        )

    @staticmethod
    def list_for_project(
        db: Session,
        *,
        project_id: str,
        limit: int = 100,
    ) -> List[InfrastructureLifecycleEvent]:
        """Newest-first lifecycle history for a project."""
        return (
            db.query(InfrastructureLifecycleEvent)
            .filter(InfrastructureLifecycleEvent.project_id == project_id)
            .order_by(InfrastructureLifecycleEvent.created_at.desc())
            .limit(limit)
            .all()
        )
