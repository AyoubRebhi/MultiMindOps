import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.sql import func

from backend.app.database.base import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    prompt = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="pending")

    plan = Column(MutableDict.as_mutable(JSONB), nullable=True)
    logs = Column(MutableList.as_mutable(JSONB), nullable=False, default=list)
    result = Column(MutableDict.as_mutable(JSONB), nullable=True)
    # Stores the full OrchestratorState between plan-preview and validate-plan
    workflow_state = Column(MutableDict.as_mutable(JSONB), nullable=True)

    # Project link is mandatory — Phase 1 authz unification closed the
    # cross-tenant hole that existed while this column was nullable. Every
    # legacy route that loads a task now also resolves the task's project
    # and runs the role gate against it, so a Task without a project is
    # both unreachable and security-meaningless. The migration
    # ``backend/migrations/phase1_authz_unification.sql`` backfills older
    # rows via the workflow link; rows that cannot be rescued must be
    # resolved by the operator before the migration succeeds.
    # ON DELETE CASCADE: deleting the project removes its tasks because
    # tasks carry no value once detached and SET NULL would re-introduce
    # the nullable hole this migration just closed.
    project_id = Column(
        String,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id = Column(String, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True)

    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )