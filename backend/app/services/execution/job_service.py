"""JobService — lifecycle operations for durable execution jobs.

All worker/API interaction with ``execution_jobs`` goes through here. The
service is stateless (the DB session is passed in) and every method commits
its own unit of work so a caller crash never leaves a half-written row.

Concurrency model
------------------
* :meth:`claim_next_job` is the only path that moves a job pending→running.
  It is written to be CORRECT under multiple concurrent workers WITHOUT
  relying on Postgres-only ``SKIP LOCKED``:

    1. Select the oldest pending job whose project has NO running job.
    2. Optimistically UPDATE it to running, guarded by
       ``WHERE status='pending'`` — only one worker's UPDATE affects a row;
       the losers see rowcount 0 and retry.
    3. The DB-level partial unique index
       ``uq_execution_jobs_one_running_per_project`` is the backstop: if two
       workers race two DIFFERENT pending jobs of the SAME project past step
       1, the second UPDATE raises IntegrityError and is rolled back.

  Steps 2+3 together give "at most one running job per project" without a
  global lock. On Postgres a future optimisation could add
  ``SKIP LOCKED``; the current approach is portable to the SQLite test DB.

* The reaper (:meth:`reap_stale_jobs`) re-queues jobs whose worker died
  (heartbeat older than the timeout). It is safe to run from multiple
  workers — each re-queue is guarded by ``WHERE status='running'``.
"""

from __future__ import annotations

import logging
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.execution_job import ExecutionJob
from backend.app.services.core.task_service import _sanitize_for_json

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def generate_worker_id() -> str:
    """A human-traceable worker id: ``host:pid:short-uuid``.

    Lets ops correlate a claimed job with the process that holds it.
    """
    import os
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class JobService:
    """Stateless lifecycle ops for ``execution_jobs``."""

    # ── Enqueue ──────────────────────────────────────────────────────────────

    @staticmethod
    def enqueue(
        db: Session,
        *,
        project_id: str,
        phase: str,
        task_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        execution_context: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
        max_retries: int = 3,
        logs_reference: Optional[str] = None,
    ) -> ExecutionJob:
        """Create a pending job, or return the existing one for an idempotency key.

        Idempotency: if ``idempotency_key`` is supplied and a NON-terminal
        job already exists with that key, the existing job is returned
        unchanged. This dedupes double-clicks / network retries that would
        otherwise enqueue two identical builds.

        Secret scrub: ``execution_context`` is passed through the same
        ``_sanitize_for_json`` used for workflow_state, so a github_token or
        AWS key accidentally placed in the context is stripped before it
        reaches the DB. Handlers re-fetch secrets from the encrypted store
        at run time (Phase 4).
        """
        if idempotency_key:
            existing = (
                db.query(ExecutionJob)
                .filter(
                    ExecutionJob.idempotency_key == idempotency_key,
                    ExecutionJob.status.in_(("pending", "running")),
                )
                .order_by(ExecutionJob.created_at.desc())
                .first()
            )
            if existing is not None:
                logger.info(
                    "[Jobs] enqueue deduped on idempotency_key=%s → existing job=%s status=%s",
                    idempotency_key, existing.id, existing.status,
                )
                return existing

        job = ExecutionJob(
            project_id=project_id,
            workflow_id=workflow_id,
            task_id=task_id,
            phase=phase,
            status="pending",
            cancel_requested="false",
            idempotency_key=idempotency_key,
            retry_count=0,
            max_retries=max_retries,
            logs_reference=logs_reference,
            execution_context=_sanitize_for_json(execution_context or {}),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        logger.info(
            "[Jobs] ENQUEUED job=%s phase=%s project=%s task=%s",
            job.id, phase, project_id, task_id,
        )
        return job

    # ── Claim ────────────────────────────────────────────────────────────────

    @staticmethod
    def claim_next_job(db: Session, *, worker_id: str) -> Optional[ExecutionJob]:
        """Atomically claim the oldest eligible pending job, or return None.

        Eligible = pending AND its project has no currently-running job.
        See the module docstring for the correctness argument. Returns the
        claimed (now-running) job, or None if nothing was claimable this
        round (which is the common idle case — callers just poll again).
        """
        # Projects that currently have a running job are locked out.
        running_project_ids = [
            row[0]
            for row in db.query(ExecutionJob.project_id)
            .filter(ExecutionJob.status == "running")
            .all()
        ]

        candidate_q = (
            db.query(ExecutionJob)
            .filter(ExecutionJob.status == "pending")
        )
        if running_project_ids:
            candidate_q = candidate_q.filter(
                ~ExecutionJob.project_id.in_(running_project_ids)
            )
        candidate = candidate_q.order_by(ExecutionJob.created_at.asc()).first()
        if candidate is None:
            return None

        now = _now()
        # Optimistic claim — only the worker whose UPDATE actually changes
        # the row (status still 'pending') wins.
        try:
            updated = (
                db.query(ExecutionJob)
                .filter(
                    ExecutionJob.id == candidate.id,
                    ExecutionJob.status == "pending",
                )
                .update(
                    {
                        "status": "running",
                        "worker_id": worker_id,
                        "started_at": now,
                        "heartbeat_at": now,
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
        except IntegrityError:
            # The per-project partial-unique index rejected this: another
            # job for the same project went running between our SELECT and
            # UPDATE. Roll back and let the caller poll again.
            db.rollback()
            logger.debug(
                "[Jobs] claim lost race on project lock for job=%s", candidate.id,
            )
            return None

        if not updated:
            # Another worker claimed this exact job first.
            db.rollback()
            return None

        db.refresh(candidate)
        logger.info(
            "[Jobs] CLAIMED job=%s phase=%s project=%s worker=%s",
            candidate.id, candidate.phase, candidate.project_id, worker_id,
        )
        return candidate

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    @staticmethod
    def heartbeat(db: Session, job_id: str) -> bool:
        """Bump ``heartbeat_at`` for a running job. Returns False if the job
        is no longer running (e.g. it was cancelled/reaped out from under
        the worker) so the caller can stop.
        """
        updated = (
            db.query(ExecutionJob)
            .filter(ExecutionJob.id == job_id, ExecutionJob.status == "running")
            .update({"heartbeat_at": _now()}, synchronize_session=False)
        )
        db.commit()
        return bool(updated)

    # ── Terminal transitions ────────────────────────────────────────────────

    @staticmethod
    def mark_succeeded(
        db: Session,
        job_id: str,
        *,
        result_summary: Optional[dict] = None,
    ) -> None:
        job = db.query(ExecutionJob).filter(ExecutionJob.id == job_id).first()
        if job is None:
            return
        job.status = "succeeded"
        job.completed_at = _now()
        job.error_message = None
        if result_summary is not None:
            job.result_summary = _sanitize_for_json(result_summary)
        db.commit()
        logger.info("[Jobs] SUCCEEDED job=%s", job_id)

    @staticmethod
    def mark_failed_or_retry(
        db: Session,
        job_id: str,
        *,
        error_message: str,
        result_summary: Optional[dict] = None,
    ) -> str:
        """Fail the job, re-queuing it if retry budget remains.

        Returns the resulting status ('pending' if re-queued, 'failed' if
        the budget is spent). Re-queue resets the row to pending so the
        worker (this or another) picks it up again.
        """
        job = db.query(ExecutionJob).filter(ExecutionJob.id == job_id).first()
        if job is None:
            return "failed"
        # A cancel that arrived during the run wins over a retry — don't
        # resurrect a job the operator asked to stop.
        if job.cancel_requested_bool:
            return JobService._finalize_cancel(db, job)

        job.error_message = (error_message or "")[:4000]
        if result_summary is not None:
            job.result_summary = _sanitize_for_json(result_summary)

        if job.retry_count < job.max_retries:
            job.retry_count += 1
            job.status = "pending"
            job.worker_id = None
            job.started_at = None
            job.heartbeat_at = None
            db.commit()
            logger.warning(
                "[Jobs] RETRY job=%s attempt=%d/%d: %s",
                job_id, job.retry_count, job.max_retries, error_message[:200],
            )
            return "pending"

        job.status = "failed"
        job.completed_at = _now()
        db.commit()
        logger.error(
            "[Jobs] FAILED job=%s (budget spent %d/%d): %s",
            job_id, job.retry_count, job.max_retries, error_message[:200],
        )
        return "failed"

    # ── Cancellation ────────────────────────────────────────────────────────

    @staticmethod
    def request_cancel(db: Session, job_id: str) -> Optional[str]:
        """Flag a job for cancellation.

        * pending job → transition straight to cancelled (no worker holds it).
        * running job → set ``cancel_requested``; the worker observes it and
          finalises. Returns the resulting/observed status, or None if the
          job does not exist. Terminal jobs are returned unchanged.
        """
        job = db.query(ExecutionJob).filter(ExecutionJob.id == job_id).first()
        if job is None:
            return None
        if job.is_terminal:
            return job.status

        job.cancel_requested = "true"
        if job.status == "pending":
            # No worker holds it — cancel immediately so it never runs.
            return JobService._finalize_cancel(db, job)

        # Running — record the request; the worker's cancel check finalises.
        db.commit()
        logger.info("[Jobs] CANCEL requested for running job=%s", job_id)
        return "running"

    @staticmethod
    def _finalize_cancel(db: Session, job: ExecutionJob) -> str:
        job.status = "cancelled"
        job.cancelled_at = _now()
        job.completed_at = _now()
        db.commit()
        logger.info("[Jobs] CANCELLED job=%s", job.id)
        return "cancelled"

    @staticmethod
    def finalize_cancel_by_id(db: Session, job_id: str) -> Optional[str]:
        """Worker-side: turn a cancel-requested running job into cancelled."""
        job = db.query(ExecutionJob).filter(ExecutionJob.id == job_id).first()
        if job is None:
            return None
        return JobService._finalize_cancel(db, job)

    @staticmethod
    def is_cancel_requested(db: Session, job_id: str) -> bool:
        """Cheap poll used by long-running handlers between steps."""
        row = (
            db.query(ExecutionJob.cancel_requested)
            .filter(ExecutionJob.id == job_id)
            .first()
        )
        if row is None:
            return False
        return (row[0] or "").strip().lower() in ("true", "1", "yes")

    # ── Reaper (crash recovery) ───────────────────────────────────────────────

    @staticmethod
    def reap_stale_jobs(
        db: Session,
        *,
        heartbeat_timeout_seconds: int,
    ) -> int:
        """Re-queue (or fail) running jobs whose worker died.

        A running job whose ``heartbeat_at`` is older than the timeout is
        assumed orphaned (worker crash, OOM, deploy). We route each through
        the same retry logic as a normal failure so the retry budget is
        respected. Returns the number of jobs reaped.

        Idempotent + concurrency-safe: each transition is guarded by
        ``WHERE status='running'`` inside ``mark_failed_or_retry``'s reload.
        """
        cutoff = _now() - timedelta(seconds=heartbeat_timeout_seconds)
        stale = (
            db.query(ExecutionJob)
            .filter(
                ExecutionJob.status == "running",
                # A job that somehow has no heartbeat yet but is running is
                # also reaped — better to re-queue than to wedge a project.
                (ExecutionJob.heartbeat_at.is_(None))
                | (ExecutionJob.heartbeat_at < cutoff),
            )
            .all()
        )
        reaped = 0
        for job in stale:
            logger.warning(
                "[Jobs] REAPING orphaned job=%s worker=%s last_heartbeat=%s",
                job.id, job.worker_id, job.heartbeat_at,
            )
            JobService.mark_failed_or_retry(
                db,
                job.id,
                error_message=(
                    f"Worker {job.worker_id} stopped heartbeating "
                    f"(stale > {heartbeat_timeout_seconds}s) — job reaped."
                ),
            )
            reaped += 1
        if reaped:
            logger.warning("[Jobs] reaped %d orphaned job(s)", reaped)
        return reaped

    # ── Reads ──────────────────────────────────────────────────────────────────

    @staticmethod
    def get(db: Session, job_id: str) -> Optional[ExecutionJob]:
        return db.query(ExecutionJob).filter(ExecutionJob.id == job_id).first()

    @staticmethod
    def list_for_project(
        db: Session,
        project_id: str,
        *,
        limit: int = 50,
    ) -> list[ExecutionJob]:
        return (
            db.query(ExecutionJob)
            .filter(ExecutionJob.project_id == project_id)
            .order_by(ExecutionJob.created_at.desc())
            .limit(limit)
            .all()
        )
