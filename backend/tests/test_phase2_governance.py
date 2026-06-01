"""Phase 2 — governance enforcement tests.

Covers:

* ``compute_content_hash`` is deterministic + sensitive to byte changes.
* ``upsert_artifact`` stamps + invalidates approval on content change.
* ``ArtifactApprovalService.record`` binds the approval to the EXACT
  content_hash + version (and clears them on reject).
* ``ReleaseService.create_candidate`` freezes the live artifact set into
  immutable snapshots.
* ``ReleaseService.evaluate`` accepts approved+unchanged candidates, and
  refuses on every drift mode the audit flagged.
* ``approve`` only promotes a candidate that passes ``evaluate``.
* ``mark_executed`` supersedes sibling candidates.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactApproval, ArtifactVersion
from backend.app.models.release import ReleaseArtifactSnapshot, ReleaseCandidate
from backend.app.services.core.artifact_approval_service import ArtifactApprovalService
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
    compute_content_hash,
)
from backend.app.services.core.release_service import (
    ReleaseError,
    ReleaseService,
    require_executable_candidate,
)


# ── Fixture: minimal in-memory schema ──────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    # Order matters — Artifact has FKs to ArtifactVersion / ArtifactApproval.
    # We create the artifact tables first, then the release tables which FK
    # back to them. FK enforcement is off by default on SQLite so a missing
    # projects/users target is tolerated for these unit tests.
    Artifact.__table__.create(engine)
    ArtifactVersion.__table__.create(engine)
    ArtifactApproval.__table__.create(engine)
    ReleaseCandidate.__table__.create(engine)
    ReleaseArtifactSnapshot.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _upsert(db, *, project="p1", subtype="Dockerfile", content="FROM python:3.12", atype="docker"):
    return ArtifactPersistenceService.upsert_artifact(
        db,
        project_id=project,
        workflow_id=None,
        artifact_type=atype,
        artifact_subtype=subtype,
        content=content,
        generated_by_agent="test",
    )


# ── compute_content_hash ───────────────────────────────────────────────────


def test_hash_is_deterministic():
    a = compute_content_hash("FROM python:3.12")
    b = compute_content_hash("FROM python:3.12")
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_hash_changes_with_one_byte():
    assert compute_content_hash("X") != compute_content_hash("Y")


def test_hash_empty_string_is_stable():
    """Defensive: an empty artifact must produce the same hash both ways
    (the persistence layer treats None → '' before hashing)."""
    assert compute_content_hash("") == compute_content_hash("")


# ── upsert + invalidation ──────────────────────────────────────────────────


def test_upsert_stamps_content_hash_on_create(db):
    artifact = _upsert(db, content="FROM python:3.12")
    db.commit()
    assert artifact.content_hash == compute_content_hash("FROM python:3.12")
    versions = db.query(ArtifactVersion).filter_by(artifact_id=artifact.id).all()
    assert len(versions) == 1
    assert versions[0].content_hash == artifact.content_hash


def test_upsert_no_op_when_content_unchanged(db):
    a1 = _upsert(db, content="X")
    db.commit()
    v1 = a1.version
    a2 = _upsert(db, content="X")
    db.commit()
    assert a2.id == a1.id
    assert a2.version == v1
    assert db.query(ArtifactVersion).filter_by(artifact_id=a1.id).count() == 1


def test_upsert_bumps_version_when_content_changes(db):
    a1 = _upsert(db, content="X")
    db.commit()
    a2 = _upsert(db, content="Y")
    db.commit()
    assert a2.version == 2
    assert a2.content_hash == compute_content_hash("Y")
    versions = db.query(ArtifactVersion).filter_by(artifact_id=a1.id).order_by(
        ArtifactVersion.version.asc()).all()
    assert [v.version for v in versions] == [1, 2]
    assert [v.content_hash for v in versions] == [
        compute_content_hash("X"), compute_content_hash("Y"),
    ]


def test_edit_invalidates_existing_approval(db):
    """The core Phase-2 invariant: editing an approved artifact must drop
    its approval so the enforcement gate refuses execution."""
    artifact = _upsert(db, content="OLD")
    db.commit()
    ArtifactApprovalService.record(
        db, artifact=artifact, user_id="reviewer-1", action="approve",
    )
    assert artifact.approval_state == "approved"
    assert artifact.approved_by == "reviewer-1"
    assert artifact.approved_content_hash == compute_content_hash("OLD")

    # Edit — must clear approval pointers.
    _upsert(db, content="NEW")
    db.commit()
    db.refresh(artifact)
    assert artifact.approval_state == "pending_review"
    assert artifact.approved_by is None
    assert artifact.approved_at is None
    assert artifact.approved_content_hash is None


def test_edit_does_not_invalidate_when_never_approved(db):
    """Editing a never-approved artifact stays pending_review (it never
    moved off it). Catches the inverse failure mode of the prior test."""
    artifact = _upsert(db, content="V1")
    db.commit()
    _upsert(db, content="V2")
    db.commit()
    db.refresh(artifact)
    assert artifact.approval_state == "pending_review"


# ── ArtifactApprovalService binding ────────────────────────────────────────


def test_approve_captures_hash_and_version(db):
    artifact = _upsert(db, content="ABC")
    db.commit()
    _, approval = ArtifactApprovalService.record(
        db, artifact=artifact, user_id="u1", action="approve",
    )
    assert approval.approved_content_hash == compute_content_hash("ABC")
    assert approval.approved_version == artifact.version


def test_reject_clears_approval_pointers(db):
    artifact = _upsert(db, content="X")
    db.commit()
    ArtifactApprovalService.record(db, artifact=artifact, user_id="u1", action="approve")
    ArtifactApprovalService.record(db, artifact=artifact, user_id="u2", action="reject")
    db.refresh(artifact)
    assert artifact.approval_state == "rejected"
    assert artifact.approved_by is None
    assert artifact.approved_content_hash is None


def test_request_changes_preserves_history_but_blocks_execution(db):
    """'request_changes' moves state to requires_changes (which the gate
    rejects) but keeps the approval history row intact for audit."""
    artifact = _upsert(db, content="X")
    db.commit()
    ArtifactApprovalService.record(
        db, artifact=artifact, user_id="reviewer", action="request_changes",
        comment="please pin the base image",
    )
    db.refresh(artifact)
    assert artifact.approval_state == "requires_changes"
    rows = db.query(ArtifactApproval).filter_by(artifact_id=artifact.id).all()
    assert len(rows) == 1
    assert rows[0].action == "request_changes"
    assert rows[0].comment == "please pin the base image"


# ── ReleaseService ─────────────────────────────────────────────────────────


def _approve(db, artifact):
    ArtifactApprovalService.record(db, artifact=artifact, user_id="u1", action="approve")


def test_create_candidate_freezes_required_artifacts(db):
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="# tf")
    db.commit()
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    assert cand.status == "draft"
    assert cand.target_phase == "terraform_apply"
    assert len(cand.snapshots) == 1
    s = cand.snapshots[0]
    assert s.artifact_id == tf.id
    assert s.snapshot_content_hash == tf.content_hash
    assert s.snapshot_version == tf.version
    assert s.snapshot_approval_state == "pending_review"


def test_create_candidate_ignores_unrelated_artifact_types(db):
    _upsert(db, atype="terraform", subtype="main.tf", content="# tf")
    _upsert(db, atype="docker", subtype="Dockerfile", content="FROM x")
    db.commit()
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    # Only the terraform artifact is in scope for terraform_apply.
    types = {s.artifact_type for s in cand.snapshots}
    assert types == {"terraform"}


def test_create_candidate_rejects_unknown_target(db):
    with pytest.raises(ReleaseError):
        ReleaseService.create_candidate(
            db, project_id="p1", workflow_id=None,
            target_phase="ssh_into_prod", created_by="u1",
        )


# ── evaluate ───────────────────────────────────────────────────────────────


def test_evaluate_rejects_when_no_required_type_present(db):
    """terraform_apply with no terraform artifacts → not executable."""
    # Live artifacts of a different type don't satisfy the requirement.
    _upsert(db, atype="docker", subtype="Dockerfile", content="FROM x")
    db.commit()
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    decision = ReleaseService.evaluate(db, cand)
    assert decision.executable is False
    assert any("Missing required artifact type" in r for r in decision.reasons)


def test_evaluate_rejects_unapproved_snapshot(db):
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="# tf")
    db.commit()
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    decision = ReleaseService.evaluate(db, cand)
    assert decision.executable is False
    assert any("not approved" in r for r in decision.reasons)


def test_evaluate_accepts_approved_unchanged_snapshot(db):
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="# tf")
    db.commit()
    _approve(db, tf)
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    decision = ReleaseService.evaluate(db, cand)
    assert decision.executable is True, decision.reasons


def test_evaluate_rejects_drift_after_snapshot(db):
    """The audit's edit-after-snapshot risk: a candidate created from
    approved bytes, then the artifact is edited — gate must refuse."""
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="A")
    db.commit()
    _approve(db, tf)
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    # Drift: live content changes after snapshot.
    _upsert(db, atype="terraform", subtype="main.tf", content="B")
    db.commit()

    decision = ReleaseService.evaluate(db, cand)
    assert decision.executable is False
    assert any("content drifted" in r for r in decision.reasons)


def test_evaluate_rejects_when_live_artifact_deleted(db):
    """If the live artifact row was removed after the snapshot, the gate
    refuses — defensive against external DB tampering.

    We delete via raw SQL to bypass the ORM's cascade machinery (which on
    SQLite would try to NULL out the approval FK rather than cascade-delete
    the approval row). The test is about the gate's reaction to a missing
    live row, not about cascade semantics."""
    from sqlalchemy import text as _sql
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="A")
    db.commit()
    _approve(db, tf)
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    artifact_id = tf.id
    db.expire_all()
    # Remove dependents + the artifact row directly.
    db.execute(_sql("DELETE FROM artifact_approvals WHERE artifact_id = :a"), {"a": artifact_id})
    db.execute(_sql("DELETE FROM artifact_versions WHERE artifact_id = :a"), {"a": artifact_id})
    db.execute(_sql("DELETE FROM artifacts WHERE id = :a"), {"a": artifact_id})
    db.commit()
    db.expire_all()

    decision = ReleaseService.evaluate(db, cand)
    assert decision.executable is False
    assert any("no longer exists" in r for r in decision.reasons)


def test_evaluate_rejects_terminal_candidate(db):
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="A")
    db.commit()
    _approve(db, tf)
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    cand.status = "executed"
    db.commit()
    decision = ReleaseService.evaluate(db, cand)
    assert decision.executable is False
    assert any("terminal status" in r for r in decision.reasons)


# ── approve / executed / supersede ─────────────────────────────────────────


def test_approve_promotes_when_executable(db):
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="A")
    db.commit()
    _approve(db, tf)
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    decision = ReleaseService.approve(db, cand)
    assert decision.executable is True
    assert cand.status == "approved"
    assert cand.approved_at is not None


def test_approve_refuses_when_evaluate_fails(db):
    """approve() is the gatekeeper: a draft that doesn't pass evaluate()
    stays draft, with the reasons surfaced to the caller."""
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="A")
    db.commit()  # NOT approved
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    decision = ReleaseService.approve(db, cand)
    assert decision.executable is False
    db.refresh(cand)
    assert cand.status == "draft"  # NOT promoted


def test_require_executable_candidate_demands_approved_status(db):
    """An executable but still-draft candidate is NOT good enough for the
    enforcement gate — only formally approved candidates can execute."""
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="A")
    db.commit()
    _approve(db, tf)
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    decision = require_executable_candidate(db, cand)
    assert decision.executable is False
    assert any("'draft'" in r for r in decision.reasons)
    # After formal approval the gate accepts.
    ReleaseService.approve(db, cand)
    decision2 = require_executable_candidate(db, cand)
    assert decision2.executable is True


def test_mark_executed_supersedes_other_drafts(db):
    tf = _upsert(db, atype="terraform", subtype="main.tf", content="A")
    db.commit()
    _approve(db, tf)

    c1 = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    c2 = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    ReleaseService.approve(db, c1)
    ReleaseService.mark_executed(db, c1)

    db.refresh(c2)
    assert c1.status == "executed"
    assert c2.status == "superseded"
