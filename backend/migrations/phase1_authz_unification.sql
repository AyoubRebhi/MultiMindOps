-- Phase 1 — execution authorization unification.
-- Idempotent: safe to re-run. Strictly additive where possible; the only
-- non-additive change is promoting tasks.project_id from nullable to NOT NULL,
-- which we guard with a backfill + an explicit failure mode for unrescued rows.
--
-- Apply with:
--   psql -d devsecops_db -f backend/migrations/phase1_authz_unification.sql
--
-- What this migration does
-- ------------------------
-- 1. Backfill tasks.project_id from tasks.workflow_id → workflows.project_id
--    for every row that has a workflow_id but is missing project_id. This is
--    the only safe automatic rescue path — older tasks (no workflow link)
--    cannot be project-assigned without operator input, so we leave them and
--    let the NOT NULL step fail loudly if any remain.
--
-- 2. Promote tasks.project_id to NOT NULL. This is the security invariant
--    that closes the cross-tenant-by-task_id route hole. The schema guard
--    at boot also enforces this so a fresh deploy without this migration
--    will refuse to start.
--
-- 3. Add a CHECK constraint on project_members.role so a direct UPDATE to
--    an invalid role no longer silently slips through the authorization
--    dependency (which would treat the unknown role as "deny everything").
--
-- Pre-flight diagnostics
-- ----------------------
-- Before running the migration, count orphaned tasks so the operator knows
-- whether the NOT NULL step will succeed:
--     SELECT COUNT(*) FROM tasks WHERE project_id IS NULL;
-- If non-zero AFTER step 1 runs, the operator MUST decide:
--   (a) attach them to an "Orphaned Tasks" project, or
--   (b) DELETE FROM tasks WHERE project_id IS NULL.

BEGIN;

-- ── Step 1: Backfill via workflow link ─────────────────────────────────────
-- This is the only automatic rescue path. We never invent a project_id.
UPDATE tasks
   SET project_id = w.project_id
  FROM workflows w
 WHERE tasks.workflow_id = w.id
   AND tasks.project_id IS NULL
   AND w.project_id IS NOT NULL;

-- ── Step 2: Diagnostic — fail explicitly if orphans remain ─────────────────
-- Postgres' DO block lets us raise with a precise count instead of letting
-- the ALTER TABLE below fail with a generic "column contains null values"
-- error that buries the actionable information.
DO $$
DECLARE
    orphan_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO orphan_count
      FROM tasks
     WHERE project_id IS NULL;

    IF orphan_count > 0 THEN
        RAISE EXCEPTION
            'phase1_authz_unification: % task row(s) have NULL project_id after '
            'workflow-backfill. Resolve manually before re-running this migration. '
            'Either: (a) UPDATE tasks SET project_id = ''<some-project-id>'' WHERE '
            'project_id IS NULL; or (b) DELETE FROM tasks WHERE project_id IS NULL;',
            orphan_count;
    END IF;
END$$;

-- ── Step 3: Promote project_id to NOT NULL ─────────────────────────────────
-- ALTER TABLE ... SET NOT NULL is idempotent in Postgres — running it
-- against a column that's already NOT NULL is a no-op.
ALTER TABLE tasks ALTER COLUMN project_id SET NOT NULL;

-- ── Step 4: Index alignment ────────────────────────────────────────────────
-- The model declares index=True on project_id and workflow_id; spell it out
-- here so older deployments self-heal without depending on create_all().
CREATE INDEX IF NOT EXISTS ix_tasks_project_id  ON tasks (project_id);
CREATE INDEX IF NOT EXISTS ix_tasks_workflow_id ON tasks (workflow_id);

-- ── Step 5: ProjectMember.role CHECK constraint ────────────────────────────
-- The authorization layer enforces the role set at request time, but the
-- DB has no constraint — so a direct UPDATE to an unknown role currently
-- slips through. The CHECK closes that hole. We add it conditionally to
-- stay idempotent and to allow operators who introduced custom roles to
-- skip this step.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_project_members_role'
    ) THEN
        ALTER TABLE project_members
            ADD CONSTRAINT ck_project_members_role
            CHECK (role IN ('OWNER', 'ADMIN', 'CLOUD_ARCHITECT', 'DEVELOPER', 'VIEWER'));
    END IF;
END$$;

COMMIT;

-- ── Operator notes ─────────────────────────────────────────────────────────
-- Rollback: this migration is forward-only. To reverse, run
--   ALTER TABLE tasks ALTER COLUMN project_id DROP NOT NULL;
--   ALTER TABLE project_members DROP CONSTRAINT IF EXISTS ck_project_members_role;
-- but that re-opens the cross-tenant access surface this migration closes,
-- so do not roll back without also reverting the application code.
