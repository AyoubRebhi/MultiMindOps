"""HTTP-level tests for GET /api/workflows.

Boots a minimal FastAPI app with ONLY the workflows router over a shared
in-memory SQLite DB, and overrides ``get_current_user`` to impersonate either
an admin or an engineer. This exercises the real request/response contract the
Workflows page depends on: the role-aware visibility rule and the
WorkflowSummary serialization (snake_case keys + ISO timestamps), end to end.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.routes.workflows import router as workflows_router
from backend.app.core import security
from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.models.workflow import Workflow


@pytest.fixture
def env():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (User, Project, Workflow):
        model.__table__.create(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = TestingSession()
    admin = User(id="admin", email="admin@x.io", display_name="Ada", role="ADMIN")
    eng1 = User(id="eng1", email="e1@x.io", display_name="Erin", role="DEVOPS_ENGINEER")
    eng2 = User(id="eng2", email="e2@x.io", display_name="Eli", role="DEVOPS_ENGINEER")
    db.add_all([admin, eng1, eng2])
    db.add(Project(id="p1", owner_id="eng1", name="Alpha", current_status="active"))
    db.add_all([
        Workflow(id="wf_a", project_id="p1", started_by="eng1",
                 current_phase="DOCKER", status="running",
                 phases_state={"PLAN_SELECTED": {"status": "completed"},
                               "DOCKER": {"status": "running"}}),
        Workflow(id="wf_b", project_id="p1", started_by="eng2",
                 current_phase="ARCHITECTURE_DECISION", status="awaiting_input",
                 phases_state={"ARCHITECTURE_DECISION": {"status": "awaiting_input"}}),
    ])
    db.commit()
    db.close()

    def _override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.include_router(workflows_router)
    app.dependency_overrides[security.get_db] = _override_get_db

    state = {"user_id": "admin"}

    def _override_user():
        s = TestingSession()
        try:
            return s.query(User).filter(User.id == state["user_id"]).first()
        finally:
            s.close()

    app.dependency_overrides[security.get_current_user] = _override_user

    client = TestClient(app)
    try:
        yield client, state
    finally:
        client.close()
        engine.dispose()


def test_admin_sees_all_workflows(env):
    client, state = env
    state["user_id"] = "admin"
    r = client.get("/api/workflows")
    assert r.status_code == 200, r.text
    ids = {w["id"] for w in r.json()}
    assert ids == {"wf_a", "wf_b"}


def test_engineer_sees_only_their_own(env):
    client, state = env
    state["user_id"] = "eng1"
    r = client.get("/api/workflows")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {w["id"] for w in body} == {"wf_a"}


def test_summary_shape_and_progress(env):
    client, state = env
    state["user_id"] = "eng1"
    wf = client.get("/api/workflows").json()[0]
    # snake_case contract the frontend mapper reads.
    assert wf["project_id"] == "p1"
    assert wf["project_name"] == "Alpha"
    assert wf["started_by_id"] == "eng1"
    assert wf["started_by_name"] == "Erin"
    assert wf["status"] == "running"
    assert wf["current_phase"] == "DOCKER"
    assert wf["completed_phases"] == 1
    assert wf["total_phases"] == 2
    assert "created_at" in wf and "updated_at" in wf
