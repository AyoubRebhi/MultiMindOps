-- Collaboration & governance layer
-- Idempotent — safe to re-run.
-- Adds:
--   * artifact_approvals  (per-decision audit history for artifact reviews)
--   * artifacts.approval_state  (denormalized current state — drives UI badges)

CREATE TABLE IF NOT EXISTS artifact_approvals (
    id           VARCHAR PRIMARY KEY,
    artifact_id  VARCHAR NOT NULL REFERENCES artifacts (id) ON DELETE CASCADE,
    approved_by  VARCHAR REFERENCES users     (id) ON DELETE SET NULL,
    action       VARCHAR NOT NULL,         -- 'approve' | 'reject' | 'request_changes'
    comment      TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_artifact_approvals_artifact_id ON artifact_approvals (artifact_id);
CREATE INDEX IF NOT EXISTS ix_artifact_approvals_approved_by ON artifact_approvals (approved_by);

-- Denormalized current state — written by ArtifactApprovalService after every
-- decision. Old artifacts default to 'pending_review' so the UI can render
-- them as awaiting governance review.
ALTER TABLE artifacts
    ADD COLUMN IF NOT EXISTS approval_state VARCHAR NOT NULL DEFAULT 'pending_review';

CREATE INDEX IF NOT EXISTS ix_artifacts_approval_state ON artifacts (approval_state);
