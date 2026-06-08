"""Observability + replay layer contracts.

Covers the four tasks of the hardening phase against a REAL in-memory SQLite
session (LLM never invoked — replay/observability must work without it):

1. Artifact completeness — docker-compose / env / .dockerignore are DB-backed.
2. WorkflowExecutionTrace — ordered, complete, idempotent materialisation.
3. Replay — DB-only, no LLM, re-enqueues validate/plan/build deterministically.
4. /debug payload — timeline + artifacts + classifications + trace + completeness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.execution_job import ExecutionJob
from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.models.workflow_execution_trace import WorkflowExecutionTrace


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for model in (Project, Workflow, Task, Artifact, ArtifactVersion,
                  ExecutionJob, WorkflowExecutionTrace):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def project(db):
    proj = Project(id="proj-1", owner_id="user-1", name="obs", current_status="active")
    db.add(proj)
    db.commit()
    return proj


# ── Task 1: artifact completeness ────────────────────────────────────────────

def test_classify_canonical_docker_keys():
    from backend.app.services.core.artifact_persistence_service import classify_artifact
    assert classify_artifact("dockerfile") == "docker"
    assert classify_artifact("dockerignore") == "docker"
    assert classify_artifact("docker_compose") == "docker"
    assert classify_artifact("env_example") == "docker"
    assert classify_artifact(".env.example") == "docker"
    assert classify_artifact("docker-compose.yml") == "docker"


def test_all_docker_build_inputs_persist(db, project):
    """compose/env/.dockerignore must become DB-backed, not disk-only."""
    from backend.app.services.core.artifact_persistence_service import (
        ArtifactPersistenceService as APS,
    )
    state = {
        "infra": {
            "artifacts": {
                "dockerfile": "FROM python:3.11\n",
                "dockerignore": "__pycache__\n",
                "docker_compose": "services: {}\n",
                "env_example": "PORT=8080\n",
            }
        }
    }
    persisted = APS.persist_state_artifacts(
        db, project_id="proj-1", workflow_id=None, state=state,
        generated_by_agent="test",
    )
    subtypes = {a.artifact_subtype for a in persisted}
    assert subtypes == {"dockerfile", "dockerignore", "docker_compose", "env_example"}

    # get_docker_artifacts round-trips them by canonical key.
    docker = APS.get_docker_artifacts(db, project_id="proj-1")
    assert set(docker) == {"dockerfile", "dockerignore", "docker_compose", "env_example"}
    assert docker["docker_compose"] == "services: {}\n"


# ── Task 2: execution trace ──────────────────────────────────────────────────

def _seed_workflow_with_phases(db) -> Workflow:
    base = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    wf = Workflow(
        id="wf-1", project_id="proj-1", status="running",
        current_phase="DOCKER",
        phases_state={
            "ARCHITECTURE_DECISION": {
                "status": "awaiting_input",
                "updated_at": base.isoformat(),
            },
            "PLAN_SELECTED": {
                "status": "completed",
                "updated_at": (base + timedelta(minutes=1)).isoformat(),
                "plan_id": "balanced",
            },
            "TERRAFORM_GENERATION": {
                "status": "completed",
                "updated_at": (base + timedelta(minutes=2)).isoformat(),
                "artifact_id": "tf-abc",
                "validation_status": "degraded",
                "failure_classification": "NETWORK_ERROR",
            },
            "DOCKER": {
                "status": "completed",
                "updated_at": (base + timedelta(minutes=3)).isoformat(),
            },
        },
    )
    db.add(wf)
    db.commit()
    return wf


def test_trace_sync_is_ordered_and_complete(db, project):
    from backend.app.services.core.workflow_trace_service import WorkflowTraceService
    wf = _seed_workflow_with_phases(db)

    rows = WorkflowTraceService.sync_from_workflow(db, wf)
    phases = [r.phase for r in rows]
    assert phases == [
        "ARCHITECTURE_DECISION", "PLAN_SELECTED", "TERRAFORM_GENERATION", "DOCKER",
    ]
    # Ordered timestamps; each row has start ≤ end where both known.
    for r in rows:
        if r.started_at and r.ended_at:
            assert r.ended_at >= r.started_at
    # Failure classification carried through.
    tf = next(r for r in rows if r.phase == "TERRAFORM_GENERATION")
    assert tf.failure_classification == "NETWORK_ERROR"
    assert tf.inputs.get("validation_status") == "degraded"
    # Plan inputs captured.
    plan = next(r for r in rows if r.phase == "PLAN_SELECTED")
    assert plan.inputs.get("plan_id") == "balanced"


def test_trace_sync_is_idempotent(db, project):
    from backend.app.services.core.workflow_trace_service import WorkflowTraceService
    wf = _seed_workflow_with_phases(db)
    WorkflowTraceService.sync_from_workflow(db, wf)
    WorkflowTraceService.sync_from_workflow(db, wf)
    live = (
        db.query(WorkflowExecutionTrace)
        .filter(WorkflowExecutionTrace.source == "live")
        .all()
    )
    assert len(live) == 4  # no duplicate live rows


# ── Task 3: replay ───────────────────────────────────────────────────────────

@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setenv("TF_PIPELINE_STORAGE_ROOT", str(tmp_path / "generated_terraform"))


def test_replay_is_db_only_and_enqueues_jobs(db, project, storage):
    from backend.app.services.core.artifact_persistence_service import (
        ArtifactPersistenceService as APS,
    )
    from backend.app.services.core.workflow_replay_service import WorkflowReplayService

    wf = Workflow(id="wf-r", project_id="proj-1", status="running", phases_state={})
    db.add(wf)
    task = Task(id="task-r", prompt="p", project_id="proj-1", workflow_id="wf-r",
                workflow_state={"repo_url": "https://example.com/r", "plan": {"project_name": "demo"}})
    db.add(task)
    db.commit()

    # Seed DB artifacts (terraform + docker) — the ONLY inputs replay may use.
    APS.upsert_artifact(db, project_id="proj-1", workflow_id="wf-r",
                        artifact_type="terraform", artifact_subtype="main.tf",
                        content='resource "null_resource" "x" {}\n')
    APS.upsert_artifact(db, project_id="proj-1", workflow_id="wf-r",
                        artifact_type="docker", artifact_subtype="dockerfile",
                        content="FROM python:3.11\n")
    db.commit()

    result = WorkflowReplayService.replay(db, project=project, workflow=wf, task=task)

    assert result["llm_used"] is False
    assert result["regenerated"] is False
    assert result["replayed"] is True
    phases = {s["phase"] for s in result["steps"]}
    assert phases == {"TERRAFORM_VALIDATION", "TERRAFORM_PLAN", "DOCKER_BUILD"}

    # Durable jobs were enqueued (validate, plan, build).
    job_phases = {j.phase for j in db.query(ExecutionJob).all()}
    assert job_phases == {"terraform_validate", "terraform_plan", "docker_build"}

    # The docker_build job carries DB artifacts (NOT regenerated).
    build = db.query(ExecutionJob).filter(ExecutionJob.phase == "docker_build").first()
    assert build.execution_context["artifacts"]["dockerfile"] == "FROM python:3.11\n"

    # Replay trace rows recorded with source='replay'.
    replay_rows = (
        db.query(WorkflowExecutionTrace)
        .filter(WorkflowExecutionTrace.source == "replay")
        .all()
    )
    assert {r.phase for r in replay_rows} == {"TERRAFORM_VALIDATION", "TERRAFORM_PLAN", "DOCKER_BUILD"}


def test_replay_skips_when_no_db_artifacts(db, project, storage):
    from backend.app.services.core.workflow_replay_service import WorkflowReplayService
    wf = Workflow(id="wf-empty", project_id="proj-1", status="running", phases_state={})
    db.add(wf)
    task = Task(id="task-e", prompt="p", project_id="proj-1", workflow_id="wf-empty",
                workflow_state={})
    db.add(task)
    db.commit()

    result = WorkflowReplayService.replay(db, project=project, workflow=wf, task=task)
    assert result["replayed"] is False
    assert db.query(ExecutionJob).count() == 0
    assert {s["phase"] for s in result["skipped"]} == {"TERRAFORM", "DOCKER_BUILD"}


# ── Task 4: /debug payload ───────────────────────────────────────────────────

def test_debug_payload_shape_and_completeness(db, project):
    from backend.app.services.core.artifact_persistence_service import (
        ArtifactPersistenceService as APS,
    )
    from backend.app.services.core.workflow_trace_service import WorkflowTraceService
    wf = _seed_workflow_with_phases(db)
    APS.upsert_artifact(db, project_id="proj-1", workflow_id="wf-1",
                        artifact_type="docker", artifact_subtype="dockerfile",
                        content="FROM python:3.11\n")
    db.commit()

    task_state = {"infra": {"artifacts": {"dockerfile": "FROM python:3.11\n"}}}
    payload = WorkflowTraceService.build_debug_payload(db, workflow=wf, task_state=task_state)

    assert set(payload) >= {
        "phase_timeline", "artifacts", "failure_classifications",
        "execution_trace", "artifact_completeness",
    }
    # Timeline ordered and complete.
    assert [e["phase"] for e in payload["phase_timeline"]] == [
        "ARCHITECTURE_DECISION", "PLAN_SELECTED", "TERRAFORM_GENERATION", "DOCKER",
    ]
    # Failure classification surfaced.
    assert any(
        f["classification"] == "NETWORK_ERROR" for f in payload["failure_classifications"]
    )
    # Artifacts DB-backed; completeness satisfied (dockerfile is persisted).
    assert any(a["subtype"] == "dockerfile" for a in payload["artifacts"])
    assert payload["artifact_completeness"]["complete"] is True
    assert payload["execution_trace"]  # non-empty, ordered trace
