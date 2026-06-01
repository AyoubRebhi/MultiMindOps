"""Durable execution job.

The unit of long-running work. Before Phase 3, background operations were
``asyncio.create_task(...)`` coroutines — they vanished on process restart,
had no idempotency, no per-project mutual exclusion, and no cancellation.
For real infrastructure execution that is unacceptable: an interrupted
``terraform apply`` must be recoverable, never silently lost.

An ``ExecutionJob`` row IS the durable record. A worker claims it, runs the
registered handler for its ``phase``, heartbeats while running, and writes a
terminal status. If the worker dies mid-job, the row survives with a stale
heartbeat; the reaper re-queues it (within the retry budget) so the work is
picked up again instead of being lost.

Status machine
--------------
    pending ──claim──▶ running ──success──▶ succeeded
                          │
                          ├──handler error (retries left)──▶ pending  (re-queued)
                          ├──handler error (budget spent)──▶ failed
                          ├──cancel requested──────────────▶ cancelled
                          └──heartbeat expired (reaper)─────▶ pending / failed

``cancel_requested`` is a separate boolean (not a status) so a cancel can be
recorded on a *running* job without racing the worker's own status writes —
the worker observes the flag between steps and transitions to ``cancelled``.

Concurrency invariant
----------------------
A partial unique index (see the migration) enforces AT MOST ONE row in
status ``running`` per ``project_id``. That is the per-project execution
lock: two ``terraform apply`` jobs for the same project can never run
concurrently, even across multiple worker processes.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func

from backend.app.database.base import Base

# JSONB on Postgres (production), plain JSON on SQLite (tests). The
# ``with_variant`` keeps production behaviour identical while letting the
# test suite create + exercise this table on an in-memory SQLite DB —
# something the other JSONB-only models can't do, which is why the Phase-3
# tests need it (they validate claim atomicity + the run-lock against a
# real session, not a mock).
_JSON_VARIANT = JSONB().with_variant(JSON(), "sqlite")


# Terminal statuses — a job in one of these is done and the reaper ignores it.
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
# Statuses a worker may transition FROM when claiming / running.
ACTIVE_STATUSES = frozenset({"pending", "running"})


class ExecutionJob(Base):
    """One durable background job."""

    __tablename__ = "execution_jobs"
    __table_args__ = (
        # Drives the worker's claim query: "oldest pending job".
        Index("ix_execution_jobs_status_created", "status", "created_at"),
        # Drives the reaper: "running jobs with an old heartbeat".
        Index("ix_execution_jobs_status_heartbeat", "status", "heartbeat_at"),
        # ── The per-project run lock ───────────────────────────────────────
        # At most ONE running job per project, enforced at the DB layer. The
        # partial WHERE clause is expressed for both Postgres (production)
        # and SQLite (tests) so create_all() emits it on either backend.
        # The migration also creates it for deployments that bypass
        # create_all(). A second claim that would put two jobs in 'running'
        # for the same project violates this index and is rejected — that is
        # the cross-process concurrency guarantee.
        Index(
            "uq_execution_jobs_one_running_per_project",
            "project_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Project scope — every job belongs to exactly one project (Phase 1
    # tenancy invariant). CASCADE so deleting a project clears its jobs.
    project_id = Column(
        String,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional workflow link — a job may run outside a formal workflow
    # (e.g. a standalone corrector reanalyze). SET NULL keeps the job row
    # if the workflow is removed.
    workflow_id = Column(
        String,
        ForeignKey("workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The legacy task this job operates on, when applicable. Most Phase-3
    # jobs (docker_build, corrector_reanalyze) are task-scoped.
    task_id = Column(
        String,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Handler selector — "docker_build" | "corrector_reanalyze" | (future)
    # "terraform_plan" | "terraform_apply" | "terraform_destroy".
    phase = Column(String, nullable=False, index=True)

    # pending | running | succeeded | failed | cancelled
    status = Column(String, nullable=False, default="pending", index=True)

    # Cancellation signal. Set by the cancel endpoint; observed by the
    # worker, which terminates the subprocess and transitions to cancelled.
    # Stored as String ('true'/'false') to mirror the codebase's existing
    # stringly-typed boolean convention (see User.is_active).
    cancel_requested = Column(String, nullable=False, default="false")

    # Idempotency — a client-supplied key that dedupes double-submits. A
    # second enqueue with the same key while a non-terminal job exists
    # returns the existing job instead of creating a duplicate.
    idempotency_key = Column(String, nullable=True, index=True)

    # Which worker currently holds the job. NULL when pending. Lets the
    # reaper attribute orphaned jobs and lets ops see who ran what.
    worker_id = Column(String, nullable=True)

    # Retry accounting. retry_count increments each time the job is
    # re-queued after a failure / orphan reap. max_retries caps it.
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=3)

    # Opaque pointer to where this job's logs live (e.g.
    # "workflow_state.execution.docker.logs"). The job row does NOT store
    # log bodies — they can be large and have their own home.
    logs_reference = Column(String, nullable=True)

    # Everything the handler needs to run, MINUS secrets. github_token /
    # AWS creds are NEVER stored here (Phase 4) — handlers re-fetch them
    # from the encrypted credentials store at run time.
    execution_context = Column(MutableDict.as_mutable(_JSON_VARIANT), nullable=False, default=dict)
    # Small terminal summary (root cause, exit code, artifact ids). NOT the
    # full result — that lives in workflow_state.
    result_summary = Column(MutableDict.as_mutable(_JSON_VARIANT), nullable=True)
    # Human-readable failure detail for the last error.
    error_message = Column(Text, nullable=True)

    # Lifecycle timestamps.
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def cancel_requested_bool(self) -> bool:
        return (self.cancel_requested or "").strip().lower() in ("true", "1", "yes")
