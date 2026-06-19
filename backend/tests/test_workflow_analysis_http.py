"""HTTP-level tests for the workflow resume + Analysis-phase endpoints.

Boots a minimal FastAPI app with ONLY the workflows router over an in-memory
SQLite DB and impersonates an admin or engineer. Verifies the role-aware
visibility rule for:

    GET /api/workflows/{id}            (resume: status + current_phase)
    GET /api/workflows/{id}/analysis   (aggregated Analysis payload)

The analysis aggregation itself is stubbed (it has dedicated unit coverage) so
these tests focus on routing, 404-on-not-visible, and the resume contract.
"""

from __future__ import annotations

from unittest.mock import patch

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
from backend.app.schemas.workflow_analysis import ProjectInfo, WorkflowAnalysisResponse
from backend.app.services.core.workflow_analysis_aggregation_service import (
    WorkflowAnalysisAggregationService,
)


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
    db.add_all([
        User(id="admin", email="admin@x.io", display_name="Ada", role="ADMIN"),
        User(id="eng1", email="e1@x.io", display_name="Erin", role="DEVOPS_ENGINEER"),
        User(id="eng2", email="e2@x.io", display_name="Eli", role="DEVOPS_ENGINEER"),
    ])
    db.add(Project(id="p1", owner_id="eng1", name="Alpha", current_status="active"))
    db.add_all([
        Workflow(id="wf_own", project_id="p1", started_by="eng1",
                 current_phase="ARCHITECTURE_DECISION", status="awaiting_input",
                 phases_state={"ARCHITECTURE_DECISION": {"status": "awaiting_input"}}),
        Workflow(id="wf_peer", project_id="p1", started_by="eng2",
                 current_phase="DOCKER", status="running",
                 phases_state={"DOCKER": {"status": "running"}}),
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


# ── Resume endpoint: GET /api/workflows/{id} ──────────────────────────────────

def test_resume_returns_phase_and_status_for_owner(env):
    client, state = env
    state["user_id"] = "eng1"
    r = client.get("/api/workflows/wf_own")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "wf_own"
    assert body["current_phase"] == "ARCHITECTURE_DECISION"
    assert body["status"] == "awaiting_input"
    assert body["project_name"] == "Alpha"


def test_admin_can_resume_any_workflow(env):
    client, state = env
    state["user_id"] = "admin"
    assert client.get("/api/workflows/wf_own").status_code == 200
    assert client.get("/api/workflows/wf_peer").status_code == 200


def test_engineer_cannot_resume_peer_workflow(env):
    client, state = env
    state["user_id"] = "eng1"
    r = client.get("/api/workflows/wf_peer")
    assert r.status_code == 404  # existence never leaked across owners


def test_resume_unknown_workflow_is_404(env):
    client, state = env
    state["user_id"] = "admin"
    assert client.get("/api/workflows/does-not-exist").status_code == 404


# ── Analysis endpoint: GET /api/workflows/{id}/analysis ───────────────────────

def _canned(workflow_id="wf_own", project_id="p1"):
    return WorkflowAnalysisResponse(
        workflow_id=workflow_id,
        project_id=project_id,
        project_info=ProjectInfo(id=project_id, name="Alpha"),
        status="DONE",
    )


def test_owner_gets_aggregated_analysis(env):
    client, state = env
    state["user_id"] = "eng1"
    with patch.object(WorkflowAnalysisAggregationService, "build", return_value=_canned()):
        r = client.get("/api/workflows/wf_own/analysis")
    assert r.status_code == 200, r.text
    body = r.json()
    # The five sections + identity are always present in the contract.
    for key in (
        "customer_portal", "code_analysis", "architecture_intelligence",
        "infrastructure_recommendations", "security_containerization",
    ):
        assert key in body
    assert body["workflow_id"] == "wf_own"
    assert body["status"] == "DONE"


def test_engineer_cannot_read_peer_analysis(env):
    client, state = env
    state["user_id"] = "eng1"
    with patch.object(WorkflowAnalysisAggregationService, "build", return_value=_canned("wf_peer")):
        r = client.get("/api/workflows/wf_peer/analysis")
    assert r.status_code == 404


def test_admin_can_read_any_analysis(env):
    client, state = env
    state["user_id"] = "admin"
    with patch.object(WorkflowAnalysisAggregationService, "build", return_value=_canned("wf_peer")):
        r = client.get("/api/workflows/wf_peer/analysis")
    assert r.status_code == 200
