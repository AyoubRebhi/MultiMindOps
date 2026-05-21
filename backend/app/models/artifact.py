import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.app.database.base import Base


class Artifact(Base):
    """Persistent generated asset (Dockerfile, Terraform module, K8s manifest, etc.).

    The ``Artifact`` row is the *current* canonical version. Every regeneration
    appends a new ``ArtifactVersion`` row but does NOT overwrite history:
    callers can always trace back through versions to reconstruct what was
    produced when.
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        # An artifact_type/subtype is unique within a project — there's only
        # one "current Dockerfile" at a time. Versions are tracked separately.
        UniqueConstraint(
            "project_id", "artifact_type", "artifact_subtype",
            name="uq_artifact_project_type_subtype",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id = Column(String, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True)

    # docker | terraform | kubernetes | cicd | validation_report | analysis | architecture_plan
    artifact_type = Column(String, nullable=False, index=True)
    # Free-form subtype within a type (e.g. "Dockerfile", "main.tf", "deployment.yaml").
    artifact_subtype = Column(String, nullable=False)

    content = Column(Text, nullable=False, default="")
    # pending | passed | failed | skipped
    validation_status = Column(String, nullable=False, default="pending")
    generated_by_agent = Column(String, nullable=True)
    approved_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    version = Column(Integer, nullable=False, default=1)
    artifact_metadata = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="artifacts")
    workflow = relationship("Workflow", back_populates="artifacts")
    versions = relationship(
        "ArtifactVersion",
        back_populates="artifact",
        cascade="all, delete-orphan",
        order_by="ArtifactVersion.version.desc()",
    )


class ArtifactVersion(Base):
    """Immutable historical record of an artifact at a specific version.

    Regeneration NEVER overwrites a prior ``ArtifactVersion``. The ``Artifact``
    row keeps a pointer-by-id and a denormalized ``version`` column for
    convenience; the truth lives here.
    """

    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint("artifact_id", "version", name="uq_artifact_version_unique"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    artifact_id = Column(String, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False, default="")
    validation_results = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    generated_by = Column(String, nullable=True)
    workflow_id = Column(String, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    artifact = relationship("Artifact", back_populates="versions")
