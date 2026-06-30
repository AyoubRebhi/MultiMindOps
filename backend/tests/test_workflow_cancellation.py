"""Workflow cancellation — cancel the deployment/observation phases.

Pins the contract:

* only GITHUB_ACTIONS_GENERATION / REPOSITORY_INSTALLATION / WORKFLOW_MONITORING
  are cancellable (else 400),
* an in-flight GitHub Actions run is cancelled via the cancel API (observe →
  cancel), a finished run is left alone,
* the workflow is marked ``status = cancelled`` and ALL artifacts + phase records
  are preserved (so the run is resumable),
* cancelling is idempotent.

The GitHub seams (observe client + cancel client) are injected, so no network.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.core.workflow_cancellation_service import (
    CANCELLED_STATUS,
    WorkflowCancellationService,
)
from backend.app.services.workflow_monitoring.github_actions_cancel_client import (
    CancelRunOutcome,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    Project.__table__.create(engine)
    Workflow.__table__.create(engine)
    Artifact.__table__.create(engine)
    ArtifactVersion.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _project(db, *, repo="https://github.com/acme/widget"):
    p = Project(id="p1", owner_id="u1", name="Widget", repository_url=repo, current_status="active")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _workflow(db, *, current_phase, status, phases_state):
    wf = Workflow(
        id="wf1", project_id="p1", started_by="u1",
        current_phase=current_phase, status=status, phases_state=phases_state, logs=[],
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def _seed_artifact(db):
    ArtifactPersistenceService.upsert_artifact(
        db, project_id="p1", workflow_id="wf1", artifact_type="github_actions",
        artifact_subtype=".github/workflows/deploy.yml", content="name: deploy",
        generated_by_agent="t", validation_status="passed",
    )
    db.commit()


class _FakeClient:
    """Returns a canned latest run per workflow file (None = no run)."""

    def __init__(self, runs):
        self._runs = runs  # {"bootstrap.yml": {...} | None, "deploy.yml": ...}

    def latest_run(self, owner, repo, workflow_file, *, branch=None):
        return self._runs.get(workflow_file)

    def run_jobs(self, owner, repo, run_id):
        return []


def _active_run(run_id):
    return {
        "id": run_id, "run_number": 2, "status": "in_progress", "conclusion": None,
        "head_branch": "multiminds/devops-pipelines", "html_url": "https://github.com/x/y/runs/1",
        "run_started_at": "2026-06-29T00:00:00Z",
    }


def _completed_run(run_id):
    return {
        "id": run_id, "run_number": 2, "status": "completed", "conclusion": "success",
        "run_started_at": "2026-06-29T00:00:00Z", "updated_at": "2026-06-29T00:05:00Z",
    }


# ── Gate ────────────────────────────────────────────────────────────────────


def test_cancel_rejected_at_non_cancellable_phase(db):
    project = _project(db)
    wf = _workflow(db, current_phase="DOCKER", status="running",
                   phases_state={"DOCKER": {"status": "running"}})
    with pytest.raises(ValueError, match="cannot be cancelled"):
        WorkflowCancellationService.cancel(db, project=project, workflow=wf)


@pytest.mark.parametrize(
    "phase", ["GITHUB_ACTIONS_GENERATION", "REPOSITORY_INSTALLATION", "WORKFLOW_MONITORING"],
)
def test_cancel_allowed_at_each_deployment_phase(db, phase, monkeypatch):
    monkeypatch.setattr(CredentialsService, "get_credential", staticmethod(lambda *a, **k: None))
    project = _project(db)
    wf = _workflow(db, current_phase=phase, status="completed",
                   phases_state={phase: {"status": "completed"}})
    result = WorkflowCancellationService.cancel(db, project=project, workflow=wf)
    assert result["status"] == CANCELLED_STATUS
    assert wf.status == CANCELLED_STATUS


# ── Mark cancelled + preserve artifacts/phases ──────────────────────────────


def test_cancel_marks_status_and_preserves_everything(db, monkeypatch):
    # No token → no GitHub call; cancellation still marks the workflow.
    monkeypatch.setattr(CredentialsService, "get_credential", staticmethod(lambda *a, **k: None))
    project = _project(db)
    _seed_artifact(db)
    phases = {
        "GITHUB_ACTIONS_GENERATION": {"status": "completed"},
        "REPOSITORY_INSTALLATION": {"status": "completed", "branch": "x"},
        "WORKFLOW_MONITORING": {"status": "monitoring"},
    }
    wf = _workflow(db, current_phase="WORKFLOW_MONITORING", status="completed",
                   phases_state=dict(phases))

    result = WorkflowCancellationService.cancel(db, project=project, workflow=wf, user_id="u1")

    assert wf.status == CANCELLED_STATUS
    assert wf.finished_at is not None
    assert result["resumable"] is True
    # phases_state is untouched — every completed phase keeps its status so the
    # run can resume from a previous phase.
    assert wf.phases_state == phases
    # Artifact preserved.
    rows = db.query(Artifact).filter(Artifact.project_id == "p1").all()
    assert len(rows) == 1
    # Audit entry recorded in Workflow.logs (no migration).
    events = [e for e in (wf.logs or []) if e.get("event") == "workflow_cancelled"]
    assert len(events) == 1
    assert events[0]["phase"] == "WORKFLOW_MONITORING"
    assert events[0]["cancelled_by"] == "u1"


# ── GitHub run cancellation (observe → cancel) ──────────────────────────────


def test_cancel_cancels_active_github_run(db, monkeypatch):
    monkeypatch.setattr(CredentialsService, "get_credential", staticmethod(lambda *a, **k: "tok"))
    project = _project(db)
    wf = _workflow(db, current_phase="WORKFLOW_MONITORING", status="completed",
                   phases_state={"WORKFLOW_MONITORING": {"status": "monitoring"}})

    calls = []

    def fake_canceller(*, owner, repo, token, run_id):
        calls.append(run_id)
        return CancelRunOutcome(run_id=run_id, requested=True, status_code=202)

    client = _FakeClient({"bootstrap.yml": _active_run(55), "deploy.yml": None})

    result = WorkflowCancellationService.cancel(
        db, project=project, workflow=wf, client=client, canceller=fake_canceller,
    )

    assert calls == [55]  # only the active bootstrap run was cancelled
    assert wf.status == CANCELLED_STATUS
    runs = result["cancelled_runs"]
    assert len(runs) == 1
    assert runs[0]["pipeline"] == "bootstrap"
    assert runs[0]["requested"] is True


def test_cancel_skips_finished_run(db, monkeypatch):
    monkeypatch.setattr(CredentialsService, "get_credential", staticmethod(lambda *a, **k: "tok"))
    project = _project(db)
    wf = _workflow(db, current_phase="WORKFLOW_MONITORING", status="completed",
                   phases_state={"WORKFLOW_MONITORING": {"status": "monitoring"}})

    calls = []

    def fake_canceller(*, owner, repo, token, run_id):
        calls.append(run_id)
        return CancelRunOutcome(run_id=run_id, requested=True)

    client = _FakeClient({"bootstrap.yml": _completed_run(9), "deploy.yml": None})

    result = WorkflowCancellationService.cancel(
        db, project=project, workflow=wf, client=client, canceller=fake_canceller,
    )
    assert calls == []  # the run already finished — nothing cancelled
    assert result["cancelled_runs"] == []
    assert wf.status == CANCELLED_STATUS


# ── Idempotency ─────────────────────────────────────────────────────────────


def test_cancel_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(CredentialsService, "get_credential", staticmethod(lambda *a, **k: "tok"))
    project = _project(db)
    wf = _workflow(db, current_phase="WORKFLOW_MONITORING", status=CANCELLED_STATUS,
                   phases_state={"WORKFLOW_MONITORING": {"status": "monitoring"}})

    calls = []

    def fake_canceller(*, owner, repo, token, run_id):
        calls.append(run_id)
        return CancelRunOutcome(run_id=run_id, requested=True)

    client = _FakeClient({"bootstrap.yml": _active_run(1), "deploy.yml": None})
    result = WorkflowCancellationService.cancel(
        db, project=project, workflow=wf, client=client, canceller=fake_canceller,
    )
    # Already cancelled → no GitHub calls, no new state.
    assert calls == []
    assert result["status"] == CANCELLED_STATUS
    assert "already cancelled" in result["message"].lower()
