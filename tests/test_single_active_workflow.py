"""Single-active-workflow contract.

Proves the duplicate-workflow fix: bootstrap + the explicit API endpoint both
funnel through ``WorkflowOrchestrationService.get_or_create_workflow``, so a
project never accumulates two concurrent ACTIVE workflows. Terminal workflows
(completed/failed/cancelled) do NOT block a new run.

Runs against a real in-memory SQLite session (LLM + credentials stubbed),
mirroring tests/test_golden_path.py.
"""

from __future__ import annotations

import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.execution_job import ExecutionJob
from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for model in (Project, Workflow, Task, Artifact, ArtifactVersion, ExecutionJob):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


_ARCH_STATE = {
    "prompt": "deploy",
    "current_phase": "architecture_decision_complete",
    "plan": {"project_name": "p"},
    "architecture_decision": {"strategies": [{"id": "balanced"}]},
    "logs": [],
}


@pytest.fixture
def stub_agents(monkeypatch):
    from backend.app.agents.orchestrator_agent import OrchestratorAgent
    from backend.app.services.core.credentials_service import CredentialsService
    from backend.app.services.core.project_context_service import ProjectContextService

    monkeypatch.setattr(OrchestratorAgent, "__init__", lambda self: None)
    monkeypatch.setattr(
        OrchestratorAgent, "run_architecture_decision_phase",
        lambda self, **kw: dict(_ARCH_STATE),
    )
    monkeypatch.setattr(CredentialsService, "get_credential", lambda *a, **k: None)
    monkeypatch.setattr(CredentialsService, "hydrate_state", lambda db, state, project_id=None: state)
    monkeypatch.setattr(ProjectContextService, "capture_from_state", lambda *a, **k: [])


@pytest.fixture
def project(db):
    proj = Project(id="proj-1", owner_id="user-1", name="p", current_status="active")
    db.add(proj)
    db.commit()
    return proj


def _wf_count(db):
    return db.query(Workflow).filter(Workflow.project_id == "proj-1").count()


def _user():
    return types.SimpleNamespace(id="user-1")


def test_second_call_reuses_active_workflow(db, project, stub_agents):
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )

    wf1, task1, _ = WOS.get_or_create_workflow(
        db, project=project, user=_user(), prompt="deploy",
    )
    assert _wf_count(db) == 1
    assert wf1.status == "awaiting_input"  # active

    # Simulate the bootstrap + API race: a second creation call.
    wf2, task2, _ = WOS.get_or_create_workflow(
        db, project=project, user=_user(), prompt="deploy again",
    )

    # No duplicate: same workflow + same backing task returned.
    assert _wf_count(db) == 1
    assert wf2.id == wf1.id
    assert task2.id == task1.id


def test_terminal_workflow_does_not_block_new(db, project, stub_agents):
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )

    wf1, _, _ = WOS.get_or_create_workflow(
        db, project=project, user=_user(), prompt="deploy",
    )
    # Mark the first run terminal (historical) — preserved, not deleted.
    wf1.status = "completed"
    db.commit()

    wf2, _, _ = WOS.get_or_create_workflow(
        db, project=project, user=_user(), prompt="deploy v2",
    )

    # A NEW workflow is created; the historical one is untouched.
    assert wf2.id != wf1.id
    assert _wf_count(db) == 2
    db.refresh(wf1)
    assert wf1.status == "completed"


def test_get_active_workflow_ignores_terminal(db, project, stub_agents):
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )

    # Two historical (terminal) workflows + one active.
    db.add(Workflow(id="w-old1", project_id="proj-1", status="completed", phases_state={}))
    db.add(Workflow(id="w-old2", project_id="proj-1", status="failed", phases_state={}))
    db.add(Workflow(id="w-active", project_id="proj-1", status="running", phases_state={}))
    db.commit()

    active = WOS.get_active_workflow(db, "proj-1")
    assert active is not None
    assert active.id == "w-active"


def test_active_workflow_without_task_creates_fresh(db, project, stub_agents):
    """A broken active workflow with no backing task must not be returned."""
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )

    # Active workflow but NO Task row backing it.
    db.add(Workflow(id="w-broken", project_id="proj-1", status="running", phases_state={}))
    db.commit()

    wf, task, _ = WOS.get_or_create_workflow(
        db, project=project, user=_user(), prompt="deploy",
    )
    # A usable workflow (with a task) is created instead of returning the broken one.
    assert wf.id != "w-broken"
    assert task is not None


# ─── Force re-analysis (WorkflowOrchestrationService.reanalyze) ───────────────


def test_reanalyze_reruns_in_place_on_active_workflow(db, project, stub_agents):
    """reanalyze must re-run analysis on the EXISTING active workflow (not reuse
    it untouched like get_or_create, and not create a duplicate), clearing the
    stale downstream phase state so it is re-run against the fresh analysis."""
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )

    wf1, task1, _ = WOS.get_or_create_workflow(
        db, project=project, user=_user(), prompt="deploy",
    )
    # Simulate downstream progress that a re-analysis must invalidate.
    wf1.phases_state = {**(wf1.phases_state or {}), "DOCKER": {"status": "completed"}}
    db.commit()

    wf2, task2, _ = WOS.reanalyze(
        db, project=project, user=_user(), prompt="re-analyze",
    )

    # In place: same workflow + backing task, no duplicate row.
    assert wf2.id == wf1.id
    assert task2.id == task1.id
    assert _wf_count(db) == 1
    # Stale downstream phase cleared; the fresh architecture-decision is recorded.
    assert "DOCKER" not in (wf2.phases_state or {})
    assert "ARCHITECTURE_DECISION" in (wf2.phases_state or {})
    assert wf2.status == "awaiting_input"


def test_reanalyze_starts_fresh_when_no_active_workflow(db, project, stub_agents):
    """With no active workflow, reanalyze starts a new run (cache still bypassed)."""
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )

    assert _wf_count(db) == 0
    wf, task, _ = WOS.reanalyze(
        db, project=project, user=_user(), prompt="x",
    )
    assert wf is not None and task is not None
    assert _wf_count(db) == 1


def test_reanalyze_threads_force_flag_into_orchestrator(db, project, monkeypatch):
    """reanalyze must call the orchestrator with force_reanalysis=True so the
    repository-analysis cache is bypassed and gpt-5-mini actually re-runs."""
    from backend.app.agents.orchestrator_agent import OrchestratorAgent
    from backend.app.services.core.credentials_service import CredentialsService
    from backend.app.services.core.project_context_service import ProjectContextService
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )

    calls: list[dict] = []

    def _capture(self, **kw):
        calls.append(kw)
        return dict(_ARCH_STATE)

    monkeypatch.setattr(OrchestratorAgent, "__init__", lambda self: None)
    monkeypatch.setattr(OrchestratorAgent, "run_architecture_decision_phase", _capture)
    monkeypatch.setattr(CredentialsService, "get_credential", lambda *a, **k: None)
    monkeypatch.setattr(ProjectContextService, "capture_from_state", lambda *a, **k: [])

    WOS.reanalyze(db, project=project, user=_user(), prompt="x")

    assert calls, "orchestrator was never invoked"
    assert calls[-1].get("force_reanalysis") is True
