"""TERRAFORM_GENERATION status semantics.

Generation success is DECOUPLED from the validation verdict: the phase is
`completed` whenever HCL files are produced, and only a genuine rendering /
contract failure (orchestrator `current_phase == "terraform_failed"`) fails it.
A validation finding (`terraform_validation_failed` / validation_status="failed")
is preserved in the phase payload but never fails generation — the dedicated
TERRAFORM_VALIDATION phase owns that verdict.

Exercised against a REAL in-memory SQLite session (same harness as the golden
path); only the LLM orchestrator + credential store are stubbed.
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


# ── Fixtures (mirror tests/test_golden_path.py) ──────────────────────────────

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


@pytest.fixture
def project(db):
    proj = Project(id="proj-1", owner_id="user-1", name="tfgen", current_status="active")
    db.add(proj)
    db.commit()
    return proj


_ARCH_STATE = {
    "prompt": "deploy my app",
    "current_phase": "architecture_decision_complete",
    "plan": {"required_artifacts": ["main.tf"], "project_name": "tfgen"},
    "architecture_decision": {"strategies": [{"id": "balanced"}]},
    "logs": [],
}

# Two real terraform artifact keys → classified as `terraform`, persisted as rows.
_TF_ARTIFACTS = {
    "main.tf": 'resource "null_resource" "x" {}\n',
    "providers.tf": "terraform {}\n",
}

# A full microservices-shaped set of 6 canonical terraform_* keys (each maps to a
# real .tf/.tfvars file and classifies as `terraform`).
_TF_ARTIFACTS_6 = {
    "terraform_providers": "terraform {}\n",
    "terraform_main": 'resource "null_resource" "x" {}\n',
    "terraform_variables": 'variable "p" { type = string }\n',
    "terraform_tfvars": 'p = "x"\n',
    "terraform_outputs": 'output "o" { value = "" }\n',
    "terraform_backend": "# backend placeholder\n",
}


@pytest.fixture
def tf_env(monkeypatch, tmp_path):
    """Stub the orchestrator + credential store; return a setter that pins the
    state `run_terraform_phase_only` yields for the test under exercise."""
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
        lambda self, prior_state, selected_plan_id: {
            **prior_state, "selected_plan_id": selected_plan_id,
        },
    )
    monkeypatch.setattr(CredentialsService, "get_credential", lambda *a, **k: None)
    monkeypatch.setattr(
        CredentialsService, "hydrate_state",
        lambda db, state, project_id=None: state,
    )
    monkeypatch.setattr(ProjectContextService, "capture_from_state", lambda *a, **k: [])
    monkeypatch.setenv("TF_PIPELINE_STORAGE_ROOT", str(tmp_path / "generated_terraform"))

    def _set_tf_state(state: dict) -> None:
        monkeypatch.setattr(
            OrchestratorAgent, "run_terraform_phase_only",
            lambda self, prior_state, task_id=None, project_id=None: {**prior_state, **state},
        )

    return _set_tf_state


def _run_generation(db, project):
    """Drive INPUT → plan-selected → TERRAFORM_GENERATION; return the workflow."""
    from backend.app.services.core.workflow_orchestration_service import (
        WorkflowOrchestrationService as WOS,
    )
    user = types.SimpleNamespace(id="user-1")
    workflow, task, _ = WOS.start_workflow(
        db, project=project, user=user, prompt="deploy my app",
    )
    WOS.select_plan(db, workflow=workflow, task=task, plan_id="balanced")
    WOS.run_phase(
        db, project=project, workflow=workflow, task=task,
        phase="TERRAFORM_GENERATION",
    )
    return workflow


def _terraform_rows(db):
    return (
        db.query(Artifact)
        .filter(Artifact.project_id == "proj-1", Artifact.artifact_type == "terraform")
        .count()
    )


# ── 1. Render success + validation failure → generation completed ────────────

def test_validation_failure_does_not_fail_generation(db, project, tf_env):
    """HCL rendered + inline validation flagged a defect → phase is `completed`,
    and the validation verdict is preserved on the phase payload (not dropped)."""
    tf_env({
        "current_phase": "terraform_validation_failed",
        "terraform_validation_status": "failed",
        "terraform_failure_classification": "VALIDATION_FAILED",
        "infra": {"artifacts": dict(_TF_ARTIFACTS)},
        "logs": [],
    })
    workflow = _run_generation(db, project)

    gen = workflow.phases_state["TERRAFORM_GENERATION"]
    assert gen["status"] == "completed"                      # NOT failed
    assert gen["validation_status"] == "failed"              # preserved
    assert gen["failure_classification"] == "VALIDATION_FAILED"  # preserved


# ── 2. Render exception → generation failed ──────────────────────────────────

def test_render_failure_fails_generation(db, project, tf_env):
    """A genuine rendering/contract failure (`terraform_failed`, no HCL) is the
    ONLY thing that fails the generation phase."""
    tf_env({
        "current_phase": "terraform_failed",
        "infra": {"artifacts": {}},
        "logs": [],
    })
    workflow = _run_generation(db, project)

    gen = workflow.phases_state["TERRAFORM_GENERATION"]
    assert gen["status"] == "failed"


# ── 3. Files generated with validation findings → artifacts visible ──────────

def test_artifacts_persisted_despite_validation_findings(db, project, tf_env):
    """The .tf rows land in the DB even when validation flagged the config, so
    the UI can render the generated files alongside the warning."""
    tf_env({
        "current_phase": "terraform_validation_failed",
        "terraform_validation_status": "failed",
        "terraform_failure_classification": "VALIDATION_FAILED",
        "infra": {"artifacts": dict(_TF_ARTIFACTS)},
        "logs": [],
    })
    workflow = _run_generation(db, project)

    gen = workflow.phases_state["TERRAFORM_GENERATION"]
    assert gen["status"] == "completed"
    assert gen["file_count"] == 2
    assert _terraform_rows(db) == 2  # main.tf + providers.tf visible in the DB


# ── 4. Degraded (NETWORK_ERROR) + 6 files + STALE terraform_failed → completed ─

def test_degraded_network_error_with_stale_failure_completes(db, project, tf_env):
    """Regression for the reported case: 6 HCL files produced, validation
    `degraded`/`NETWORK_ERROR`, yet `current_phase` still carries a STALE
    `terraform_failed` from a prior hard-failed attempt (the success/degraded
    path never resets it). The presence of generated HCL must win → completed.
    """
    tf_env({
        # Stale failure inherited from a previous attempt — NOT this run's outcome.
        "current_phase": "terraform_failed",
        "terraform_validation_status": "degraded",
        "terraform_failure_classification": "NETWORK_ERROR",
        "infra": {"artifacts": dict(_TF_ARTIFACTS_6)},
        "logs": [],
    })
    workflow = _run_generation(db, project)

    gen = workflow.phases_state["TERRAFORM_GENERATION"]
    assert gen["status"] == "completed"                       # HCL presence wins
    assert gen["file_count"] == 6
    assert gen["validation_status"] == "degraded"             # preserved
    assert gen["failure_classification"] == "NETWORK_ERROR"   # preserved
    assert _terraform_rows(db) == 6                           # all 6 visible in DB
