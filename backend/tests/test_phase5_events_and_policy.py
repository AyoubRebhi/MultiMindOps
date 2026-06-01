"""Phase 5 — event log + execution policy tests.

Two blocks:

1. WorkflowEventService — append-only, derived current phase.
2. ExecutionPolicy — each gate's allow/deny matrix, and policy composition
   (short-circuit vs. exhaustive evaluation).

The policy tests deliberately drive the gates with hand-built
``ExecutionContext`` objects rather than going through the executor —
the executor doesn't exist yet, and the gates' contract is exactly
"given this context, allow or deny with this reason".
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactApproval, ArtifactVersion
from backend.app.models.release import ReleaseArtifactSnapshot, ReleaseCandidate
from backend.app.models.workflow_event import WorkflowPhaseEvent
from backend.app.services.core.artifact_approval_service import ArtifactApprovalService
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.release_service import ReleaseService
from backend.app.services.core.workflow_event_service import (
    Phase,
    Status,
    WorkflowEventService,
)
from backend.app.services.execution.execution_policy import (
    ExecutionContext,
    GateDecision,
    PolicyResult,
    approval_gate,
    environment_isolation_gate,
    evaluate,
    make_severity_gate,
    stale_plan_gate,
    terraform_apply_policy,
)


# ── Fixture for the event-log tests ────────────────────────────────────────


@pytest.fixture
def event_db():
    engine = create_engine("sqlite:///:memory:")
    WorkflowPhaseEvent.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


# ── Fixture for the approval-gate tests (needs artifact + release tables) ──


@pytest.fixture
def gate_db():
    engine = create_engine("sqlite:///:memory:")
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


# ─────────────────────────────────────────────────────────────────────────────
# WorkflowEventService
# ─────────────────────────────────────────────────────────────────────────────


def test_append_creates_immutable_row(event_db):
    e = WorkflowEventService.append(
        event_db, project_id="p1", workflow_id="w1",
        phase=Phase.TERRAFORM_PLAN, status=Status.STARTED,
        actor_user_id="alice", message="plan started",
    )
    assert e.id is not None
    assert e.phase == Phase.TERRAFORM_PLAN
    assert e.status == Status.STARTED
    rows = event_db.query(WorkflowPhaseEvent).all()
    assert len(rows) == 1


def test_list_for_workflow_is_chronological(event_db):
    WorkflowEventService.append(event_db, project_id="p1", workflow_id="w1",
                                phase=Phase.DOCKER, status=Status.STARTED)
    WorkflowEventService.append(event_db, project_id="p1", workflow_id="w1",
                                phase=Phase.DOCKER, status=Status.SUCCEEDED)
    WorkflowEventService.append(event_db, project_id="p1", workflow_id="w1",
                                phase=Phase.TERRAFORM, status=Status.STARTED)
    events = WorkflowEventService.list_for_workflow(event_db, "w1")
    assert [(e.phase, e.status) for e in events] == [
        (Phase.DOCKER, Status.STARTED),
        (Phase.DOCKER, Status.SUCCEEDED),
        (Phase.TERRAFORM, Status.STARTED),
    ]


def test_list_for_workflow_scopes_to_workflow(event_db):
    WorkflowEventService.append(event_db, project_id="p1", workflow_id="w1",
                                phase=Phase.DOCKER, status=Status.STARTED)
    WorkflowEventService.append(event_db, project_id="p1", workflow_id="w2",
                                phase=Phase.DOCKER, status=Status.STARTED)
    assert len(WorkflowEventService.list_for_workflow(event_db, "w1")) == 1
    assert len(WorkflowEventService.list_for_workflow(event_db, "w2")) == 1


def test_derived_current_phase_returns_latest(event_db):
    WorkflowEventService.append(event_db, project_id="p1", workflow_id="w1",
                                phase=Phase.DOCKER, status=Status.SUCCEEDED)
    WorkflowEventService.append(event_db, project_id="p1", workflow_id="w1",
                                phase=Phase.TERRAFORM, status=Status.STARTED)
    assert WorkflowEventService.derived_current_phase(event_db, "w1") == (
        Phase.TERRAFORM, Status.STARTED,
    )


def test_derived_current_phase_none_when_no_events(event_db):
    assert WorkflowEventService.derived_current_phase(event_db, "w-none") is None


# ─────────────────────────────────────────────────────────────────────────────
# Execution policy — individual gates
# ─────────────────────────────────────────────────────────────────────────────


def _make_approved_candidate(db) -> ReleaseCandidate:
    """Build an artifact + approve it + create+approve a candidate around it."""
    tf = ArtifactPersistenceService.upsert_artifact(
        db, project_id="p1", workflow_id=None,
        artifact_type="terraform", artifact_subtype="main.tf",
        content="# tf", generated_by_agent="test",
    )
    db.commit()
    ArtifactApprovalService.record(db, artifact=tf, user_id="u1", action="approve")
    cand = ReleaseService.create_candidate(
        db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )
    ReleaseService.approve(db, cand)
    return cand


def test_approval_gate_allows_executable_candidate(gate_db):
    cand = _make_approved_candidate(gate_db)
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        release_candidate=cand,
    )
    decision = approval_gate(ctx)
    assert decision.allow is True
    assert decision.gate == "approval"


def test_approval_gate_denies_when_no_candidate(gate_db):
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        release_candidate=None,
    )
    decision = approval_gate(ctx)
    assert decision.allow is False
    assert "No release candidate" in decision.reason


def test_approval_gate_denies_when_draft(gate_db):
    """A candidate that would pass evaluate() but is still 'draft' must be
    denied — only formally-approved candidates can execute."""
    tf = ArtifactPersistenceService.upsert_artifact(
        gate_db, project_id="p1", workflow_id=None,
        artifact_type="terraform", artifact_subtype="main.tf",
        content="# tf", generated_by_agent="test",
    )
    gate_db.commit()
    ArtifactApprovalService.record(gate_db, artifact=tf, user_id="u1", action="approve")
    cand = ReleaseService.create_candidate(
        gate_db, project_id="p1", workflow_id=None,
        target_phase="terraform_apply", created_by="u1",
    )  # NOT approved
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        release_candidate=cand,
    )
    decision = approval_gate(ctx)
    assert decision.allow is False


def test_severity_gate_blocks_high_at_default_ceiling(gate_db):
    gate = make_severity_gate(ceiling="high")
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        max_security_severity="critical",
    )
    assert gate(ctx).allow is False
    ctx2 = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        max_security_severity="high",
    )
    assert gate(ctx2).allow is False


def test_severity_gate_allows_warning_at_default_ceiling(gate_db):
    gate = make_severity_gate(ceiling="high")
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        max_security_severity="warning",
    )
    assert gate(ctx).allow is True


def test_severity_gate_denies_when_no_validator_ran(gate_db):
    """Absent severity == no scanner ran. Refusing is the safe default —
    a silently-skipped tfsec is a known prod-incident pattern."""
    gate = make_severity_gate(ceiling="high")
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        max_security_severity=None,
    )
    decision = gate(ctx)
    assert decision.allow is False
    assert "did not run" in decision.reason or "skipped" in decision.reason


def test_severity_gate_custom_ceiling(gate_db):
    """A stricter ceiling rejects 'medium'; a looser ceiling accepts it."""
    strict = make_severity_gate(ceiling="medium")
    loose = make_severity_gate(ceiling="critical")
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        max_security_severity="medium",
    )
    assert strict(ctx).allow is False
    assert loose(ctx).allow is True


def test_stale_plan_gate_allows_matching_hashes(gate_db):
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        plan_hash="abc", approved_plan_hash="abc",
    )
    assert stale_plan_gate(ctx).allow is True


def test_stale_plan_gate_denies_mismatch(gate_db):
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        plan_hash="new", approved_plan_hash="old",
    )
    decision = stale_plan_gate(ctx)
    assert decision.allow is False
    assert "changed since approval" in decision.reason


def test_stale_plan_gate_denies_when_hashes_missing(gate_db):
    """Can't verify what we can't see — refuse rather than wave through."""
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        plan_hash=None, approved_plan_hash=None,
    )
    assert stale_plan_gate(ctx).allow is False


def test_environment_gate_allows_match(gate_db):
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        executor_environment="prod", candidate_environment="prod",
    )
    assert environment_isolation_gate(ctx).allow is True


def test_environment_gate_denies_mismatch(gate_db):
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        executor_environment="prod", candidate_environment="dev",
    )
    decision = environment_isolation_gate(ctx)
    assert decision.allow is False
    assert "does not match" in decision.reason


def test_environment_gate_denies_when_missing(gate_db):
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
    )
    assert environment_isolation_gate(ctx).allow is False


# ── Policy composition ────────────────────────────────────────────────────


def test_evaluate_short_circuits_on_first_denial(gate_db):
    cand = _make_approved_candidate(gate_db)
    # severity will deny (None ⇒ deny); stale_plan would also deny but
    # short_circuit=True should stop after severity.
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        release_candidate=cand,
        max_security_severity=None,
        plan_hash=None, approved_plan_hash=None,
    )
    result = evaluate(ctx, terraform_apply_policy(), short_circuit=True)
    assert result.allowed is False
    # 1st gate (approval) allowed; 2nd (severity) denied — stop.
    assert len(result.decisions) == 2


def test_evaluate_runs_all_when_not_short_circuiting(gate_db):
    cand = _make_approved_candidate(gate_db)
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        release_candidate=cand,
        max_security_severity=None,
        plan_hash=None, approved_plan_hash=None,
    )
    result = evaluate(ctx, terraform_apply_policy(), short_circuit=False)
    assert result.allowed is False
    assert len(result.decisions) == len(terraform_apply_policy())
    assert len(result.denials) >= 1


def test_full_terraform_policy_allows_when_everything_is_green(gate_db):
    cand = _make_approved_candidate(gate_db)
    ctx = ExecutionContext(
        db=gate_db, project_id="p1", target_phase="terraform_apply",
        release_candidate=cand,
        max_security_severity="warning",          # < high ceiling
        plan_hash="abc", approved_plan_hash="abc",
        executor_environment="prod", candidate_environment="prod",
    )
    result = evaluate(ctx, terraform_apply_policy())
    assert result.allowed is True, result.decisions
