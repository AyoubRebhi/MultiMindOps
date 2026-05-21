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

    # Optional links to the project-centric model. Nullable so legacy tasks
    # created before this migration keep working unattached.
    project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    workflow_id = Column(String, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True)

    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )