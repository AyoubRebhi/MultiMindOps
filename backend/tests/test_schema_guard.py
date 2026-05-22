"""Tests for backend.app.core.schema_guard.

The schema guard is the contract between SQLAlchemy ``create_all`` (which
creates missing tables but not missing columns) and the live PostgreSQL
schema. We test its three behaviors:

1. Structural sanity of every declared ``CRITICAL_COLUMNS`` requirement.
2. Idempotency: every production repair SQL uses ``ADD COLUMN IF NOT EXISTS``
   so re-running the guard on an already-repaired DB is a no-op.
3. Self-healing path: a missing column gets repaired and recorded as
   present on the second pass.

We use SQLite for (3) because spinning up a real Postgres in the test runner
is heavyweight. SQLite's ALTER TABLE does NOT accept ``IF NOT EXISTS`` for
columns, so the test patches in a SQLite-compatible variant of the
requirements while leaving the production list untouched.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

from backend.app.core.schema_guard import (
    CRITICAL_COLUMNS,
    ColumnRequirement,
    describe_requirements,
    run_schema_guard,
)


def _bootstrap_minimal_schema(engine) -> None:
    """Create the bare-minimum tables the guard expects to find."""
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tasks (id VARCHAR PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE projects (id VARCHAR PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE workflows (id VARCHAR PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE artifacts (id VARCHAR PRIMARY KEY)"))


@pytest.fixture
def sqlite_engine():
    engine = create_engine("sqlite:///:memory:")
    _bootstrap_minimal_schema(engine)
    return engine


def test_critical_columns_are_all_well_formed():
    """Each requirement names a real table and includes an additive repair."""
    seen = set()
    for req in describe_requirements():
        assert isinstance(req, ColumnRequirement)
        key = (req.table, req.column)
        assert key not in seen, f"duplicate requirement {key}"
        seen.add(key)
        assert "ADD COLUMN IF NOT EXISTS" in req.repair_sql.upper()
        assert req.purpose, f"{key} missing purpose text"


def test_repairs_are_idempotent_in_text():
    """Sanity: every production repair is shaped so re-running is safe."""
    for req in CRITICAL_COLUMNS:
        assert "IF NOT EXISTS" in req.repair_sql.upper(), (
            f"{req.table}.{req.column} repair is NOT idempotent — "
            f"add IF NOT EXISTS or the guard will fail on second boot"
        )


def test_guard_repairs_missing_columns(sqlite_engine, monkeypatch):
    """End-to-end: the guard detects + repairs missing columns.

    The production requirements use PostgreSQL syntax that SQLite does not
    accept (``IF NOT EXISTS`` on ADD COLUMN, ``REFERENCES`` clauses with
    ON DELETE actions). We swap in a sqlite-compatible variant so the test
    can validate the guard's *behavior* without paying for Postgres.
    """
    sqlite_safe = [
        ColumnRequirement(
            table="tasks",
            column="project_id",
            repair_sql="ALTER TABLE tasks ADD COLUMN project_id VARCHAR",
            purpose="test",
        ),
        ColumnRequirement(
            table="tasks",
            column="workflow_id",
            repair_sql="ALTER TABLE tasks ADD COLUMN workflow_id VARCHAR",
            purpose="test",
        ),
        ColumnRequirement(
            table="artifacts",
            column="approval_state",
            repair_sql=(
                "ALTER TABLE artifacts ADD COLUMN approval_state VARCHAR "
                "NOT NULL DEFAULT 'pending_review'"
            ),
            purpose="test",
        ),
        ColumnRequirement(
            table="projects",
            column="bootstrap_status",
            repair_sql=(
                "ALTER TABLE projects ADD COLUMN bootstrap_status VARCHAR "
                "NOT NULL DEFAULT 'pending'"
            ),
            purpose="test",
        ),
    ]

    # Before: none of the critical columns exist
    insp = inspect(sqlite_engine)
    assert "project_id" not in {c["name"] for c in insp.get_columns("tasks")}

    monkeypatch.setattr(
        "backend.app.core.schema_guard.CRITICAL_COLUMNS",
        sqlite_safe,
    )
    run_schema_guard(sqlite_engine)

    insp = inspect(sqlite_engine)
    cols_tasks = {c["name"] for c in insp.get_columns("tasks")}
    assert "project_id" in cols_tasks
    assert "workflow_id" in cols_tasks

    cols_artifacts = {c["name"] for c in insp.get_columns("artifacts")}
    assert "approval_state" in cols_artifacts

    cols_projects = {c["name"] for c in insp.get_columns("projects")}
    assert "bootstrap_status" in cols_projects


def test_guard_is_a_no_op_on_a_healthy_schema(sqlite_engine, monkeypatch):
    """Second pass after self-heal must complete without raising."""
    sqlite_safe = [
        ColumnRequirement(
            table="tasks",
            column="project_id",
            repair_sql="ALTER TABLE tasks ADD COLUMN project_id VARCHAR",
            purpose="test",
        ),
    ]
    monkeypatch.setattr(
        "backend.app.core.schema_guard.CRITICAL_COLUMNS",
        sqlite_safe,
    )
    # Pre-add the column so the guard has nothing to do.
    with sqlite_engine.begin() as conn:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN project_id VARCHAR"))

    # Second pass — must not raise.
    run_schema_guard(sqlite_engine)


def test_guard_raises_when_table_is_missing(tmp_path):
    """If a required table doesn't exist, the guard refuses to continue."""
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    with pytest.raises(RuntimeError) as ei:
        run_schema_guard(engine)
    assert "SCHEMA_GUARD" in str(ei.value)
