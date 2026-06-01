-- Phase 5 — workflow phase event log (event-sourcing foundation).
-- Idempotent: safe to re-run. Additive only.
--
-- Apply with:
--   psql -d devsecops_db -f backend/migrations/phase5_workflow_events.sql
--
-- Append-only by convention: there is no service path that UPDATEs or
-- DELETEs from this table. A row is the historical record of one
-- transition; any state change is a new row.

BEGIN;

CREATE TABLE IF NOT EXISTS workflow_phase_events (
    id              VARCHAR PRIMARY KEY,
    project_id      VARCHAR NOT NULL REFERENCES projects  (id) ON DELETE CASCADE,
    workflow_id     VARCHAR NOT NULL REFERENCES workflows (id) ON DELETE CASCADE,
    phase           VARCHAR NOT NULL,
    status          VARCHAR NOT NULL,
    actor_user_id   VARCHAR          REFERENCES users     (id) ON DELETE SET NULL,
    message         TEXT,
    payload         JSONB   NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_wfe_workflow_created
    ON workflow_phase_events (workflow_id, created_at);
CREATE INDEX IF NOT EXISTS ix_wfe_project_created
    ON workflow_phase_events (project_id,  created_at);
CREATE INDEX IF NOT EXISTS ix_wfe_phase
    ON workflow_phase_events (phase);
CREATE INDEX IF NOT EXISTS ix_wfe_actor_user_id
    ON workflow_phase_events (actor_user_id);

COMMIT;
