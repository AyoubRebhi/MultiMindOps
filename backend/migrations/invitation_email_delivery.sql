-- Invitation email delivery: forced password change + send tracking.
-- Idempotent — safe to re-run. Strictly additive: never drops a column,
-- never reshapes existing data. All ADD COLUMN statements use IF NOT EXISTS.
--
-- Apply with:  psql -d devsecops_db -f backend/migrations/invitation_email_delivery.sql
--
-- The schema guard at app boot self-heals these additive columns; operators
-- should still run this migration explicitly so production rollouts are
-- deterministic.

-- ── users: force a password change for invited (temp-password) accounts ────
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password VARCHAR NOT NULL DEFAULT 'false';

-- ── invitations: track email delivery (Phase 8) ───────────────────────────
ALTER TABLE invitations ADD COLUMN IF NOT EXISTS email_status  VARCHAR NOT NULL DEFAULT 'PENDING';
ALTER TABLE invitations ADD COLUMN IF NOT EXISTS email_error   TEXT;
ALTER TABLE invitations ADD COLUMN IF NOT EXISTS email_sent_at TIMESTAMPTZ;
