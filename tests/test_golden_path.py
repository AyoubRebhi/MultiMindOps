"""Golden-path contract for the unified, deterministic workflow engine.

Exercises the canonical workflow end-to-end against a REAL in-memory SQLite
session (not mocks) — only the LLM agent calls and the encrypted-credential
store are stubbed, because the behaviour worth proving is the orchestration +
persistence wiring, not the model output:

    INPUT → ANALYSIS → INFRASTRUCTURE (tf generate → rehydrate → validate)
          → DOCKER

Proven contracts:
* Every phase produces Artifact rows in the DB.
* Workflow.phases_state is the single source of truth and stays consistent.
* Terraform generation rehydrates the real generated HCL onto disk.
* Re-running a phase does NOT duplicate artifacts (idempotent upsert).
* A failed Terraform phase does NOT corrupt previously-produced artifacts.
* The prerequisite gate rejects out-of-order phase execution.
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


# ── DB fixture ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """In-memory SQLite with the tables the workflow engine touches.

    JSONB columns fall back to JSON on SQLite via each model's ``with_variant``
    so the real rows can be created. FK targets that we don't insert into
    (users) are left uncreated — SQLite leaves FK enforcement off by default.
    """
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


# ── Stubs ─────────────────────────────────────────────────────────────────────

_ARCH_STATE = {
    "prompt": "deploy my app",
    "current_phase": "architecture_decision_complete",
    "plan": {"required_artifacts": ["Dockerfile", "main.tf"], "project_name": "golden"},
    "architecture_decision": {"strategies": [{"id": "balanced"}]},
    "logs": [],
}

_DOCKER_STATE = {
    "current_phase": "docker_completed",
    # Keys must be canonical DOCKER_ARTIFACT_KEYS to survive initialize_from_state.
    "infra": {
        "artifacts": {"dockerfile": "FROM python:3.11-slim\nCMD [\"python\",\"app.py\"]\n"},
        "used_llm": True,
        "fallback_used": False,
        "generation_mode": "llm",
    },
    "logs": [],
}

_TF_STATE = {
    "current_phase": "terraform_completed",
    "infra": {
        "artifacts": {
            "main.tf": 'resource "null_resource" "x" {}\n',
            "providers.tf": 'terraform {}\n',
        },
    },
    "logs": [],
}


@pytest.fixture
def stub_agents(monkeypatch, tmp_path):
    """Stub the LLM agent + credential store; redirect terraform disk storage."""
    from backend.app.agents.orchestrator_agent import OrchestratorAgent
    from backend.app.services.core.credentials_service import CredentialsService
    from backend.app.services.core.project_context_service import ProjectContextService

    monkeypatch.setattr(OrchestratorAgent, "__init__", lambda self: None)
    monkeypatch.setattr(
        OrchestratorAgent, "run_architecture_decision_phase",
        lambda self, **kw: dict(_ARCH_STATE),
    )
    monkeypatch.setattr(
        OrchestratorAgent, "resume_with_selected_plan",
        lambda self, prior_state, selected_plan_id: {**prior_state, "selected_plan_id": selected_plan_id},
    )
    monkeypatch.setattr(
        OrchestratorAgent, "run_docker_phase",
        lambda self, prior_state: {**prior_state, **_DOCKER_STATE},
    )
    monkeypatch.setattr(
        OrchestratorAgent, "run_terraform_phase_only",
        lambda self, prior_state, task_id=None, project_id=None: {**prior_state, **_TF_STATE},
    )

    monkeypatch.setattr(CredentialsService, "get_credential", lambda *a, **k: None)
    monkeypatch.setattr(CredentialsService, "hydrate_state", lambda db, state, project_id=None: state)
    monkeypatch.setattr(ProjectContextService, "capture_from_state", lambda *a, **k: [])

    # Terraform rehydration writes here instead of the process cwd.
    monkeypatch.setenv("TF_PIPELINE_STORAGE_ROOT", str(tmp_path / "generated_terraform"))


@pytest.fixture
def project(db):
    proj = Project(id="proj-1", owner_id="user-1", name="golden", current_status="active")
    db.add(proj)
    db.commit()
    return proj


def _count(db, **filters):
    q = db.query(Artifact)
    for k, v in filters.items():
        q = q.filter(getattr(Artifact, k) == v)
    return q.count()


# ── The golden path ─────────────────────────────────────────────────────────

def test_golden_path(db, project, stub_agents):
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )
    from backend.app.services.terraform_pipeline import TerraformPipelineService

    user = types.SimpleNamespace(id="user-1")

    # 1. INPUT → ANALYSIS (architecture decision) ────────────────────────────
    workflow, task, _state = WOS.start_workflow(
        db, project=project, user=user, prompt="deploy my app",
    )
    assert workflow.status == "awaiting_input"
    assert "ARCHITECTURE_DECISION" in workflow.phases_state

    # Prerequisite gate: DOCKER before plan selection is rejected.
    with pytest.raises(ValueError):
        WOS.run_phase(db, project=project, workflow=workflow, task=task, phase="DOCKER")

    # 2. Plan selection ──────────────────────────────────────────────────────
    WOS.select_plan(db, workflow=workflow, task=task, plan_id="balanced")
    assert workflow.phases_state["PLAN_SELECTED"]["status"] == "completed"

    # 3. INFRASTRUCTURE — Terraform generate → DB + rehydrate to disk ─────────
    _s, tf_ids = WOS.run_phase(
        db, project=project, workflow=workflow, task=task, phase="TERRAFORM_GENERATION",
    )
    gen = workflow.phases_state["TERRAFORM_GENERATION"]
    assert gen["status"] == "completed"
    assert _count(db, project_id="proj-1", artifact_type="terraform") == 2  # main.tf, providers.tf
    # Rehydrated onto disk = the REAL generated HCL is what validate/plan will run.
    artifact_id = gen["artifact_id"]
    tf_dir = TerraformPipelineService().artifact_path(artifact_id)
    assert tf_dir.exists()
    assert (tf_dir / "main.tf").exists()
    # DB is the source of truth for rehydration.
    files = __import__(
        "backend.app.services.core.artifact_persistence_service",
        fromlist=["ArtifactPersistenceService"],
    ).ArtifactPersistenceService.get_terraform_files(db, project_id="proj-1")
    assert set(files) == {"main.tf", "providers.tf"}

    # 4. INFRASTRUCTURE — Terraform validate (async durable job enqueued) ─────
    WOS.run_phase(
        db, project=project, workflow=workflow, task=task, phase="TERRAFORM_VALIDATION",
    )
    assert workflow.phases_state["TERRAFORM_VALIDATION"]["status"] == "running"
    assert db.query(ExecutionJob).filter(ExecutionJob.phase == "terraform_validate").count() == 1
    # Worker finaliser records the outcome on the authoritative Workflow row.
    WOS.record_terraform_phase_result(
        db, workflow_id=workflow.id, task_id=task.id, project_id="proj-1",
        phase="TERRAFORM_VALIDATION", ok=True, results=[], artifact_id=artifact_id,
    )
    assert workflow.phases_state["TERRAFORM_VALIDATION"]["status"] == "completed"
    assert _count(db, project_id="proj-1", artifact_type="validation_report") == 1

    # 5. DOCKER — dockerfile generate → DB ───────────────────────────────────
    _s, dk_ids = WOS.run_phase(
        db, project=project, workflow=workflow, task=task, phase="DOCKER",
    )
    assert workflow.phases_state["DOCKER"]["status"] == "completed"
    assert _count(db, project_id="proj-1", artifact_type="docker") == 1
    dockerfile = (
        db.query(Artifact)
        .filter(Artifact.project_id == "proj-1", Artifact.artifact_type == "docker")
        .first()
    )
    assert dockerfile.version == 1

    # 6. Idempotency — re-running DOCKER with identical content adds no rows ──
    WOS.run_phase(db, project=project, workflow=workflow, task=task, phase="DOCKER")
    assert _count(db, project_id="proj-1", artifact_type="docker") == 1
    db.refresh(dockerfile)
    assert dockerfile.version == 1  # no new version: same content hash

    # 7. Failure isolation — a failed plan must not corrupt prior artifacts ───
    docker_before = _count(db, project_id="proj-1", artifact_type="docker")
    tf_before = _count(db, project_id="proj-1", artifact_type="terraform")
    WOS.record_terraform_phase_result(
        db, workflow_id=workflow.id, task_id=task.id, project_id="proj-1",
        phase="TERRAFORM_PLAN", ok=False, results=[], artifact_id=artifact_id,
        error="terraform reported a non-zero exit",
    )
    assert workflow.phases_state["TERRAFORM_PLAN"]["status"] == "failed"
    # Prior phases + their artifacts are untouched.
    assert workflow.phases_state["DOCKER"]["status"] == "completed"
    assert workflow.phases_state["TERRAFORM_GENERATION"]["status"] == "completed"
    assert _count(db, project_id="proj-1", artifact_type="docker") == docker_before
    assert _count(db, project_id="proj-1", artifact_type="terraform") == tf_before


def test_docker_build_outcome_lands_on_workflow(db, project):
    """record_build_result mirrors the build outcome onto Workflow.phases_state."""
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )

    wf = Workflow(id="wf-x", project_id="proj-1", status="running", phases_state={})
    db.add(wf)
    task = Task(id="task-x", prompt="p", project_id="proj-1", workflow_id="wf-x")
    db.add(task)
    db.commit()

    WOS.record_build_result(db, task, status="completed", extra={"build_number": 1})

    db.refresh(wf)
    assert wf.phases_state["DOCKER_BUILD"]["status"] == "completed"
    assert wf.status == "completed"
    assert wf.finished_at is not None
