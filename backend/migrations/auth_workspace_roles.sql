-- Auth integration: global role + workspace tenant + invitations.
-- Idempotent — safe to re-run. Strictly additive: never drops a column,
-- never reshapes existing data. All ADD COLUMN statements use IF NOT EXISTS.
--
-- Apply with:  psql -d devsecops_db -f backend/migrations/auth_workspace_roles.sql
--
-- The schema guard at app boot self-heals the additive `users` columns and
-- creates the new tables via create_all(); operators should still run this
-- migration explicitly so production rollouts are deterministic.

-- ── users: global role + workspace pointer ────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS role         VARCHAR NOT NULL DEFAULT 'DEVOPS_ENGINEER';
ALTER TABLE users ADD COLUMN IF NOT EXISTS workspace_id VARCHAR;

CREATE INDEX IF NOT EXISTS ix_users_workspace_id ON users (workspace_id);

-- The seeded dev user (when AUTH_ALLOW_DEV_FALLBACK was used) should be ADMIN.
UPDATE users SET role = 'ADMIN'
 WHERE email = 'dev@devsecops-ai.local' AND role <> 'ADMIN';

-- ── workspaces ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workspaces (
    id         VARCHAR PRIMARY KEY,
    name       VARCHAR NOT NULL,
    owner_id   VARCHAR NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    plan       VARCHAR NOT NULL DEFAULT 'Team',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_workspaces_owner_id ON workspaces (owner_id);

-- ── invitations ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invitations (
    id           VARCHAR PRIMARY KEY,
    workspace_id VARCHAR NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    email        VARCHAR NOT NULL,
    role         VARCHAR NOT NULL DEFAULT 'DEVOPS_ENGINEER',
    status       VARCHAR NOT NULL DEFAULT 'pending',
    token        VARCHAR NOT NULL UNIQUE,
    invited_by   VARCHAR REFERENCES users (id) ON DELETE SET NULL,
    message      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    accepted_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_invitations_workspace_id ON invitations (workspace_id);
CREATE INDEX IF NOT EXISTS ix_invitations_email        ON invitations (email);
CREATE INDEX IF NOT EXISTS ix_invitations_token        ON invitations (token);
