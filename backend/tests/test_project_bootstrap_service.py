"""Bootstrap state-machine tests.

We mock the Session, User, and WorkflowOrchestrationService so the tests
exercise the transition logic in isolation. The orchestrator is heavy
(LLM, repo clone) and is verified by its own integration suite; here we
only need to know that ProjectBootstrapService:

* flips status to ``analyzing`` before invoking orchestration,
* flips to ``context_building`` then ``ready`` on success,
* flips to ``failed`` and persists a structured ``bootstrap_error`` on
  any orchestrator exception,
* short-circuits to ``ready`` when no repository_url is set.
"""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.core.project_bootstrap_service import (
    STATUS_ANALYZING,
    STATUS_CONTEXT_BUILDING,
    STATUS_FAILED,
    STATUS_READY,
    ProjectBootstrapService,
)


class _FakeProject:
    """Minimal stand-in for the SQLAlchemy Project row."""

    def __init__(self, *, project_id="p1", repo_url="https://example.com/r"):
        self.id = project_id
        self.owner_id = "u1"
        self.repository_url = repo_url
        self.repository_visibility = "public"
        self.bootstrap_status = "pending"
        self.bootstrap_error = None
        self.current_status = "draft"


class _FakeUser:
    def __init__(self, user_id="u1"):
        self.id = user_id


class _FakeSession:
    """Records commit() invocations so we can snapshot state transitions."""

    def __init__(self, *, project=None, user=None):
        self._project = project
        self._user = user
        self.commits: List[dict] = []
        self.closed = False

    # ── query/filter chain returning the requested object ──────────────────
    def query(self, model):
        return _FakeQuery(self, model)

    def commit(self):
        # Snapshot the project state at each commit so we can assert order.
        if self._project is not None:
            self.commits.append({
                "bootstrap_status": self._project.bootstrap_status,
                "bootstrap_error": self._project.bootstrap_error,
                "current_status": self._project.current_status,
            })

    def add(self, _):
        pass

    def flush(self):
        pass

    def refresh(self, _):
        pass

    def close(self):
        self.closed = True


class _FakeQuery:
    def __init__(self, session, model):
        self.session = session
        self.model = model

    def filter(self, *_, **__):
        return self

    def first(self):
        cls_name = self.model.__name__
        if cls_name == "Project":
            return self.session._project
        if cls_name == "User":
            return self.session._user
        return None


def _make_session_factory(project, user):
    session = _FakeSession(project=project, user=user)
    return lambda: session, session


# ─── Test cases ──────────────────────────────────────────────────────────────


def test_bootstrap_happy_path_transitions_through_all_states():
    project = _FakeProject()
    user = _FakeUser()
    factory, session = _make_session_factory(project, user)

    fake_workflow = MagicMock(id="w1")
    fake_task = MagicMock(id="t1")
    fake_state = {"current_phase": "architecture_decision_complete"}

    with patch(
        "backend.app.services.core.project_bootstrap_service."
        "WorkflowOrchestrationService.get_or_create_workflow",
        return_value=(fake_workflow, fake_task, fake_state),
    ) as start_wf:
        ProjectBootstrapService.run_bootstrap_analysis(
            session_factory=factory,
            project_id="p1",
            user_id="u1",
        )

    # get_or_create_workflow must have been called exactly once
    assert start_wf.call_count == 1

    # Final state is ready, with no error
    assert project.bootstrap_status == STATUS_READY
    assert project.bootstrap_error is None
    assert project.current_status == "active"

    # Status transitions go through analyzing → context_building → ready
    statuses = [c["bootstrap_status"] for c in session.commits]
    assert STATUS_ANALYZING in statuses
    assert STATUS_CONTEXT_BUILDING in statuses
    assert STATUS_READY in statuses
    assert statuses.index(STATUS_ANALYZING) < statuses.index(STATUS_READY)

    # Session was closed (no dangling connection)
    assert session.closed is True


def test_bootstrap_force_routes_to_reanalyze_not_get_or_create():
    """A forced re-analysis must call WorkflowOrchestrationService.reanalyze
    (which re-invokes the LLM + bypasses the cache), NOT get_or_create_workflow
    (which would reuse the active workflow and skip analysis entirely)."""
    project = _FakeProject()
    user = _FakeUser()
    factory, session = _make_session_factory(project, user)

    fake = (MagicMock(id="w1"), MagicMock(id="t1"), {"current_phase": "architecture_decision_complete"})

    with patch(
        "backend.app.services.core.project_bootstrap_service."
        "WorkflowOrchestrationService.reanalyze",
        return_value=fake,
    ) as reanalyze, patch(
        "backend.app.services.core.project_bootstrap_service."
        "WorkflowOrchestrationService.get_or_create_workflow",
    ) as get_or_create:
        ProjectBootstrapService.run_bootstrap_analysis(
            session_factory=factory,
            project_id="p1",
            user_id="u1",
            force=True,
        )

    assert reanalyze.call_count == 1
    get_or_create.assert_not_called()
    assert project.bootstrap_status == STATUS_READY
    assert project.bootstrap_error is None


def test_bootstrap_default_uses_get_or_create_not_reanalyze():
    """Without force, the normal bootstrap path must NOT force a re-analysis."""
    project = _FakeProject()
    user = _FakeUser()
    factory, session = _make_session_factory(project, user)

    fake = (MagicMock(id="w1"), MagicMock(id="t1"), {"current_phase": "architecture_decision_complete"})

    with patch(
        "backend.app.services.core.project_bootstrap_service."
        "WorkflowOrchestrationService.get_or_create_workflow",
        return_value=fake,
    ) as get_or_create, patch(
        "backend.app.services.core.project_bootstrap_service."
        "WorkflowOrchestrationService.reanalyze",
    ) as reanalyze:
        ProjectBootstrapService.run_bootstrap_analysis(
            session_factory=factory,
            project_id="p1",
            user_id="u1",
        )

    assert get_or_create.call_count == 1
    reanalyze.assert_not_called()


def test_bootstrap_records_structured_failure_on_orchestrator_error():
    project = _FakeProject()
    user = _FakeUser()
    factory, session = _make_session_factory(project, user)

    boom = RuntimeError("repo clone exploded")

    with patch(
        "backend.app.services.core.project_bootstrap_service."
        "WorkflowOrchestrationService.get_or_create_workflow",
        side_effect=boom,
    ):
        # Bootstrap MUST NOT re-raise — it runs in a background task and the
        # only way the user sees the failure is through bootstrap_error.
        ProjectBootstrapService.run_bootstrap_analysis(
            session_factory=factory,
            project_id="p1",
            user_id="u1",
        )

    assert project.bootstrap_status == STATUS_FAILED
    assert project.bootstrap_error is not None
    assert "RuntimeError" in project.bootstrap_error
    assert "repo clone exploded" in project.bootstrap_error
    assert project.current_status == "failed"


def test_bootstrap_short_circuits_when_no_repository_url():
    project = _FakeProject(repo_url=None)
    user = _FakeUser()
    factory, session = _make_session_factory(project, user)

    # Even though we patch get_or_create_workflow, it must NOT be called.
    with patch(
        "backend.app.services.core.project_bootstrap_service."
        "WorkflowOrchestrationService.get_or_create_workflow",
    ) as start_wf:
        ProjectBootstrapService.run_bootstrap_analysis(
            session_factory=factory,
            project_id="p1",
            user_id="u1",
        )
        start_wf.assert_not_called()

    assert project.bootstrap_status == STATUS_READY


def test_bootstrap_aborts_when_user_missing():
    project = _FakeProject()
    factory, session = _make_session_factory(project, user=None)

    ProjectBootstrapService.run_bootstrap_analysis(
        session_factory=factory,
        project_id="p1",
        user_id="ghost",
    )

    assert project.bootstrap_status == STATUS_FAILED
    assert "Bootstrap user ghost not found" in (project.bootstrap_error or "")


def test_reset_for_retry_clears_failure_state():
    """The retry endpoint should hand a clean slate to the next bootstrap."""
    project = _FakeProject()
    project.bootstrap_status = STATUS_FAILED
    project.bootstrap_error = "previous failure"
    session = _FakeSession(project=project)

    ProjectBootstrapService.reset_for_retry(session, project)

    assert project.bootstrap_status == "pending"
    assert project.bootstrap_error is None
