"""ExecutionWorker — the polling loop that runs durable jobs.

Two ways to run it:

* In-process (default): the API lifespan calls :func:`start_in_process_worker`
  so a single container both serves HTTP and drains the job queue. The
  in-memory log-stream manager is shared, so Docker build log streaming over
  the WebSocket keeps working exactly as before — the only change is that the
  build now runs under a durable job instead of a fire-and-forget task.

* Standalone: ``python -m backend.app.workers.execution_worker`` runs a
  dedicated worker process. Useful once load justifies separating the API
  from execution. (Live WS streaming across processes would then need a
  shared broker; DB log replay still works.)

Loop responsibilities
----------------------
1. On startup, reap stale jobs (crash recovery) so work orphaned by a prior
   crash is re-queued immediately rather than waiting for the first reap tick.
2. Each tick: reap stale jobs, then claim up to ``(max_concurrency - active)``
   jobs and run each as a supervised asyncio task.
3. While a job runs, a supervisor coroutine heartbeats it and watches the
   cancel flag; on cancel it cancels the handler task and finalises the job
   as cancelled.
4. On shutdown (SIGTERM / lifespan exit): stop claiming, let in-flight jobs
   drain up to a grace period, then return. Jobs still running at hard
   timeout are left ``running`` with a fresh-ish heartbeat — the next
   worker reaps them only after the heartbeat actually goes stale.

Per-project mutual exclusion is enforced by the DB (partial unique index)
plus ``JobService.claim_next_job``; the worker does not need its own lock.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

from backend.app.database.session import SessionLocal
from backend.app.services.execution.job_service import JobService, generate_worker_id
from backend.app.workers import handlers as handler_registry

logger = logging.getLogger(__name__)


class ExecutionWorker:
    """A single worker instance. One per process (or per app, in-process)."""

    def __init__(
        self,
        *,
        worker_id: Optional[str] = None,
        poll_interval_seconds: float = 2.0,
        heartbeat_interval_seconds: float = 10.0,
        heartbeat_timeout_seconds: int = 60,
        max_concurrency: int = 2,
        shutdown_grace_seconds: float = 30.0,
    ) -> None:
        self.worker_id = worker_id or generate_worker_id()
        self.poll_interval = poll_interval_seconds
        self.heartbeat_interval = heartbeat_interval_seconds
        self.heartbeat_timeout = heartbeat_timeout_seconds
        self.max_concurrency = max_concurrency
        self.shutdown_grace = shutdown_grace_seconds

        self._stopping = asyncio.Event()
        # job_id → asyncio.Task of the supervised run
        self._active: dict[str, asyncio.Task] = {}
        self._loop_task: Optional[asyncio.Task] = None

    # ── Public control ────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Main loop. Returns when :meth:`request_stop` is called and active
        jobs have drained (or the grace period elapses)."""
        logger.info(
            "[Worker %s] starting — concurrency=%d poll=%.1fs heartbeat=%.1fs timeout=%ds",
            self.worker_id, self.max_concurrency, self.poll_interval,
            self.heartbeat_interval, self.heartbeat_timeout,
        )
        # Startup crash recovery — re-queue anything orphaned by a prior crash.
        self._reap()

        while not self._stopping.is_set():
            try:
                self._reap()
                self._drain_finished()
                self._claim_until_full()
            except Exception:
                # A bad tick must never kill the loop — log and continue.
                logger.exception("[Worker %s] tick error", self.worker_id)
            # Sleep, but wake early if asked to stop.
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.poll_interval)
            except asyncio.TimeoutError:
                pass

        await self._shutdown()

    def request_stop(self) -> None:
        """Signal the loop to stop claiming and begin draining."""
        logger.info("[Worker %s] stop requested", self.worker_id)
        self._stopping.set()

    # ── Internal: claim + run ─────────────────────────────────────────────────

    def _claim_until_full(self) -> None:
        """Claim jobs until concurrency is saturated or nothing is claimable."""
        while len(self._active) < self.max_concurrency and not self._stopping.is_set():
            db = SessionLocal()
            try:
                job = JobService.claim_next_job(db, worker_id=self.worker_id)
            finally:
                db.close()
            if job is None:
                return  # nothing claimable this round
            task = asyncio.create_task(
                self._supervise(job.id, job.phase),
                name=f"job_{job.id[:8]}",
            )
            self._active[job.id] = task

    async def _supervise(self, job_id: str, phase: str) -> None:
        """Run one job's handler with a concurrent heartbeat + cancel watcher."""
        handler = handler_registry.get_handler(phase)
        if handler is None:
            # No handler registered — fail fast so it doesn't sit running.
            db = SessionLocal()
            try:
                JobService.mark_failed_or_retry(
                    db, job_id,
                    error_message=f"No handler registered for phase '{phase}'",
                )
            finally:
                db.close()
            return

        # Reload a detached job instance for the handler.
        db = SessionLocal()
        try:
            job = JobService.get(db, job_id)
        finally:
            db.close()
        if job is None:
            return

        handler_task = asyncio.create_task(handler(job), name=f"handler_{job_id[:8]}")
        heartbeat_task = asyncio.create_task(
            self._heartbeat_until_done(job_id, handler_task),
            name=f"hb_{job_id[:8]}",
        )

        result: Optional[dict] = None
        cancelled = False
        error: Optional[BaseException] = None
        try:
            result = await handler_task
        except asyncio.CancelledError:
            # Either the supervisor cancelled us (job cancel) or shutdown.
            cancelled = True
        except Exception as exc:  # noqa: BLE001 — handler failures are expected
            error = exc
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass

        db = SessionLocal()
        try:
            if cancelled or JobService.is_cancel_requested(db, job_id):
                JobService.finalize_cancel_by_id(db, job_id)
            elif error is not None:
                logger.warning(
                    "[Worker %s] job=%s handler error: %s",
                    self.worker_id, job_id, error,
                )
                JobService.mark_failed_or_retry(
                    db, job_id, error_message=f"{type(error).__name__}: {error}",
                )
            else:
                JobService.mark_succeeded(db, job_id, result_summary=result)
        finally:
            db.close()

    async def _heartbeat_until_done(
        self, job_id: str, handler_task: asyncio.Task,
    ) -> None:
        """Bump the heartbeat on an interval; cancel the handler on a cancel
        request or if the job vanished (reaped out from under us)."""
        while not handler_task.done():
            await asyncio.sleep(self.heartbeat_interval)
            if handler_task.done():
                return
            db = SessionLocal()
            try:
                still_running = JobService.heartbeat(db, job_id)
                cancel = JobService.is_cancel_requested(db, job_id)
            finally:
                db.close()
            if cancel or not still_running:
                # Cancel requested, or the job is no longer 'running' (e.g.
                # reaped). Stop the handler; the supervisor finalises status.
                logger.info(
                    "[Worker %s] cancelling handler job=%s (cancel=%s running=%s)",
                    self.worker_id, job_id, cancel, still_running,
                )
                handler_task.cancel()
                return

    def _drain_finished(self) -> None:
        """Remove completed supervised tasks from the active set."""
        done = [jid for jid, t in self._active.items() if t.done()]
        for jid in done:
            self._active.pop(jid, None)

    def _reap(self) -> None:
        db = SessionLocal()
        try:
            JobService.reap_stale_jobs(
                db, heartbeat_timeout_seconds=self.heartbeat_timeout,
            )
        finally:
            db.close()

    async def _shutdown(self) -> None:
        """Let in-flight jobs drain up to the grace period."""
        if not self._active:
            logger.info("[Worker %s] stopped (no active jobs)", self.worker_id)
            return
        logger.info(
            "[Worker %s] draining %d active job(s), grace=%.0fs",
            self.worker_id, len(self._active), self.shutdown_grace,
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._active.values(), return_exceptions=True),
                timeout=self.shutdown_grace,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[Worker %s] grace expired with %d job(s) still active — leaving "
                "them running; the next worker will reap if the heartbeat goes stale.",
                self.worker_id, len([t for t in self._active.values() if not t.done()]),
            )
        logger.info("[Worker %s] stopped", self.worker_id)


# ── In-process embedding (API lifespan) ──────────────────────────────────────

_in_process_worker: Optional[ExecutionWorker] = None
_in_process_task: Optional[asyncio.Task] = None


def start_in_process_worker(**kwargs) -> ExecutionWorker:
    """Start a worker on the running event loop. Idempotent per process.

    Called from the API lifespan. Returns the worker so the lifespan can
    request a graceful stop on shutdown.
    """
    global _in_process_worker, _in_process_task
    if _in_process_worker is not None:
        return _in_process_worker
    _in_process_worker = ExecutionWorker(**kwargs)
    _in_process_task = asyncio.create_task(
        _in_process_worker.run_forever(), name="execution_worker",
    )
    return _in_process_worker


async def stop_in_process_worker() -> None:
    """Request graceful stop of the in-process worker and await drain."""
    global _in_process_worker, _in_process_task
    if _in_process_worker is None:
        return
    _in_process_worker.request_stop()
    if _in_process_task is not None:
        try:
            await _in_process_task
        except Exception:
            logger.exception("[Worker] error awaiting in-process worker shutdown")
    _in_process_worker = None
    _in_process_task = None


# ── Standalone entrypoint ─────────────────────────────────────────────────────


async def _main_async() -> None:
    from backend.app.core.config import settings

    worker = ExecutionWorker(
        poll_interval_seconds=settings.EXECUTION_JOB_POLL_INTERVAL_SECONDS,
        heartbeat_interval_seconds=settings.EXECUTION_JOB_HEARTBEAT_INTERVAL_SECONDS,
        heartbeat_timeout_seconds=settings.EXECUTION_JOB_HEARTBEAT_TIMEOUT_SECONDS,
        max_concurrency=settings.EXECUTION_WORKER_CONCURRENCY,
    )

    loop = asyncio.get_running_loop()
    # Graceful shutdown on SIGINT/SIGTERM where supported (POSIX). On Windows
    # add_signal_handler raises NotImplementedError — fall back to KeyboardInterrupt.
    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", signal.SIGINT)):
        try:
            loop.add_signal_handler(sig, worker.request_stop)
        except (NotImplementedError, ValueError):
            pass

    await worker.run_forever()


def main() -> None:
    from backend.app.core.config import settings
    from backend.app.core.logging_setup import configure_logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    configure_logging(app_env=settings.APP_ENV, level_override=settings.LOG_LEVEL)
    try:
        asyncio.run(_main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
