-- Authentication & session foundation.
-- Idempotent — safe to re-run. Strictly additive: never drops a column,
-- never reshapes existing data. All ADD COLUMN statements use IF NOT EXISTS.
--
-- Apply with:  psql -d devsecops_db -f backend/migrations/auth_foundation.sql
--
-- The schema guard at app boot creates the table-level structure if it is
-- missing, but operators should still run this migration explicitly so
-- production rollouts are deterministic.

-- ── User table: new auth columns ──────────────────────────────────────────
-- Each addition is independent so a partial re-run still completes the
-- remaining columns.
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash         VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url            VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider         VARCHAR NOT NULL DEFAULT 'local';
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified        VARCHAR NOT NULL DEFAULT 'false';
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status        VARCHAR NOT NULL DEFAULT 'active';
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at         TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_by            VARCHAR REFERENCES users (id) ON DELETE SET NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_by            VARCHAR REFERENCES users (id) ON DELETE SET NULL;

-- Legacy rows (created by the dev stub) must be flagged so the password
-- flow rejects them until a password is set.
UPDATE users
   SET auth_provider = 'dev'
 WHERE email = 'dev@devsecops-ai.local'
   AND auth_provider = 'local'
   AND password_hash IS NULL;

-- Email uniqueness + index — both already in the model but spelled out
-- here in case an older deployment missed the unique constraint.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_users_email'
    ) THEN
        BEGIN
            ALTER TABLE users ADD CONSTRAINT uq_users_email UNIQUE (email);
        EXCEPTION WHEN duplicate_table THEN NULL;
        END;
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE INDEX IF NOT EXISTS ix_users_account_status ON users (account_status);

-- ── Sessions table ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_sessions (
    id                  VARCHAR PRIMARY KEY,
    user_id             VARCHAR NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    refresh_token_hash  VARCHAR NOT NULL,
    ip_address          VARCHAR,
    user_agent          VARCHAR,
    expires_at          TIMESTAMPTZ NOT NULL,
    revoked_at          TIMESTAMPTZ,
    last_used_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id            ON user_sessions (user_id);
CREATE INDEX IF NOT EXISTS ix_user_sessions_refresh_token_hash ON user_sessions (refresh_token_hash);
CREATE INDEX IF NOT EXISTS ix_user_sessions_expires_at         ON user_sessions (expires_at);
