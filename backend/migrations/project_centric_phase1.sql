-- Phase 1 — project-centric architecture
-- Idempotent: safe to re-run. Run once against devsecops_db.
-- Note: SQLAlchemy create_all() will also create these tables on app boot,
-- but this script exists so production rollouts can run migrations explicitly.

CREATE TABLE IF NOT EXISTS users (
    id            VARCHAR PRIMARY KEY,
    email         VARCHAR NOT NULL UNIQUE,
    display_name  VARCHAR,
    is_active     VARCHAR NOT NULL DEFAULT 'true',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_users_email ON users (email);

CREATE TABLE IF NOT EXISTS projects (
    id                     VARCHAR PRIMARY KEY,
    owner_id               VARCHAR NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
    name                   VARCHAR NOT NULL,
    description            TEXT,
    repository_url         VARCHAR,
    architecture_type      VARCHAR,
    application_profile    VARCHAR,
    default_strategy_tier  VARCHAR DEFAULT 'balanced',
    current_status         VARCHAR NOT NULL DEFAULT 'draft',
    project_metadata       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_projects_owner_id       ON projects (owner_id);
CREATE INDEX IF NOT EXISTS ix_projects_repository_url ON projects (repository_url);

CREATE TABLE IF NOT EXISTS project_members (
    id          VARCHAR PRIMARY KEY,
    project_id  VARCHAR NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    user_id     VARCHAR NOT NULL REFERENCES users    (id) ON DELETE CASCADE,
    role        VARCHAR NOT NULL DEFAULT 'DEVELOPER',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_project_member_unique UNIQUE (project_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_project_members_project_id ON project_members (project_id);
CREATE INDEX IF NOT EXISTS ix_project_members_user_id    ON project_members (user_id);

CREATE TABLE IF NOT EXISTS workflows (
    id              VARCHAR PRIMARY KEY,
    project_id      VARCHAR NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    started_by      VARCHAR REFERENCES users (id) ON DELETE SET NULL,
    current_phase   VARCHAR,
    status          VARCHAR NOT NULL DEFAULT 'pending',
    execution_mode  VARCHAR NOT NULL DEFAULT 'full',
    phases_state    JSONB NOT NULL DEFAULT '{}'::jsonb,
    logs            JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_workflows_project_id ON workflows (project_id);
CREATE INDEX IF NOT EXISTS ix_workflows_started_by ON workflows (started_by);

CREATE TABLE IF NOT EXISTS artifacts (
    id                   VARCHAR PRIMARY KEY,
    project_id           VARCHAR NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    workflow_id          VARCHAR REFERENCES workflows (id) ON DELETE SET NULL,
    artifact_type        VARCHAR NOT NULL,
    artifact_subtype     VARCHAR NOT NULL,
    content              TEXT NOT NULL DEFAULT '',
    validation_status    VARCHAR NOT NULL DEFAULT 'pending',
    generated_by_agent   VARCHAR,
    approved_by          VARCHAR REFERENCES users (id) ON DELETE SET NULL,
    version              INTEGER NOT NULL DEFAULT 1,
    artifact_metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_artifact_project_type_subtype UNIQUE (project_id, artifact_type, artifact_subtype)
);
CREATE INDEX IF NOT EXISTS ix_artifacts_project_id    ON artifacts (project_id);
CREATE INDEX IF NOT EXISTS ix_artifacts_workflow_id   ON artifacts (workflow_id);
CREATE INDEX IF NOT EXISTS ix_artifacts_artifact_type ON artifacts (artifact_type);

CREATE TABLE IF NOT EXISTS artifact_versions (
    id                  VARCHAR PRIMARY KEY,
    artifact_id         VARCHAR NOT NULL REFERENCES artifacts (id) ON DELETE CASCADE,
    version             INTEGER NOT NULL,
    content             TEXT NOT NULL DEFAULT '',
    validation_results  JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_by        VARCHAR,
    workflow_id         VARCHAR REFERENCES workflows (id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_artifact_version_unique UNIQUE (artifact_id, version)
);
CREATE INDEX IF NOT EXISTS ix_artifact_versions_artifact_id ON artifact_versions (artifact_id);

CREATE TABLE IF NOT EXISTS project_contexts (
    id                   VARCHAR PRIMARY KEY,
    project_id           VARCHAR NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    context_type         VARCHAR NOT NULL,
    content              JSONB NOT NULL DEFAULT '{}'::jsonb,
    generated_by         VARCHAR,
    embedding_reference  VARCHAR,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_project_contexts_project_id   ON project_contexts (project_id);
CREATE INDEX IF NOT EXISTS ix_project_contexts_context_type ON project_contexts (context_type);

-- Link existing Task rows to the new model (nullable so old tasks survive).
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS project_id  VARCHAR REFERENCES projects  (id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS workflow_id VARCHAR REFERENCES workflows (id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_tasks_project_id  ON tasks (project_id);
CREATE INDEX IF NOT EXISTS ix_tasks_workflow_id ON tasks (workflow_id);
