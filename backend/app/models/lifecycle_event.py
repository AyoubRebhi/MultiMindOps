"""Append-only Infrastructure Lifecycle event log.

Every lifecycle operation (retry bootstrap, destroy request/complete, import
completed, recovery completed) writes ONE immutable row here. Rows are never
updated or deleted — the table is the audit trail of everything that happened to
a project's infrastructure after deployment. Mirrors the append-only convention
already used by ``ArtifactVersion`` / ``ArtifactApproval``.
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func

from backend.app.database.base import Base

# JSONB in production (Postgres); JSON on SQLite (tests). Same pattern as Artifact.
_JSON_VARIANT = JSONB().with_variant(JSON(), "sqlite")


class InfrastructureLifecycleEvent(Base):
    """One immutable infrastructure-lifecycle event for a project/workflow."""

    __tablename__ = "infrastructure_lifecycle_events"
    __table_args__ = (
        # Lookups are always "newest events for this project".
        Index("ix_lifecycle_event_project_created", "project_id", "created_at"),
        # Dedup probe for reconcile-on-read (idempotent event materialisation).
        Index("ix_lifecycle_event_dedup", "project_id", "dedup_key"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id = Column(
        String, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # BOOTSTRAP_RETRY | DESTROY_REQUESTED | DESTROY_COMPLETED | DESTROY_FAILED
    # | IMPORT_COMPLETED | RECOVERY_COMPLETED | BOOTSTRAP_RETRY_FAILED
    event_type = Column(String, nullable=False, index=True)
    # success | failure | requested | info
    status = Column(String, nullable=False, default="info")
    summary = Column(Text, nullable=False, default="")

    # Idempotency key for reconcile-on-read so the same underlying event (e.g. a
    # destroy run concluding success) is never recorded twice.
    dedup_key = Column(String, nullable=True)

    duration_ms = Column(Integer, nullable=True)
    actor_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    event_metadata = Column(MutableDict.as_mutable(_JSON_VARIANT), nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
