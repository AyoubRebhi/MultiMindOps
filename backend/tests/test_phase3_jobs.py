"""Phase 3 — durable execution job system tests.

Exercises JobService against a REAL in-memory SQLite session (not a mock)
because the behaviour worth proving — claim atomicity, the per-project run
lock, heartbeat-expiry reaping, retry budget — is database behaviour. The
ExecutionJob model's JSONB columns fall back to JSON on SQLite (see the
``with_variant`` in the model), which is what makes this possible.

Covered contracts:
* enqueue creates a pending job; idempotency key dedupes.
* claim moves pending→running and stamps worker/started/heartbeat.
* per-project run lock: claim skips projects with a running job; the DB
  partial-unique index rejects a second running job for the same project.
* heartbeat bumps the timestamp and reports loss of the running state.
* mark_succeeded / mark_failed_or_retry (re-queue within budget, fail after).
* request_cancel: pending→cancelled now; running→flagged.
* reap_stale_jobs re-queues orphaned jobs.
* execution_context secret scrub.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.app.models.execution_job import ExecutionJob
from backend.app.services.execution.job_service import JobService


@pytest.fixture
def db():
    """In-memory SQLite with ONLY the execution_jobs table.

    FK targets (projects/workflows/tasks) are not created; SQLite leaves FK
    enforcement off by default, so a job row referencing a non-existent
    project is accepted — fine for testing JobService in isolation.
    """
    engine = create_engine("sqlite:///:memory:")
    ExecutionJob.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _now():
    return datetime.now(timezone.utc)


def _as_naive(dt: datetime) -> datetime:
    """Strip tzinfo for backend-agnostic comparison.

    SQLite (test DB) returns naive datetimes from ``DateTime(timezone=True)``
    columns; Postgres (production) returns tz-aware. The JobService logic is
    correct on both — this helper just lets the test compare timestamps
    without tripping over the naive/aware mismatch.
    """
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


# ── enqueue ─────────────────────────────────────────────────────────────────


def test_enqueue_creates_pending_job(db):
    job = JobService.enqueue(
        db, project_id="p1", phase="docker_build", task_id="t1",
        execution_context={"task_id": "t1"},
    )
    assert job.status == "pending"
    assert job.project_id == "p1"
    assert job.phase == "docker_build"
    assert job.retry_count == 0


def test_enqueue_idempotency_dedupes(db):
    a = JobService.enqueue(
        db, project_id="p1", phase="docker_build",
        idempotency_key="build:t1:1", execution_context={"task_id": "t1"},
    )
    b = JobService.enqueue(
        db, project_id="p1", phase="docker_build",
        idempotency_key="build:t1:1", execution_context={"task_id": "t1"},
    )
    assert a.id == b.id, "second enqueue with same key must return the first job"
    assert db.query(ExecutionJob).count() == 1


def test_enqueue_scrubs_secrets_from_context(db):
    """A github_token accidentally placed in execution_context must be
    stripped before it touches the DB — same scrub as workflow_state."""
    job = JobService.enqueue(
        db, project_id="p1", phase="docker_build",
        execution_context={"task_id": "t1", "github_token": "ghp_leak", "image_tag": "x"},
    )
    assert "github_token" not in job.execution_context
    assert job.execution_context["image_tag"] == "x"


# ── claim ─────────────────────────────────────────────────────────────────────


def test_claim_moves_pending_to_running(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build")
    claimed = JobService.claim_next_job(db, worker_id="w1")
    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.worker_id == "w1"
    assert claimed.started_at is not None
    assert claimed.heartbeat_at is not None


def test_claim_returns_none_when_no_pending(db):
    assert JobService.claim_next_job(db, worker_id="w1") is None


def test_claim_oldest_first(db):
    j1 = JobService.enqueue(db, project_id="pA", phase="docker_build")
    j2 = JobService.enqueue(db, project_id="pB", phase="docker_build")
    claimed = JobService.claim_next_job(db, worker_id="w1")
    assert claimed.id == j1.id, "FIFO — oldest pending job is claimed first"


# ── per-project run lock ──────────────────────────────────────────────────────


def test_claim_skips_project_with_running_job(db):
    """The per-project lock: while P1 has a running job, a second pending
    job for P1 is NOT claimable — but a job for a different project is."""
    JobService.enqueue(db, project_id="p1", phase="docker_build")  # will run
    JobService.enqueue(db, project_id="p1", phase="docker_build")  # blocked by lock
    j_other = JobService.enqueue(db, project_id="p2", phase="docker_build")

    first = JobService.claim_next_job(db, worker_id="w1")
    assert first.project_id == "p1"

    # Next claim must SKIP the second p1 job and take p2's job instead.
    second = JobService.claim_next_job(db, worker_id="w2")
    assert second is not None
    assert second.id == j_other.id
    assert second.project_id == "p2"

    # A third claim finds nothing claimable (p1 still locked, p2 running).
    assert JobService.claim_next_job(db, worker_id="w3") is None


def test_partial_unique_index_rejects_two_running_per_project(db):
    """DB-level backstop: inserting two running jobs for the same project
    violates uq_execution_jobs_one_running_per_project."""
    db.add(ExecutionJob(project_id="p1", phase="docker_build", status="running"))
    db.commit()
    db.add(ExecutionJob(project_id="p1", phase="docker_build", status="running"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_two_running_different_projects_allowed(db):
    """The lock is PER project — different projects run concurrently."""
    db.add(ExecutionJob(project_id="p1", phase="docker_build", status="running"))
    db.add(ExecutionJob(project_id="p2", phase="docker_build", status="running"))
    db.commit()  # must not raise
    assert db.query(ExecutionJob).filter_by(status="running").count() == 2


# ── heartbeat ─────────────────────────────────────────────────────────────────


def test_heartbeat_bumps_timestamp(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build")
    job = JobService.claim_next_job(db, worker_id="w1")
    # Force the stored heartbeat back in time so the bump is observable.
    job.heartbeat_at = _now() - timedelta(seconds=30)
    db.commit()
    assert JobService.heartbeat(db, job.id) is True
    db.refresh(job)
    assert _as_naive(job.heartbeat_at) > _as_naive(_now()) - timedelta(seconds=5)


def test_heartbeat_returns_false_for_non_running(db):
    job = JobService.enqueue(db, project_id="p1", phase="docker_build")
    # Still pending, not running → heartbeat is a no-op signalling "stop".
    assert JobService.heartbeat(db, job.id) is False


# ── terminal transitions ──────────────────────────────────────────────────────


def test_mark_succeeded(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build")
    job = JobService.claim_next_job(db, worker_id="w1")
    JobService.mark_succeeded(db, job.id, result_summary={"ok": True})
    db.refresh(job)
    assert job.status == "succeeded"
    assert job.completed_at is not None
    assert job.result_summary == {"ok": True}


def test_mark_failed_requeues_within_budget(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build", max_retries=2)
    job = JobService.claim_next_job(db, worker_id="w1")
    status = JobService.mark_failed_or_retry(db, job.id, error_message="boom")
    assert status == "pending"
    db.refresh(job)
    assert job.retry_count == 1
    assert job.status == "pending"
    assert job.worker_id is None  # released for re-claim


def test_mark_failed_fails_when_budget_spent(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build", max_retries=1)
    job = JobService.claim_next_job(db, worker_id="w1")
    # First failure → retry (count 1, budget 1)
    JobService.mark_failed_or_retry(db, job.id, error_message="boom1")
    # Re-claim + fail again → budget spent → failed
    again = JobService.claim_next_job(db, worker_id="w1")
    status = JobService.mark_failed_or_retry(db, again.id, error_message="boom2")
    assert status == "failed"
    db.refresh(job)
    assert job.status == "failed"
    assert job.completed_at is not None


def test_failed_does_not_resurrect_a_cancelled_job(db):
    """If a cancel arrived during the run, a subsequent handler error must
    finalise as cancelled, NOT re-queue."""
    JobService.enqueue(db, project_id="p1", phase="docker_build", max_retries=3)
    job = JobService.claim_next_job(db, worker_id="w1")
    JobService.request_cancel(db, job.id)  # running → flagged
    status = JobService.mark_failed_or_retry(db, job.id, error_message="boom")
    assert status == "cancelled"
    db.refresh(job)
    assert job.status == "cancelled"


# ── cancellation ──────────────────────────────────────────────────────────────


def test_cancel_pending_job_is_immediate(db):
    job = JobService.enqueue(db, project_id="p1", phase="docker_build")
    status = JobService.request_cancel(db, job.id)
    assert status == "cancelled"
    db.refresh(job)
    assert job.status == "cancelled"
    assert job.cancelled_at is not None


def test_cancel_running_job_flags_for_worker(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build")
    job = JobService.claim_next_job(db, worker_id="w1")
    status = JobService.request_cancel(db, job.id)
    assert status == "running"  # not yet cancelled — worker finalises
    db.refresh(job)
    assert job.cancel_requested_bool is True
    assert JobService.is_cancel_requested(db, job.id) is True


def test_finalize_cancel_by_id(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build")
    job = JobService.claim_next_job(db, worker_id="w1")
    JobService.request_cancel(db, job.id)
    JobService.finalize_cancel_by_id(db, job.id)
    db.refresh(job)
    assert job.status == "cancelled"


def test_cancel_terminal_job_is_noop(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build")
    job = JobService.claim_next_job(db, worker_id="w1")
    JobService.mark_succeeded(db, job.id)
    status = JobService.request_cancel(db, job.id)
    assert status == "succeeded"  # unchanged


# ── reaper (crash recovery) ───────────────────────────────────────────────────


def test_reap_requeues_orphaned_running_job(db):
    """A running job whose worker died (stale heartbeat) is re-queued."""
    JobService.enqueue(db, project_id="p1", phase="docker_build", max_retries=3)
    job = JobService.claim_next_job(db, worker_id="dead-worker")
    # Simulate the worker dying 5 minutes ago.
    job.heartbeat_at = _now() - timedelta(seconds=300)
    db.commit()

    reaped = JobService.reap_stale_jobs(db, heartbeat_timeout_seconds=60)
    assert reaped == 1
    db.refresh(job)
    assert job.status == "pending"  # re-queued, claimable again
    assert job.retry_count == 1
    assert job.worker_id is None


def test_reap_ignores_fresh_heartbeat(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build")
    job = JobService.claim_next_job(db, worker_id="w1")  # heartbeat = now
    reaped = JobService.reap_stale_jobs(db, heartbeat_timeout_seconds=60)
    assert reaped == 0
    db.refresh(job)
    assert job.status == "running"


def test_reap_then_reclaim_recovers_work(db):
    """End-to-end crash recovery: orphaned job is reaped, then a fresh
    worker can claim it again — the work is not lost."""
    JobService.enqueue(db, project_id="p1", phase="docker_build")
    job = JobService.claim_next_job(db, worker_id="dead")
    job.heartbeat_at = _now() - timedelta(seconds=300)
    db.commit()

    JobService.reap_stale_jobs(db, heartbeat_timeout_seconds=60)
    reclaimed = JobService.claim_next_job(db, worker_id="fresh")
    assert reclaimed is not None
    assert reclaimed.id == job.id
    assert reclaimed.worker_id == "fresh"
    assert reclaimed.status == "running"


# ── reads ─────────────────────────────────────────────────────────────────────


def test_list_for_project_scopes_to_project(db):
    JobService.enqueue(db, project_id="p1", phase="docker_build")
    JobService.enqueue(db, project_id="p1", phase="corrector_reanalyze")
    JobService.enqueue(db, project_id="p2", phase="docker_build")
    p1_jobs = JobService.list_for_project(db, "p1")
    assert len(p1_jobs) == 2
    assert all(j.project_id == "p1" for j in p1_jobs)
