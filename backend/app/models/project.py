import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.app.database.base import Base


class Project(Base):
    """Top-level container for an inferred or declared infrastructure target.

    A Project owns workflows, artifacts, members, and reusable context. It is
    the primary entity in the project-centric architecture — workflows are
    execution instances scoped to a project.
    """

    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(String, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)

    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    repository_url = Column(String, nullable=True, index=True)

    # Free-form classifiers chosen at creation time. Stored as strings (not
    # enums) so new architecture types can be introduced from data without a
    # schema migration. Validation happens in the Pydantic layer.
    architecture_type = Column(String, nullable=True)
    application_profile = Column(String, nullable=True)
    default_strategy_tier = Column(String, nullable=True, default="balanced")

    # current_status reflects the *project lifecycle*, not the latest workflow.
    # Values: 'draft' | 'active' | 'archived' | 'failed'.
    current_status = Column(String, nullable=False, default="draft")

    # AI bootstrap state machine — independent from current_status because the
    # project can be 'active' (lifecycle) while a re-bootstrap is 'analyzing'.
    # Values: 'pending' | 'analyzing' | 'context_building' | 'ready' | 'failed'.
    # See backend/app/services/core/project_bootstrap_service.py for the
    # canonical transitions and ProjectBootstrapStatus in schemas/project.py
    # for the Pydantic enum exposed to the frontend.
    bootstrap_status = Column(String, nullable=False, default="pending")
    # Last bootstrap failure trace — preserved so ProjectDetail can render
    # "Analysis failed" with a retry action and the operator has a structured
    # error to investigate. Cleared on a successful re-bootstrap.
    bootstrap_error = Column(Text, nullable=True)

    # Repository visibility chosen at creation time. Drives which credentials
    # the analyzer attempts to use. 'public' | 'private'.
    repository_visibility = Column(String, nullable=True)

    project_metadata = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    members = relationship(
        "ProjectMember",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    workflows = relationship(
        "Workflow",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    artifacts = relationship(
        "Artifact",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    contexts = relationship(
        "ProjectContext",
        back_populates="project",
        cascade="all, delete-orphan",
    )


class ProjectMember(Base):
    """Project membership with a role.

    A user may belong to many projects with different roles. Role authorization
    is enforced at the API layer; storing it relationally keeps the lookup
    cheap and avoids embedding role grants in a JWT.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member_unique"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # OWNER | DEVELOPER | CLOUD_ARCHITECT | ADMIN | VIEWER
    role = Column(String, nullable=False, default="DEVELOPER")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="members")


class ProjectContext(Base):
    """Persistent reusable context attached to a project.

    Examples: codebase analysis summary, architecture summary, Terraform
    topology summary, Docker hints, validation rollups. The point is reuse —
    a workflow rerun should consult ProjectContext rather than re-invoking
    the analysis agents from scratch.
    """

    __tablename__ = "project_contexts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    context_type = Column(String, nullable=False, index=True)
    content = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    generated_by = Column(String, nullable=True)
    # Pointer into a vector store / RAG layer when relevant; null for plain JSON context.
    embedding_reference = Column(String, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="contexts")
