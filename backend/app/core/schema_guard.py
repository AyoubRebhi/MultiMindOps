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
from typing import Iterable, List

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


def describe_requirements() -> Iterable[ColumnRequirement]:
    """Expose the requirement list (used by tests and ops tools)."""
    return tuple(CRITICAL_COLUMNS)
