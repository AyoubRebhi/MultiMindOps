import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.app.database.base import Base


class Workflow(Base):
    """Execution instance scoped to a Project.

    A Project owns many Workflows. Each Workflow represents one run (or
    re-run) of the orchestration graph or a subset of phases. ``phases_state``
    stores per-phase metadata (status, last artifact_id, last duration, etc.)
    so phase-level reruns can skip unchanged phases without re-executing the
    whole graph.
    """

    __tablename__ = "workflows"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    started_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # ANALYSIS | PLANNING | DOCKER | TERRAFORM | KUBERNETES | VALIDATION | COMPLETE
    current_phase = Column(String, nullable=True)
    # pending | running | awaiting_input | completed | failed | cancelled
    status = Column(String, nullable=False, default="pending")
    # 'full' | 'phase' | 'replay'  — informs which phases run on this instance.
    execution_mode = Column(String, nullable=False, default="full")

    # Per-phase state map: { "DOCKER": {"status": "completed", "artifact_id": "...", ...}, ... }
    phases_state = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    logs = Column(MutableList.as_mutable(JSONB), nullable=False, default=list)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="workflows")
    artifacts = relationship("Artifact", back_populates="workflow")
