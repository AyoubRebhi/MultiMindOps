-- Bloc 7 migration: add workflow_state column for human-validation gate
-- Run once against devsecops_db if the tasks table already exists.

ALTER TABLE tasks
    ADD COLUMN IF NOT EXISTS workflow_state JSONB;
