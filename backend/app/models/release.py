"""Release candidates — immutable snapshots of an approved artifact set.

Why this exists
---------------
Approval is per-artifact. Execution (especially Terraform apply) operates on
a SET of artifacts (``main.tf`` + ``variables.tf`` + ``providers.tf`` + …).
Approving one file does not approve the set. Worse, a reviewer who approves
``main.tf`` at v3 has no guarantee that the executor sees the same v3
content — somebody could have edited the file in the gap.

A ``ReleaseCandidate`` captures the WHOLE set: every required artifact at
its exact content hash and version. The executor consumes the candidate, not
the live ``Artifact`` rows; if anything in the set drifts, the candidate is
no longer ``executable`` and a fresh candidate must be created and re-approved.

This is the missing piece between "we approved some files" and
"this exact build is safe to apply against AWS".

Status machine
--------------
    draft ── all snapshots approved ──▶ approved
      │
      └── any snapshot rejected / a hash drifts ──▶ rejected | superseded

Snapshots are IMMUTABLE. They record what content_hash/version was bound to
the candidate at creation time; they never get rewritten by a later artifact
edit. The candidate's ``status`` IS mutable (draft → approved → executed →
superseded) so the lifecycle is visible without parsing snapshot diffs.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.app.database.base import Base


# JSONB on Postgres; JSON on SQLite — same rationale as ExecutionJob.
_JSON_VARIANT = JSONB().with_variant(JSON(), "sqlite")


class ReleaseCandidate(Base):
    """One candidate ⇒ one apply-able infrastructure release."""

    __tablename__ = "release_candidates"
    # Indexes on project_id / workflow_id are emitted by the Column(index=True)
    # declarations below; no explicit Index() entries are needed (declaring
    # both would attempt to create the same index name twice).

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String, ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # The workflow that produced the artifacts captured by this candidate.
    # SET NULL keeps the candidate alive if the workflow is removed — the
    # snapshot rows still record what was approved.
    workflow_id = Column(
        String, ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # draft        — being assembled / awaiting approvals
    # approved     — every required snapshot is approved AND every snapshot
    #                hash still matches the live artifact hash
    # rejected     — at least one snapshot was rejected
    # executed     — terminal: an executor consumed this candidate
    # superseded   — a fresher candidate exists; this one is historical
    status = Column(String, nullable=False, default="draft", index=True)

    # What the candidate is FOR — e.g. "terraform_apply", "kubernetes_deploy".
    # Drives which artifact types the gate requires (a terraform_apply
    # candidate without a main.tf snapshot is invalid).
    target_phase = Column(String, nullable=False)

    # Free-form release notes — human context for the approver.
    notes = Column(Text, nullable=True)

    # Stamped when the candidate transitions to approved/executed/etc.
    created_by = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)

    # Arbitrary extras (environment tag, region, plan-output hash). Kept out
    # of structured columns so adding a field is data, not migration.
    candidate_metadata = Column(MutableDict.as_mutable(_JSON_VARIANT), nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    snapshots = relationship(
        "ReleaseArtifactSnapshot",
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="ReleaseArtifactSnapshot.artifact_subtype",
    )


class ReleaseArtifactSnapshot(Base):
    """One artifact's frozen state inside a release candidate.

    IMMUTABLE in practice — ``content_hash`` and ``approved_version`` are
    set at creation time and never updated. A candidate is held together by
    the integrity of these snapshots; a future edit to the underlying
    artifact does NOT mutate them, which is precisely how the enforcement
    gate detects drift.
    """

    __tablename__ = "release_artifact_snapshots"
    __table_args__ = (
        # One row per (candidate, artifact). Re-snapshotting the same
        # artifact into the same candidate would create ambiguous truth.
        UniqueConstraint(
            "candidate_id", "artifact_id",
            name="uq_release_snapshot_candidate_artifact",
        ),
        # Indexes on candidate_id / artifact_id come from Column(index=True).
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    candidate_id = Column(
        String, ForeignKey("release_candidates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    artifact_id = Column(
        String, ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Denormalised from the artifact at snapshot time — so a release report
    # is readable without joining back through projects/artifacts. These are
    # the values the gate compares against the live artifact row.
    artifact_type = Column(String, nullable=False)
    artifact_subtype = Column(String, nullable=False)
    snapshot_content_hash = Column(String, nullable=False)
    snapshot_version = Column(Integer, nullable=False)
    # The artifact's approval state at snapshot time. The gate ALSO re-checks
    # the live row at execution time — this column captures the historical
    # state so a release post-mortem can answer "was it approved when we
    # released?" without time-travelling the DB.
    snapshot_approval_state = Column(String, nullable=False, default="pending_review")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    candidate = relationship("ReleaseCandidate", back_populates="snapshots")
