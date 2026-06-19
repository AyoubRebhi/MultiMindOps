"""Workflows page — role-aware visibility tests for WorkflowListingService.

The business rule for ``GET /api/workflows``:

* ADMIN           — sees every workflow on the platform (monitoring view).
* DEVOPS_ENGINEER — sees only the workflows they personally launched.

These run against a real in-memory SQLite session because the service issues a
genuine multi-table JOIN (Workflow ⋈ Project ⋈ User) and reads the JSON
``phases_state`` column — both of which the SQLite JSON variant supports. A fake
session would not exercise the join or the progress rollup.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.services.core.workflow_listing_service import WorkflowListingService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    # Order matters only for readability; SQLite doesn't enforce FKs by default.
    User.__table__.create(engine)
    Project.__table__.create(engine)
    Workflow.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _seed(db):
    """Two engineers + one admin, two projects, three workflows.

    eng1 owns wf_a (Project Alpha) and wf_c (Project Beta); eng2 owns wf_b
    (Project Alpha). The admin launched nothing.
    """
    admin = User(id="admin", email="admin@x.io", display_name="Ada Admin", role="ADMIN")
    eng1 = User(id="eng1", email="e1@x.io", display_name="Erin Eng", role="DEVOPS_ENGINEER")
    eng2 = User(id="eng2", email="e2@x.io", role="DEVOPS_ENGINEER")  # no display name
    db.add_all([admin, eng1, eng2])

    p_alpha = Project(id="p_alpha", owner_id="eng1", name="Project Alpha", current_status="active")
    p_beta = Project(id="p_beta", owner_id="eng1", name="Project Beta", current_status="active")
    db.add_all([p_alpha, p_beta])

    wf_a = Workflow(
        id="wf_a", project_id="p_alpha", started_by="eng1",
        current_phase="DOCKER", status="running",
        phases_state={
            "ARCHITECTURE_DECISION": {"status": "completed"},
            "PLAN_SELECTED": {"status": "completed"},
            "DOCKER": {"status": "running"},
        },
    )
    wf_b = Workflow(
        id="wf_b", project_id="p_alpha", started_by="eng2",
        current_phase="ARCHITECTURE_DECISION", status="awaiting_input",
        phases_state={"ARCHITECTURE_DECISION": {"status": "awaiting_input"}},
    )
    wf_c = Workflow(
        id="wf_c", project_id="p_beta", started_by="eng1",
        current_phase="DOCKER_BUILD", status="completed",
        phases_state={
            "ARCHITECTURE_DECISION": {"status": "completed"},
            "PLAN_SELECTED": {"status": "completed"},
            "DOCKER": {"status": "completed_with_fallback"},
            "DOCKER_BUILD": {"status": "completed"},
        },
    )
    db.add_all([wf_a, wf_b, wf_c])
    db.commit()
    return admin, eng1, eng2


def test_admin_sees_all_workflows(db):
    admin, _, _ = _seed(db)
    rows = WorkflowListingService.list_for_user(db, admin)
    assert {r.id for r in rows} == {"wf_a", "wf_b", "wf_c"}


def test_engineer_sees_only_their_own(db):
    _, eng1, eng2 = _seed(db)

    eng1_rows = WorkflowListingService.list_for_user(db, eng1)
    assert {r.id for r in eng1_rows} == {"wf_a", "wf_c"}

    eng2_rows = WorkflowListingService.list_for_user(db, eng2)
    assert {r.id for r in eng2_rows} == {"wf_b"}


def test_engineer_cannot_see_peer_workflows(db):
    """The core isolation guarantee: eng2's run never appears for eng1."""
    _, eng1, _ = _seed(db)
    rows = WorkflowListingService.list_for_user(db, eng1)
    assert "wf_b" not in {r.id for r in rows}


def test_summary_joins_project_and_owner_names(db):
    admin, _, _ = _seed(db)
    by_id = {r.id: r for r in WorkflowListingService.list_for_user(db, admin)}

    assert by_id["wf_a"].project_name == "Project Alpha"
    assert by_id["wf_a"].started_by_id == "eng1"
    assert by_id["wf_a"].started_by_name == "Erin Eng"
    # eng2 has no display_name → falls back to email so the owner is never blank.
    assert by_id["wf_b"].started_by_name == "e2@x.io"


def test_phase_progress_is_derived_from_phases_state(db):
    admin, _, _ = _seed(db)
    by_id = {r.id: r for r in WorkflowListingService.list_for_user(db, admin)}

    # wf_a: 2 completed of 3 touched (DOCKER still running).
    assert (by_id["wf_a"].completed_phases, by_id["wf_a"].total_phases) == (2, 3)
    # wf_c: all 4 done (completed_with_fallback counts as completed).
    assert (by_id["wf_c"].completed_phases, by_id["wf_c"].total_phases) == (4, 4)
    # wf_b: nothing completed yet.
    assert (by_id["wf_b"].completed_phases, by_id["wf_b"].total_phases) == (0, 1)


def test_ordered_newest_updated_first(db):
    admin, _, _ = _seed(db)
    rows = WorkflowListingService.list_for_user(db, admin)
    updated = [r.updated_at for r in rows]
    assert updated == sorted(updated, reverse=True)
