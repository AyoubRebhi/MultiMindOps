-- Phase 3 — durable execution job system.
-- Idempotent: safe to re-run. Purely additive — new table + indexes.
--
-- Apply with:
--   psql -d devsecops_db -f backend/migrations/phase3_execution_jobs.sql
--
-- What this enables
-- -----------------
-- Background operations (Docker build, corrector reanalyze, future Terraform
-- phases) become durable rows instead of fire-and-forget asyncio tasks. A
-- worker claims a job, heartbeats while running, and writes a terminal
-- status. If the worker dies, the reaper re-queues the orphaned job.
--
-- The per-project run lock
-- ------------------------
-- The partial unique index ``uq_execution_jobs_one_running_per_project``
-- enforces AT MOST ONE running job per project at the DATABASE layer. This
-- is the concurrency control that prevents two terraform applies racing on
-- the same state file — even across multiple worker processes, the second
-- claim's UPDATE to status='running' violates the index and is rejected.

BEGIN;

CREATE TABLE IF NOT EXISTS execution_jobs (
    id                  VARCHAR PRIMARY KEY,
    project_id          VARCHAR NOT NULL REFERENCES projects  (id) ON DELETE CASCADE,
    workflow_id         VARCHAR          REFERENCES workflows (id) ON DELETE SET NULL,
    task_id             VARCHAR          REFERENCES tasks     (id) ON DELETE CASCADE,
    phase               VARCHAR NOT NULL,
    status              VARCHAR NOT NULL DEFAULT 'pending',
    cancel_requested    VARCHAR NOT NULL DEFAULT 'false',
    idempotency_key     VARCHAR,
    worker_id           VARCHAR,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    max_retries         INTEGER NOT NULL DEFAULT 3,
    logs_reference      VARCHAR,
    execution_context   JSONB   NOT NULL DEFAULT '{}'::jsonb,
    result_summary      JSONB,
    error_message       TEXT,
    heartbeat_at        TIMESTAMPTZ,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    cancelled_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Claim query: oldest pending job.
CREATE INDEX IF NOT EXISTS ix_execution_jobs_status_created
    ON execution_jobs (status, created_at);
-- Reaper: running jobs whose heartbeat is stale.
CREATE INDEX IF NOT EXISTS ix_execution_jobs_status_heartbeat
    ON execution_jobs (status, heartbeat_at);
CREATE INDEX IF NOT EXISTS ix_execution_jobs_project_id  ON execution_jobs (project_id);
CREATE INDEX IF NOT EXISTS ix_execution_jobs_workflow_id ON execution_jobs (workflow_id);
CREATE INDEX IF NOT EXISTS ix_execution_jobs_task_id     ON execution_jobs (task_id);
CREATE INDEX IF NOT EXISTS ix_execution_jobs_idempotency ON execution_jobs (idempotency_key);

-- ── The per-project run lock ───────────────────────────────────────────────
-- At most one running job per project. Enforced at the DB so the guarantee
-- holds regardless of how many worker processes exist or how they race.
CREATE UNIQUE INDEX IF NOT EXISTS uq_execution_jobs_one_running_per_project
    ON execution_jobs (project_id)
    WHERE status = 'running';

COMMIT;

-- ── Operator notes ─────────────────────────────────────────────────────────
-- * The application worker is started in-process by the API lifespan when
--   EXECUTION_WORKER_ENABLED=true (default). To run a dedicated worker
--   process instead, set EXECUTION_WORKER_ENABLED=false on the API and run:
--     python -m backend.app.workers.execution_worker
-- * Stale-job recovery: a job is considered orphaned when status='running'
--   and heartbeat_at < now() - EXECUTION_JOB_HEARTBEAT_TIMEOUT_SECONDS. The
--   reaper re-queues it (retry_count++) until max_retries, then marks failed.
