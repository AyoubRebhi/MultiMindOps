"""Final stabilization hardening — consistency + visibility contracts.

These cover the minimal hardening pass layered on top of the workflow engine
WITHOUT modifying it (engine / replay / docker pipeline untouched):

1. Explicit Terraform outcome visibility — ``derive_terraform_status`` ALWAYS
   reports generation / validation / plan statuses (``not_run`` when a phase
   never executed) and aggregates the failure classification, even when
   degraded or failed.
2. Strengthened completeness contract — the audit exposes ``missing_keys`` +
   ``missing_by_type`` so the /debug endpoint clearly shows what is missing,
   and terraform-missing can never read complete.
3. Failure-classification visibility — a degraded/failed terraform
   classification surfaces in the /debug ``terraform_status`` block AND the
   ``failure_classifications`` list, even with no dedicated validation phase.

Hermetic: real in-memory SQLite, no LLM, no terraform binary.
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
from backend.app.services.core.workflow_trace_service import WorkflowTraceService


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
    proj = Project(id="proj-1", owner_id="user-1", name="hard", current_status="active")
    db.add(proj)
    db.commit()
    return proj


# ── Task 1: explicit Terraform outcome visibility ────────────────────────────

def test_terraform_status_always_present_when_nothing_ran():
    """An empty/absent terraform leg must report not_run — never a missing key."""
    out = WorkflowTraceService.derive_terraform_status({})
    assert out == {
        "terraform_generation_status": "not_run",
        "terraform_validation_status": "not_run",
        "terraform_plan_status": "not_run",
        "terraform_failure_classification": None,
    }
    # None input behaves the same (defensive).
    assert WorkflowTraceService.derive_terraform_status(None) == out


def test_terraform_status_degraded_generation_without_validation_phase():
    """A degraded generation (registry outage) must surface even though the
    dedicated validation phase never ran."""
    phases = {
        "TERRAFORM_GENERATION": {
            "status": "completed",
            "validation_status": "degraded",
            "failure_classification": "NETWORK_ERROR",
        }
    }
    out = WorkflowTraceService.derive_terraform_status(phases)
    assert out["terraform_generation_status"] == "completed"
    # validation status falls back to the generation-time inline status.
    assert out["terraform_validation_status"] == "degraded"
    assert out["terraform_plan_status"] == "not_run"
    assert out["terraform_failure_classification"] == "NETWORK_ERROR"


def test_terraform_status_uses_dedicated_phases_when_present():
    phases = {
        "TERRAFORM_GENERATION": {"status": "completed", "validation_status": "degraded"},
        "TERRAFORM_VALIDATION": {"status": "completed", "failure_classification": None},
        "TERRAFORM_PLAN": {"status": "completed"},
    }
    out = WorkflowTraceService.derive_terraform_status(phases)
    assert out["terraform_generation_status"] == "completed"
    # The dedicated validation phase wins over the generation inline status.
    assert out["terraform_validation_status"] == "completed"
    assert out["terraform_plan_status"] == "completed"
    assert out["terraform_failure_classification"] is None


def test_terraform_status_failure_classification_precedence():
    """validation/plan classification wins over the generation-time one."""
    phases = {
        "TERRAFORM_GENERATION": {"status": "completed", "failure_classification": "NETWORK_ERROR"},
        "TERRAFORM_VALIDATION": {"status": "failed", "failure_classification": "VALIDATION_FAILED"},
    }
    out = WorkflowTraceService.derive_terraform_status(phases)
    assert out["terraform_validation_status"] == "failed"
    assert out["terraform_failure_classification"] == "VALIDATION_FAILED"


def test_terraform_status_failed_generation_blocks_downstream():
    phases = {
        "TERRAFORM_GENERATION": {
            "status": "failed",
            "validation_status": "failed",
            "failure_classification": "VALIDATION_FAILED",
        }
    }
    out = WorkflowTraceService.derive_terraform_status(phases)
    assert out["terraform_generation_status"] == "failed"
    assert out["terraform_validation_status"] == "failed"
    assert out["terraform_plan_status"] == "not_run"
    assert out["terraform_failure_classification"] == "VALIDATION_FAILED"


# ── Task 3: completeness contract clearly shows missing keys ──────────────────

_TF_STATE = {
    "infra": {
        "artifacts": {
            "terraform_main": 'resource "aws_ecs_cluster" "c" {}\n',
            "terraform_providers": 'provider "aws" {}\n',
            "dockerfile": "FROM python:3.11\n",
        }
    }
}


def test_completeness_exposes_missing_keys_and_grouping(db, project):
    """Nothing persisted → missing_keys lists every input, grouped by type."""
    audit = WorkflowTraceService.audit_artifact_completeness(
        db, project_id="proj-1", task_state=_TF_STATE,
    )
    assert audit["complete"] is False
    assert audit["terraform_complete"] is False
    # Flat list for a quick scan.
    assert set(audit["missing_keys"]) == {"terraform_main", "terraform_providers", "dockerfile"}
    # Grouped so a missing terraform key stands out from a missing docker key.
    assert set(audit["missing_by_type"]["terraform"]) == {"terraform_main", "terraform_providers"}
    assert audit["missing_by_type"]["docker"] == ["dockerfile"]


def test_completeness_missing_keys_empty_when_all_persisted(db, project):
    from backend.app.services.core.artifact_persistence_service import (
        ArtifactPersistenceService as APS,
    )
    APS.persist_state_artifacts(
        db, project_id="proj-1", workflow_id=None, state=_TF_STATE,
        generated_by_agent="test",
    )
    audit = WorkflowTraceService.audit_artifact_completeness(
        db, project_id="proj-1", task_state=_TF_STATE,
    )
    assert audit["complete"] is True
    assert audit["missing_keys"] == []
    assert audit["missing_by_type"] == {}


# ── Tasks 1 + 4: /debug surfaces terraform_status + classification ────────────

def _seed_degraded_workflow(db) -> Workflow:
    base = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    wf = Workflow(
        id="wf-1", project_id="proj-1", status="running",
        current_phase="TERRAFORM_GENERATION",
        phases_state={
            "PLAN_SELECTED": {
                "status": "completed",
                "updated_at": base.isoformat(),
                "plan_id": "balanced",
            },
            "TERRAFORM_GENERATION": {
                "status": "completed",
                "updated_at": (base + timedelta(minutes=1)).isoformat(),
                "artifact_id": "tf-abc",
                "validation_status": "degraded",
                "failure_classification": "NETWORK_ERROR",
            },
        },
    )
    db.add(wf)
    db.commit()
    return wf


def test_debug_payload_includes_terraform_status_block(db, project):
    wf = _seed_degraded_workflow(db)
    payload = WorkflowTraceService.build_debug_payload(db, workflow=wf, task_state={})

    assert "terraform_status" in payload
    ts = payload["terraform_status"]
    assert ts["terraform_generation_status"] == "completed"
    assert ts["terraform_validation_status"] == "degraded"  # generation inline fallback
    assert ts["terraform_plan_status"] == "not_run"          # never ran, still present
    assert ts["terraform_failure_classification"] == "NETWORK_ERROR"


def test_debug_payload_surfaces_degraded_classification_in_failures(db, project):
    wf = _seed_degraded_workflow(db)
    payload = WorkflowTraceService.build_debug_payload(db, workflow=wf, task_state={})
    # The NETWORK_ERROR classification appears in the deduped failure list.
    assert any(
        f["classification"] == "NETWORK_ERROR"
        for f in payload["failure_classifications"]
    )
