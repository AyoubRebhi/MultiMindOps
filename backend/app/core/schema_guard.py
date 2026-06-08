"""Startup schema guard.

``Base.metadata.create_all()`` creates missing tables but never ADDs columns to
existing ones. That gap is exactly what produced the runtime error
``column tasks.project_id does not exist`` after the project-centric model
landed: the ``tasks`` table predates the new columns, so SQLAlchemy left it
untouched while the ORM started issuing ``SELECT tasks.project_id`` queries.

This module:

1. Inspects the live database for the critical columns the new model expects.
2. Emits structured ``[SCHEMA_GUARD]`` log lines so operators can tell at a
   glance what is present, what is missing, and what the guard did about it.
3. Applies a small, additive, idempotent repair set (``ALTER TABLE ... ADD
   COLUMN IF NOT EXISTS``) so dev environments self-heal without operators
   having to run the migration SQL by hand.
4. Refuses to silently continue if a repair fails — the exception bubbles up
   into the app lifespan and the process exits, which is what the spec
   requires ("never silently continue on schema mismatch").

Design notes
------------
* Repairs are STRICTLY ADDITIVE. The guard will never drop, rename, or
  reshape a column. Anything beyond ``ADD COLUMN`` belongs in a real
  migration file under ``backend/migrations/``.
* The guard is best-effort but loud: every column it finds, every column it
  adds, and every column it cannot add gets its own log line.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ColumnRequirement:
    """A column the live schema must have, plus the additive repair to add it.

    ``repair_sql`` is run verbatim when the column is missing. It MUST be
    idempotent (use ``ADD COLUMN IF NOT EXISTS``) — the guard does not wrap
    the statement in a transaction-rollback safety net.
    """

    table: str
    column: str
    repair_sql: str
    purpose: str  # one-line human description for log output


@dataclass(frozen=True)
class NotNullRequirement:
    """A column that MUST be NOT NULL in the live schema.

    Unlike ``ColumnRequirement`` this does not self-heal: forcibly setting
    a column NOT NULL when nulls already exist would either crash or hide
    a tenancy violation. The guard reports the breach loudly and refuses
    to boot — operators run the corresponding SQL migration explicitly.
    The check is skipped if the column does not exist yet (a fresh deploy
    on an empty DB still works because create_all() emits NOT NULL).
    """

    table: str
    column: str
    purpose: str
    migration_hint: str  # which migration file to run by hand


# Critical columns the project-centric model requires. Add new entries here
# when introducing additive schema changes; do NOT remove entries — they
# protect older deployments from skipping a migration.
CRITICAL_COLUMNS: List[ColumnRequirement] = [
    ColumnRequirement(
        table="tasks",
        column="project_id",
        repair_sql=(
            "ALTER TABLE tasks "
            "ADD COLUMN IF NOT EXISTS project_id VARCHAR "
            "REFERENCES projects (id) ON DELETE SET NULL"
        ),
        purpose="links legacy Task rows to the project-centric model",
    ),
    ColumnRequirement(
        table="tasks",
        column="workflow_id",
        repair_sql=(
            "ALTER TABLE tasks "
            "ADD COLUMN IF NOT EXISTS workflow_id VARCHAR "
            "REFERENCES workflows (id) ON DELETE SET NULL"
        ),
        purpose="links legacy Task rows to the Workflow they back",
    ),
    ColumnRequirement(
        table="artifacts",
        column="approval_state",
        repair_sql=(
            "ALTER TABLE artifacts "
            "ADD COLUMN IF NOT EXISTS approval_state VARCHAR "
            "NOT NULL DEFAULT 'pending_review'"
        ),
        purpose="denormalized governance state for UI badges",
    ),
    ColumnRequirement(
        table="projects",
        column="bootstrap_status",
        repair_sql=(
            "ALTER TABLE projects "
            "ADD COLUMN IF NOT EXISTS bootstrap_status VARCHAR "
            "NOT NULL DEFAULT 'pending'"
        ),
        purpose="AI bootstrap state machine (pending → analyzing → ready/failed)",
    ),
    ColumnRequirement(
        table="projects",
        column="bootstrap_error",
        repair_sql=(
            "ALTER TABLE projects "
            "ADD COLUMN IF NOT EXISTS bootstrap_error TEXT"
        ),
        purpose="last bootstrap failure trace for the ProjectDetail retry UI",
    ),
    ColumnRequirement(
        table="projects",
        column="repository_visibility",
        repair_sql=(
            "ALTER TABLE projects "
            "ADD COLUMN IF NOT EXISTS repository_visibility VARCHAR"
        ),
        purpose="public/private flag driving credential resolution",
    ),
    # ── Auth foundation columns ────────────────────────────────────────────
    # See backend/migrations/auth_foundation.sql for the canonical migration.
    ColumnRequirement(
        table="users",
        column="password_hash",
        repair_sql=(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR"
        ),
        purpose="bcrypt password hash for the local-auth flow",
    ),
    ColumnRequirement(
        table="users",
        column="avatar_url",
        repair_sql=(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR"
        ),
        purpose="user avatar URL (UI)",
    ),
    ColumnRequirement(
        table="users",
        column="auth_provider",
        repair_sql=(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider "
            "VARCHAR NOT NULL DEFAULT 'local'"
        ),
        purpose="auth provider tag (local | dev | google | github | ...)",
    ),
    ColumnRequirement(
        table="users",
        column="email_verified",
        repair_sql=(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified "
            "VARCHAR NOT NULL DEFAULT 'false'"
        ),
        purpose="email confirmation flag",
    ),
    ColumnRequirement(
        table="users",
        column="account_status",
        repair_sql=(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status "
            "VARCHAR NOT NULL DEFAULT 'active'"
        ),
        purpose="account state machine (active | disabled | locked | pending)",
    ),
    ColumnRequirement(
        table="users",
        column="last_login_at",
        repair_sql=(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ"
        ),
        purpose="last successful login timestamp",
    ),
    ColumnRequirement(
        table="users",
        column="failed_login_attempts",
        repair_sql=(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts "
            "INTEGER NOT NULL DEFAULT 0"
        ),
        purpose="lockout counter (reset on success)",
    ),
    ColumnRequirement(
        table="users",
        column="created_by",
        repair_sql=(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_by "
            "VARCHAR REFERENCES users (id) ON DELETE SET NULL"
        ),
        purpose="audit pointer: who created this user",
    ),
    ColumnRequirement(
        table="users",
        column="updated_by",
        repair_sql=(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_by "
            "VARCHAR REFERENCES users (id) ON DELETE SET NULL"
        ),
        purpose="audit pointer: who last updated this user",
    ),
    # ── Phase 4 — encrypted credentials canary ─────────────────────────────
    # The credentials table is created by SQLAlchemy at create_all() time.
    # We declare ONE canary column so the guard's missing-table path fires
    # if the table is somehow absent (older deployment, partial migration);
    # the guard logs the table name and refuses to boot.
    ColumnRequirement(
        table="project_credentials",
        column="encrypted_payload",
        repair_sql=(
            "ALTER TABLE project_credentials "
            "ADD COLUMN IF NOT EXISTS encrypted_payload TEXT NOT NULL DEFAULT ''"
        ),
        purpose=(
            "Phase 4 — Fernet ciphertext column on the per-project "
            "credentials store; canary that surfaces a missing table early"
        ),
    ),
    # ── Phase 3 — execution jobs canary ─────────────────────────────────────
    # Same canary pattern: surfaces a missing execution_jobs table at boot.
    # The per-project run-lock partial index is emitted by create_all() and
    # the migration; the guard does not attempt to (re)create it.
    ColumnRequirement(
        table="execution_jobs",
        column="status",
        repair_sql=(
            "ALTER TABLE execution_jobs "
            "ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'pending'"
        ),
        purpose=(
            "Phase 3 — durable job status column; canary that surfaces a "
            "missing execution_jobs table early"
        ),
    ),
    # ── Phase 2 — governance enforcement ───────────────────────────────────
    # Content-hash columns on artifacts + artifact_versions, plus the
    # approved_content_hash / approved_at columns that bind an approval to
    # the exact bytes the reviewer saw. Self-healed additively here so
    # older deployments come up; the canonical migration is
    # phase2_governance_enforcement.sql (it also backfills hashes).
    ColumnRequirement(
        table="artifacts",
        column="content_hash",
        repair_sql=(
            "ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS content_hash VARCHAR"
        ),
        purpose="Phase 2 — SHA-256 of current content; drives the approval-drift gate",
    ),
    ColumnRequirement(
        table="artifacts",
        column="approved_at",
        repair_sql=(
            "ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ"
        ),
        purpose="Phase 2 — when the current content was approved",
    ),
    ColumnRequirement(
        table="artifacts",
        column="approved_content_hash",
        repair_sql=(
            "ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS approved_content_hash VARCHAR"
        ),
        purpose="Phase 2 — the content hash that was approved; drift→re-review",
    ),
    ColumnRequirement(
        table="artifact_versions",
        column="content_hash",
        repair_sql=(
            "ALTER TABLE artifact_versions ADD COLUMN IF NOT EXISTS content_hash VARCHAR"
        ),
        purpose="Phase 2 — frozen hash on each historical version",
    ),
    ColumnRequirement(
        table="artifact_approvals",
        column="approved_content_hash",
        repair_sql=(
            "ALTER TABLE artifact_approvals "
            "ADD COLUMN IF NOT EXISTS approved_content_hash VARCHAR"
        ),
        purpose="Phase 2 — historical hash captured at decision time",
    ),
    ColumnRequirement(
        table="artifact_approvals",
        column="approved_version",
        repair_sql=(
            "ALTER TABLE artifact_approvals "
            "ADD COLUMN IF NOT EXISTS approved_version INTEGER"
        ),
        purpose="Phase 2 — artifact version at decision time",
    ),
    # Canaries for the new release tables — create_all() makes them; if
    # they're missing the guard refuses to boot with a clear pointer to
    # the migration.
    ColumnRequirement(
        table="release_candidates",
        column="status",
        repair_sql=(
            "ALTER TABLE release_candidates "
            "ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'draft'"
        ),
        purpose="Phase 2 — release candidate status canary",
    ),
    ColumnRequirement(
        table="release_artifact_snapshots",
        column="snapshot_content_hash",
        repair_sql=(
            "ALTER TABLE release_artifact_snapshots "
            "ADD COLUMN IF NOT EXISTS snapshot_content_hash VARCHAR NOT NULL DEFAULT ''"
        ),
        purpose="Phase 2 — frozen snapshot hash canary",
    ),
    # ── Phase 5 — workflow event log ───────────────────────────────────────
    ColumnRequirement(
        table="workflow_phase_events",
        column="phase",
        repair_sql=(
            "ALTER TABLE workflow_phase_events "
            "ADD COLUMN IF NOT EXISTS phase VARCHAR NOT NULL DEFAULT 'UNKNOWN'"
        ),
        purpose="Phase 5 — workflow event log canary",
    ),
    # ── Observability — workflow execution trace ────────────────────────────
    # create_all() makes the table; this canary surfaces a missing table early
    # on older deployments so the /debug + /replay observability layer works.
    ColumnRequirement(
        table="workflow_execution_traces",
        column="phase",
        repair_sql=(
            "ALTER TABLE workflow_execution_traces "
            "ADD COLUMN IF NOT EXISTS phase VARCHAR NOT NULL DEFAULT 'UNKNOWN'"
        ),
        purpose="Observability — per-phase execution trace canary",
    ),
]


# Columns the guard refuses to boot without — invariants that secure
# multi-tenant access. Promoting a column from nullable→NOT NULL is too
# dangerous to self-heal (it would either crash on existing nulls or, worse,
# hide them by inserting fake values), so the guard only DIAGNOSES and the
# operator runs the SQL migration.
NOT_NULL_REQUIREMENTS: List[NotNullRequirement] = [
    NotNullRequirement(
        table="tasks",
        column="project_id",
        purpose=(
            "closes the cross-tenant access surface — every Task must "
            "resolve to exactly one Project so the role gate is meaningful"
        ),
        migration_hint="backend/migrations/phase1_authz_unification.sql",
    ),
]


def _existing_columns(engine: Engine, table: str) -> set[str]:
    """Return the set of column names present on ``table``.

    Empty set means either "table does not exist" or "inspector failed".
    Both are handled the same way by the caller — the missing column case.
    """
    try:
        insp = inspect(engine)
        if not insp.has_table(table):
            return set()
        return {c["name"] for c in insp.get_columns(table)}
    except SQLAlchemyError as exc:
        logger.warning("[SCHEMA_GUARD] Inspector failed for table=%s: %s", table, exc)
        return set()


def _column_nullable(engine: Engine, table: str, column: str) -> Optional[bool]:
    """Return True/False if the column exists, None if the column or table is missing.

    SQLAlchemy's reflection returns ``{"nullable": bool}`` on each column dict;
    we surface the tri-state because "doesn't exist" is meaningfully different
    from "exists and is nullable".
    """
    try:
        insp = inspect(engine)
        if not insp.has_table(table):
            return None
        for col in insp.get_columns(table):
            if col["name"] == column:
                return bool(col.get("nullable", True))
        return None
    except SQLAlchemyError as exc:
        logger.warning(
            "[SCHEMA_GUARD] Inspector failed reading %s.%s nullability: %s",
            table, column, exc,
        )
        return None


def _count_null_rows(engine: Engine, table: str, column: str) -> Optional[int]:
    """Best-effort SELECT COUNT(*) WHERE column IS NULL — None on error.

    Used purely for diagnostic output so operators see how many rows the
    migration would need to rescue. We do not block on the count itself —
    the nullability flag is the authoritative invariant.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
            ).scalar_one()
            return int(row or 0)
    except SQLAlchemyError as exc:
        logger.warning(
            "[SCHEMA_GUARD] Could not count NULLs in %s.%s: %s",
            table, column, exc,
        )
        return None


def _apply_repair(engine: Engine, req: ColumnRequirement) -> None:
    """Run the additive repair statement and commit it.

    Raises ``SQLAlchemyError`` if the statement fails. The caller decides how
    to react — currently the lifespan re-raises so startup aborts loudly.
    """
    with engine.begin() as conn:
        conn.execute(text(req.repair_sql))


def run_schema_guard(engine: Engine) -> None:
    """Verify critical columns exist, applying additive repairs if missing.

    Call once during startup, AFTER ``Base.metadata.create_all()`` (so any
    missing tables are created by SQLAlchemy first, and the guard only needs
    to worry about column-level drift on existing tables).
    """
    logger.info("[SCHEMA_GUARD] Running startup schema check")

    missing_tables: set[str] = set()
    repaired: List[str] = []
    failures: List[str] = []
    ok_count = 0

    # Group requirements by table so we inspect each table at most once.
    tables = {req.table for req in CRITICAL_COLUMNS}
    columns_by_table = {t: _existing_columns(engine, t) for t in tables}

    for table, cols in columns_by_table.items():
        if not cols:
            missing_tables.add(table)
            logger.error(
                "[SCHEMA_GUARD] Missing table '%s' — create_all() should have "
                "created it. Check DB connection and model imports.",
                table,
            )

    for req in CRITICAL_COLUMNS:
        present = columns_by_table.get(req.table, set())
        if req.column in present:
            ok_count += 1
            continue

        if req.table in missing_tables:
            # No point in ALTER TABLE on a table that does not exist.
            failures.append(f"{req.table}.{req.column} (table missing)")
            continue

        logger.warning(
            "[SCHEMA_GUARD] Missing %s.%s — applying additive repair (%s)",
            req.table, req.column, req.purpose,
        )
        try:
            _apply_repair(engine, req)
            repaired.append(f"{req.table}.{req.column}")
            logger.info(
                "[SCHEMA_GUARD] Repaired %s.%s",
                req.table, req.column,
            )
        except SQLAlchemyError as exc:
            failures.append(f"{req.table}.{req.column} ({exc.__class__.__name__})")
            logger.error(
                "[SCHEMA_GUARD] FAILED to repair %s.%s: %s",
                req.table, req.column, exc,
            )

    logger.info(
        "[SCHEMA_GUARD] Summary: %d ok, %d repaired, %d failed, missing_tables=%s",
        ok_count, len(repaired), len(failures), sorted(missing_tables) or "none",
    )

    if failures or missing_tables:
        # Refuse to start with broken schema — the spec is explicit about not
        # silently continuing. Operators will see the structured log above
        # and know exactly which migration to run.
        details = ", ".join(failures) if failures else f"missing tables: {sorted(missing_tables)}"
        raise RuntimeError(
            f"[SCHEMA_GUARD] Schema check failed and could not self-heal: {details}. "
            f"Run backend/migrations/project_centric_phase1.sql against the database "
            f"before restarting."
        )

    # ── NOT NULL invariants — diagnose only, never auto-heal ──────────────
    # These are tenancy invariants. If a column is nullable that must not be,
    # or a NULL row slipped through, we refuse to boot. The operator runs
    # the migration; we never silently re-tighten the schema.
    notnull_violations: List[str] = []
    for req in NOT_NULL_REQUIREMENTS:
        is_nullable = _column_nullable(engine, req.table, req.column)
        if is_nullable is None:
            # Column or table is missing — that's a separate failure mode
            # the column-level requirements would have surfaced if relevant.
            # Skip the not-null check; do not mask the original error.
            logger.info(
                "[SCHEMA_GUARD] NOT NULL check skipped for %s.%s (column not present)",
                req.table, req.column,
            )
            continue
        if is_nullable:
            null_count = _count_null_rows(engine, req.table, req.column)
            notnull_violations.append(
                f"{req.table}.{req.column} is nullable "
                f"(NULL rows: {null_count if null_count is not None else 'unknown'}). "
                f"Run {req.migration_hint} — {req.purpose}."
            )
            continue
        # Defensive: the column is declared NOT NULL but the DB might still
        # hold residual NULLs if NOT NULL was added without a backfill on a
        # previous deploy (which Postgres would actually reject — this is a
        # belt-and-braces check).
        null_count = _count_null_rows(engine, req.table, req.column)
        if null_count and null_count > 0:
            notnull_violations.append(
                f"{req.table}.{req.column} is declared NOT NULL but still has "
                f"{null_count} NULL row(s). DB is inconsistent — investigate manually."
            )

    if notnull_violations:
        for line in notnull_violations:
            logger.error("[SCHEMA_GUARD] NOT NULL invariant breach: %s", line)
        raise RuntimeError(
            "[SCHEMA_GUARD] NOT NULL invariant breach — refusing to start:\n  - "
            + "\n  - ".join(notnull_violations)
        )


def ensure_single_active_workflow_index(engine: Engine) -> None:
    """Defense-in-depth DB guard for "one active workflow per project".

    Creates a PARTIAL UNIQUE INDEX on ``workflows(project_id)`` restricted to
    non-terminal rows, so the database itself rejects a second concurrent active
    workflow even if the application-level ``get_or_create_workflow`` guard is
    bypassed (e.g. a race).

    Safety (honours "do NOT break historical / do NOT delete data"):
    * Postgres only — the predicate uses ``status NOT IN (...)``. Other dialects
      (the SQLite test DB) are skipped.
    * If the project table ALREADY contains projects with multiple active
      workflows (duplicates created before this guard shipped), creating the
      unique index would fail — so we DETECT that first and SKIP creation,
      logging a warning. We never mutate or delete the historical rows to force
      the index; the application guard still prevents NEW duplicates.
    * Idempotent: ``CREATE UNIQUE INDEX IF NOT EXISTS``.
    """
    if engine.dialect.name != "postgresql":
        logger.info(
            "[WORKFLOW_GUARD] dialect=%s — partial unique index skipped "
            "(application get_or_create guard still active)",
            engine.dialect.name,
        )
        return

    terminal = "('completed','failed','cancelled')"
    try:
        with engine.connect() as conn:
            dup_projects = conn.execute(
                text(
                    "SELECT COUNT(*) FROM ("
                    "  SELECT project_id FROM workflows "
                    f"  WHERE status NOT IN {terminal} "
                    "  GROUP BY project_id HAVING COUNT(*) > 1"
                    ") d"
                )
            ).scalar_one()
        if dup_projects and int(dup_projects) > 0:
            logger.warning(
                "[WORKFLOW_GUARD] %d project(s) already have multiple ACTIVE "
                "workflows — skipping unique-index creation to avoid breaking "
                "existing data. The application get_or_create guard prevents NEW "
                "duplicates; reconcile the legacy rows, then restart to enforce "
                "at the DB level.",
                int(dup_projects),
            )
            return

        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_workflows_one_active_per_project "
                    "ON workflows (project_id) "
                    f"WHERE status NOT IN {terminal}"
                )
            )
        logger.info(
            "[WORKFLOW_GUARD] partial unique index ensured — at most one active "
            "workflow per project enforced at the DB level"
        )
    except SQLAlchemyError as exc:
        # Best-effort: never block startup over the defense-in-depth index. The
        # application-level guard is the primary enforcement.
        logger.warning(
            "[WORKFLOW_GUARD] could not ensure single-active-workflow index: %s",
            exc,
        )


def describe_requirements() -> Iterable[ColumnRequirement]:
    """Expose the requirement list (used by tests and ops tools)."""
    return tuple(CRITICAL_COLUMNS)


def describe_not_null_requirements() -> Iterable[NotNullRequirement]:
    """Expose the NOT NULL invariants (used by tests and ops tools)."""
    return tuple(NOT_NULL_REQUIREMENTS)
