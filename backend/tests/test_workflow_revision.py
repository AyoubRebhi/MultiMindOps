"""Workflow revision — regenerate a phase + invalidate downstream.

Covers the iterative-redesign feature (WorkflowRevisionService):

* the dependency closure (``downstream_phases``) matches the lifecycle DAG,
* ``_invalidate_downstream`` flips only the RECORDED downstream phases to
  ``invalidated`` while preserving their previous status,
* ``_diff_versions`` reports exactly the artifacts whose version was bumped,
* the revision log round-trips through ``Workflow.logs`` (no migration),
* the full ``regenerate_phase`` flow (with the engine's ``run_phase`` stubbed)
  bumps the revision, supersedes the old artifact version WITHOUT deleting it,
  invalidates the transitive downstream phases, and reopens the run.

Runs against a real in-memory SQLite session because the service reads/writes
the JSON ``phases_state`` / ``logs`` columns and queries the artifact tables.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import every related model so the SQLAlchemy mapper registry is fully
# configured (Workflow ⋈ Project ⋈ User ⋈ Artifact relationships resolve).
from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.workflow_orchestration_service import (
    WorkflowOrchestrationService,
)
from backend.app.services.core.workflow_revision_service import (
    INVALIDATED_STATUS,
    WorkflowRevisionService,
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


def _completed(extra=None):
    return {"status": "completed", "updated_at": "2026-06-29T00:00:00+00:00", **(extra or {})}


def _make_workflow(db, phases_state, *, status="completed", current_phase="GITHUB_ACTIONS_GENERATION"):
    wf = Workflow(
        id="wf-1",
        project_id="p1",
        started_by="u1",
        current_phase=current_phase,
        status=status,
        phases_state=phases_state,
        logs=[],
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


# ─── Dependency closure ──────────────────────────────────────────────────────


def test_downstream_of_terraform_generation():
    assert WorkflowRevisionService.downstream_phases("TERRAFORM_GENERATION") == [
        "TERRAFORM_VALIDATION",
        "TERRAFORM_PLAN",
        "GITHUB_ACTIONS_GENERATION",
        "REPOSITORY_INSTALLATION",
        "WORKFLOW_MONITORING",
    ]


def test_downstream_of_docker():
    assert WorkflowRevisionService.downstream_phases("DOCKER") == [
        "DOCKER_BUILD",
        "GITHUB_ACTIONS_GENERATION",
        "REPOSITORY_INSTALLATION",
        "WORKFLOW_MONITORING",
    ]


def test_downstream_of_terminal_phase_is_empty():
    assert WorkflowRevisionService.downstream_phases("WORKFLOW_MONITORING") == []


def test_impacted_phases_only_lists_recorded_downstream(db):
    wf = _make_workflow(
        db,
        {
            "PLAN_SELECTED": _completed(),
            "TERRAFORM_GENERATION": _completed(),
            "GITHUB_ACTIONS_GENERATION": _completed(),
            # REPOSITORY_INSTALLATION / WORKFLOW_MONITORING never ran.
        },
    )
    impacted = WorkflowRevisionService.impacted_phases(wf, "TERRAFORM_GENERATION")
    assert impacted == ["GITHUB_ACTIONS_GENERATION"]


# ─── Invalidation ──────────────────────────────────────────────────────────


def test_invalidate_downstream_preserves_previous_status(db):
    wf = _make_workflow(
        db,
        {
            "DOCKER": _completed(),  # NOT downstream of terraform → untouched
            "TERRAFORM_GENERATION": _completed(),
            "GITHUB_ACTIONS_GENERATION": _completed(),
            "REPOSITORY_INSTALLATION": _completed(),
            "WORKFLOW_MONITORING": {"status": "monitoring"},
        },
    )
    changed = WorkflowRevisionService._invalidate_downstream(
        wf, "TERRAFORM_GENERATION", user_id="u1",
    )
    assert changed == [
        "GITHUB_ACTIONS_GENERATION",
        "REPOSITORY_INSTALLATION",
        "WORKFLOW_MONITORING",
    ]
    gh = wf.phases_state["GITHUB_ACTIONS_GENERATION"]
    assert gh["status"] == INVALIDATED_STATUS
    assert gh["previous_status"] == "completed"
    assert gh["invalidated_by"] == "TERRAFORM_GENERATION"
    mon = wf.phases_state["WORKFLOW_MONITORING"]
    assert mon["previous_status"] == "monitoring"
    # The non-downstream DOCKER phase is left exactly as it was.
    assert wf.phases_state["DOCKER"]["status"] == "completed"


def test_invalidate_is_idempotent(db):
    wf = _make_workflow(
        db,
        {
            "TERRAFORM_GENERATION": _completed(),
            "GITHUB_ACTIONS_GENERATION": _completed(),
        },
    )
    WorkflowRevisionService._invalidate_downstream(wf, "TERRAFORM_GENERATION", user_id="u1")
    # A second pass finds GH already invalidated and changes nothing.
    changed = WorkflowRevisionService._invalidate_downstream(
        wf, "TERRAFORM_GENERATION", user_id="u1",
    )
    assert changed == []
    assert wf.phases_state["GITHUB_ACTIONS_GENERATION"]["previous_status"] == "completed"


# ─── Version diff (superseded artifacts) ─────────────────────────────────────


def test_diff_versions_reports_only_bumped():
    before = {"terraform/terraform_main": 1, "terraform/terraform_vpc": 1}
    after = {
        "terraform/terraform_main": 2,   # bumped → superseded
        "terraform/terraform_vpc": 1,    # unchanged → omitted
        "terraform/terraform_outputs": 1,  # brand new → nothing to supersede
    }
    assert WorkflowRevisionService._diff_versions(before, after) == {
        "terraform/terraform_main": {"from": 1, "to": 2},
    }


# ─── Revision history (Workflow.logs) ────────────────────────────────────────


def test_revision_history_round_trips_newest_first(db):
    wf = _make_workflow(db, {"TERRAFORM_GENERATION": _completed()})
    WorkflowRevisionService._record_revision(
        wf, phase="DOCKER", revision=2, invalidated=["GITHUB_ACTIONS_GENERATION"],
        superseded={}, user_id="u1",
    )
    WorkflowRevisionService._record_revision(
        wf, phase="TERRAFORM_GENERATION", revision=2,
        invalidated=["GITHUB_ACTIONS_GENERATION"], superseded={}, user_id="u1",
    )
    history = WorkflowRevisionService.get_revision_history(wf)
    assert [h["phase"] for h in history] == ["TERRAFORM_GENERATION", "DOCKER"]
    assert all(h["event"] == "phase_revision" for h in history)


# ─── Full regenerate flow (engine stubbed) ───────────────────────────────────


def _seed_terraform_v1(db):
    art = ArtifactPersistenceService.upsert_artifact(
        db,
        project_id="p1",
        workflow_id="wf-1",
        artifact_type="terraform",
        artifact_subtype="terraform_main",
        content="# terraform v1",
        generated_by_agent="TerraformAgent",
        validation_status="passed",
    )
    db.commit()
    return art


def _stub_run_phase_regenerating_terraform(monkeypatch):
    """Stub the engine so 'running TERRAFORM_GENERATION' bumps the artifact."""

    def fake_run_phase(db, *, project, workflow, task, phase):
        ArtifactPersistenceService.upsert_artifact(
            db,
            project_id=project.id,
            workflow_id=workflow.id,
            artifact_type="terraform",
            artifact_subtype="terraform_main",
            content="# terraform v2 — regenerated",
            generated_by_agent="TerraformAgent",
            validation_status="passed",
        )
        phases = dict(workflow.phases_state or {})
        phases[phase] = {
            "status": "completed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        workflow.phases_state = phases
        workflow.current_phase = phase
        workflow.status = "running"
        db.commit()
        return {"logs": []}, ["artifact-id"]

    monkeypatch.setattr(
        WorkflowOrchestrationService, "run_phase", staticmethod(fake_run_phase),
    )


def test_regenerate_terraform_bumps_invalidates_and_preserves_history(db, monkeypatch):
    _seed_terraform_v1(db)
    wf = _make_workflow(
        db,
        {
            "PLAN_SELECTED": _completed(),
            "DOCKER": _completed(),
            "TERRAFORM_GENERATION": _completed(),
            "GITHUB_ACTIONS_GENERATION": _completed(),
            "REPOSITORY_INSTALLATION": _completed(),
            "WORKFLOW_MONITORING": {"status": "monitoring"},
        },
    )
    _stub_run_phase_regenerating_terraform(monkeypatch)

    result = WorkflowRevisionService.regenerate_phase(
        db,
        project=SimpleNamespace(id="p1"),
        workflow=wf,
        task=SimpleNamespace(id="t1"),
        phase="TERRAFORM_GENERATION",
        user_id="u1",
    )

    # New revision created.
    assert result["revised"] is True
    assert result["revision"] == 2
    assert wf.phases_state["TERRAFORM_GENERATION"]["revision"] == 2

    # Old artifact version preserved (v1 + v2 both in history) — no deletion.
    art = (
        db.query(Artifact)
        .filter(Artifact.project_id == "p1", Artifact.artifact_type == "terraform")
        .first()
    )
    assert art.version == 2
    versions = (
        db.query(ArtifactVersion)
        .filter(ArtifactVersion.artifact_id == art.id)
        .order_by(ArtifactVersion.version.asc())
        .all()
    )
    assert [v.version for v in versions] == [1, 2]
    assert "v1" in versions[0].content and "v2" in versions[1].content

    # Superseded record points at the bumped version.
    assert result["superseded_artifacts"] == {
        "terraform/terraform_main": {"from": 1, "to": 2},
    }

    # Downstream invalidated (the example: GITHUB_ACTIONS / INSTALLATION / MONITORING).
    assert result["invalidated_phases"] == [
        "GITHUB_ACTIONS_GENERATION",
        "REPOSITORY_INSTALLATION",
        "WORKFLOW_MONITORING",
    ]
    assert wf.phases_state["GITHUB_ACTIONS_GENERATION"]["status"] == INVALIDATED_STATUS
    assert wf.phases_state["DOCKER"]["status"] == "completed"  # sibling untouched

    # current_phase points back at the regenerated phase; run reopened.
    assert wf.current_phase == "TERRAFORM_GENERATION"
    assert wf.status == "running"

    # Revision history recorded.
    history = WorkflowRevisionService.get_revision_history(wf)
    assert len(history) == 1
    assert history[0]["phase"] == "TERRAFORM_GENERATION"
    assert history[0]["revision"] == 2
    assert history[0]["invalidated_phases"] == result["invalidated_phases"]


def test_regenerate_rejects_non_regeneratable_phase(db):
    wf = _make_workflow(db, {"REPOSITORY_INSTALLATION": _completed()})
    with pytest.raises(ValueError, match="cannot be regenerated"):
        WorkflowRevisionService.regenerate_phase(
            db,
            project=SimpleNamespace(id="p1"),
            workflow=wf,
            task=SimpleNamespace(id="t1"),
            phase="REPOSITORY_INSTALLATION",
            user_id="u1",
        )


def test_regenerate_rejects_uncompleted_phase(db):
    wf = _make_workflow(db, {"TERRAFORM_GENERATION": {"status": "running"}})
    with pytest.raises(ValueError, match="has not completed"):
        WorkflowRevisionService.regenerate_phase(
            db,
            project=SimpleNamespace(id="p1"),
            workflow=wf,
            task=SimpleNamespace(id="t1"),
            phase="TERRAFORM_GENERATION",
            user_id="u1",
        )


def test_regenerate_failed_rerun_does_not_invalidate(db, monkeypatch):
    wf = _make_workflow(
        db,
        {
            "PLAN_SELECTED": _completed(),
            "DOCKER": _completed(),
            "TERRAFORM_GENERATION": _completed(),
            "GITHUB_ACTIONS_GENERATION": _completed(),
        },
    )

    def fake_run_phase_failed(db, *, project, workflow, task, phase):
        phases = dict(workflow.phases_state or {})
        phases[phase] = {"status": "failed", "updated_at": "2026-06-29T01:00:00+00:00"}
        workflow.phases_state = phases
        workflow.current_phase = phase
        db.commit()
        return {"logs": []}, []

    monkeypatch.setattr(
        WorkflowOrchestrationService, "run_phase", staticmethod(fake_run_phase_failed),
    )

    result = WorkflowRevisionService.regenerate_phase(
        db,
        project=SimpleNamespace(id="p1"),
        workflow=wf,
        task=SimpleNamespace(id="t1"),
        phase="GITHUB_ACTIONS_GENERATION",
        user_id="u1",
    )
    assert result["revised"] is False
    assert result["invalidated_phases"] == []
    # No revision history written for a non-completing re-run.
    assert WorkflowRevisionService.get_revision_history(wf) == []
