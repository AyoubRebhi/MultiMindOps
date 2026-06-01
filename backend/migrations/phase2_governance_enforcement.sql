-- Phase 2 — governance enforcement.
-- Idempotent. Additive — new columns + new tables only.
--
-- Apply with:
--   psql -d devsecops_db -f backend/migrations/phase2_governance_enforcement.sql
--
-- What this does
-- --------------
-- 1. Adds content_hash to artifacts + artifact_versions so the enforcement
--    gate can detect "what was approved" vs. "what is about to execute".
-- 2. Adds approved_content_hash + approved_at on artifacts and
--    approved_content_hash + approved_version on artifact_approvals so an
--    approval is bound to the exact bytes the reviewer saw.
-- 3. Creates the release_candidates + release_artifact_snapshots tables so
--    execution can operate on an immutable SET of approved artifacts
--    instead of mutable live rows.
--
-- Historical rows
-- ---------------
-- Existing artifacts get content_hash backfilled from their current
-- ``content`` column via SHA-256. Approval pointers stay NULL because we
-- can't reconstruct the historical bytes that were approved — the safe
-- default is "treat existing approvals as unverified", so the gate will
-- refuse to execute against them until they're re-approved.

BEGIN;

-- ── artifacts ──────────────────────────────────────────────────────────────
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS content_hash          VARCHAR;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS approved_at           TIMESTAMPTZ;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS approved_content_hash VARCHAR;

CREATE INDEX IF NOT EXISTS ix_artifacts_content_hash ON artifacts (content_hash);

-- Backfill content_hash on existing rows. Postgres pgcrypto digest() returns
-- bytea — encode to hex so the value matches the application's
-- compute_content_hash() output. Skip rows that already carry a hash so
-- the migration is safe to re-run.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto'
    ) THEN
        UPDATE artifacts
           SET content_hash = encode(digest(coalesce(content, ''), 'sha256'), 'hex')
         WHERE content_hash IS NULL;
    ELSE
        RAISE NOTICE 'pgcrypto extension not installed — skipping content_hash backfill on artifacts. '
                     'Either install pgcrypto and re-run, or let the application re-stamp hashes '
                     'on next upsert.';
    END IF;
END$$;

-- ── artifact_versions ──────────────────────────────────────────────────────
ALTER TABLE artifact_versions ADD COLUMN IF NOT EXISTS content_hash VARCHAR;

CREATE INDEX IF NOT EXISTS ix_artifact_versions_content_hash
    ON artifact_versions (content_hash);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto'
    ) THEN
        UPDATE artifact_versions
           SET content_hash = encode(digest(coalesce(content, ''), 'sha256'), 'hex')
         WHERE content_hash IS NULL;
    END IF;
END$$;

-- ── artifact_approvals ─────────────────────────────────────────────────────
ALTER TABLE artifact_approvals ADD COLUMN IF NOT EXISTS approved_content_hash VARCHAR;
ALTER TABLE artifact_approvals ADD COLUMN IF NOT EXISTS approved_version      INTEGER;

-- ── release_candidates ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS release_candidates (
    id                   VARCHAR PRIMARY KEY,
    project_id           VARCHAR NOT NULL REFERENCES projects  (id) ON DELETE CASCADE,
    workflow_id          VARCHAR          REFERENCES workflows (id) ON DELETE SET NULL,
    status               VARCHAR NOT NULL DEFAULT 'draft',
    target_phase         VARCHAR NOT NULL,
    notes                TEXT,
    created_by           VARCHAR          REFERENCES users (id) ON DELETE SET NULL,
    approved_at          TIMESTAMPTZ,
    executed_at          TIMESTAMPTZ,
    candidate_metadata   JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_release_candidates_project_id  ON release_candidates (project_id);
CREATE INDEX IF NOT EXISTS ix_release_candidates_workflow_id ON release_candidates (workflow_id);
CREATE INDEX IF NOT EXISTS ix_release_candidates_status      ON release_candidates (status);

-- ── release_artifact_snapshots ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS release_artifact_snapshots (
    id                        VARCHAR PRIMARY KEY,
    candidate_id              VARCHAR NOT NULL REFERENCES release_candidates (id) ON DELETE CASCADE,
    artifact_id               VARCHAR NOT NULL REFERENCES artifacts          (id) ON DELETE CASCADE,
    artifact_type             VARCHAR NOT NULL,
    artifact_subtype          VARCHAR NOT NULL,
    snapshot_content_hash     VARCHAR NOT NULL,
    snapshot_version          INTEGER NOT NULL,
    snapshot_approval_state   VARCHAR NOT NULL DEFAULT 'pending_review',
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_release_snapshot_candidate_artifact
        UNIQUE (candidate_id, artifact_id)
);

CREATE INDEX IF NOT EXISTS ix_release_snapshots_candidate_id ON release_artifact_snapshots (candidate_id);
CREATE INDEX IF NOT EXISTS ix_release_snapshots_artifact_id  ON release_artifact_snapshots (artifact_id);

COMMIT;
