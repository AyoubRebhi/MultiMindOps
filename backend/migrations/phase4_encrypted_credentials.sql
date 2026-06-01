-- Phase 4 — encrypted per-project credentials.
-- Idempotent: safe to re-run. Purely additive — introduces a new table,
-- never touches existing rows.
--
-- Apply with:
--   psql -d devsecops_db -f backend/migrations/phase4_encrypted_credentials.sql
--
-- Why this lives outside Project.metadata
-- ---------------------------------------
-- Project.metadata is JSONB and is read by every endpoint that returns the
-- project payload (detail view, list, search). Credentials need a stricter
-- access surface AND encryption at rest, so they live in a sibling table
-- with the same project_id FK and an independent lifecycle.
--
-- Schema notes
-- ------------
-- * encrypted_payload is TEXT (not BYTEA). Fernet produces url-safe base64
--   so the stored value round-trips through JSON, pg_dump, and SQLAlchemy
--   without binary quoting. See backend/app/core/encryption.py.
-- * (project_id, provider) is UNIQUE: each provider exists exactly once
--   per project. Rotation = UPDATE on the existing row, not INSERT.
-- * created_by / updated_by are nullable FKs to users — keeps the row
--   alive after the user who created it is removed.

BEGIN;

CREATE TABLE IF NOT EXISTS project_credentials (
    id                  VARCHAR PRIMARY KEY,
    project_id          VARCHAR NOT NULL
                            REFERENCES projects (id) ON DELETE CASCADE,
    provider            VARCHAR NOT NULL,
    encrypted_payload   TEXT    NOT NULL,
    label               VARCHAR,
    created_by          VARCHAR REFERENCES users (id) ON DELETE SET NULL,
    updated_by          VARCHAR REFERENCES users (id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_project_credentials_project_provider
        UNIQUE (project_id, provider)
);

CREATE INDEX IF NOT EXISTS ix_project_credentials_project_id ON project_credentials (project_id);
CREATE INDEX IF NOT EXISTS ix_project_credentials_provider   ON project_credentials (provider);

COMMIT;

-- ── Post-deploy operator checklist ────────────────────────────────────────
-- 1. Set APP_SECRET_KEY in .env (generate with:
--      python -c "from backend.app.core.encryption import generate_app_secret_key; print(generate_app_secret_key())"
--    ). The application refuses any credential write/read until this is set.
-- 2. After deploying this migration + application code, the workflow flow
--    will stop writing github_token into Task.workflow_state. To clean
--    historical rows of leaked secrets, run the one-shot purge:
--      UPDATE tasks
--         SET workflow_state = workflow_state - 'github_token'
--       WHERE workflow_state ? 'github_token';
--    The application no longer reads from that key, so dropping it is safe.
