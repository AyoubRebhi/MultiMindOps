"""Terraform artifact persistence fix.

Regression cover for CRITICAL #1: TerraformAgent emits canonical keys
(terraform_main, terraform_providers, ...) which classify_artifact dropped, so
NO terraform artifact was DB-backed. Verifies:

1. Canonical terraform_* keys now classify + persist as artifact_type='terraform'
   with the original key preserved as subtype (granularity).
2. get_terraform_files() translates the canonical-key subtype back to a real
   .tf filename so rehydration produces a valid terraform working dir.
3. audit_artifact_completeness now includes terraform_* in expected inputs and
   CANNOT report complete=True while terraform inputs exist but are not persisted.

Hermetic: real in-memory SQLite, no LLM, no terraform binary.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.project import Project
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService as APS,
    classify_artifact,
)
from backend.app.services.core.workflow_trace_service import WorkflowTraceService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for model in (Project, Artifact, ArtifactVersion):
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
    p = Project(id="proj-1", owner_id="u1", name="tf", current_status="active")
    db.add(p)
    db.commit()
    return p


# The exact keys the real TerraformAgent (ecs deterministic path) emits.
_TF_STATE = {
    "infra": {
        "artifacts": {
            "terraform_providers": 'provider "aws" {}\n',
            "terraform_main": 'resource "aws_ecs_cluster" "c" {}\n',
            "terraform_variables": 'variable "region" {}\n',
            "terraform_tfvars": 'region = "us-east-1"\n',
            "terraform_outputs": 'output "cluster_name" {}\n',
            "terraform_backend": 'terraform { backend "s3" {} }\n',
        }
    }
}


def test_canonical_terraform_keys_classify_as_terraform():
    for key in _TF_STATE["infra"]["artifacts"]:
        assert classify_artifact(key) == "terraform", key


def test_terraform_artifacts_persist_with_canonical_subtype(db, project):
    persisted = APS.persist_state_artifacts(
        db, project_id="proj-1", workflow_id=None, state=_TF_STATE,
        generated_by_agent="TerraformAgent",
    )
    tf = {a.artifact_subtype: a for a in persisted if a.artifact_type == "terraform"}
    # All 6 persisted, artifact_type=terraform, subtype = ORIGINAL canonical key.
    assert set(tf) == {
        "terraform_providers", "terraform_main", "terraform_variables",
        "terraform_tfvars", "terraform_outputs", "terraform_backend",
    }
    assert all(a.artifact_type == "terraform" for a in tf.values())
    rows = db.query(Artifact).filter(Artifact.artifact_type == "terraform").count()
    assert rows == 6


def test_get_terraform_files_translates_to_real_filenames(db, project):
    APS.persist_state_artifacts(
        db, project_id="proj-1", workflow_id=None, state=_TF_STATE,
        generated_by_agent="TerraformAgent",
    )
    files = APS.get_terraform_files(db, project_id="proj-1")
    # DB keeps canonical keys; the adapter hands terraform REAL .tf filenames.
    assert set(files) == {
        "providers.tf", "main.tf", "variables.tf",
        "terraform.tfvars", "outputs.tf", "backend.tf",
    }
    assert files["main.tf"] == 'resource "aws_ecs_cluster" "c" {}\n'
    # Every rehydrated file is a terraform-loadable name.
    assert all(f.endswith((".tf", ".tfvars")) for f in files)


def test_completeness_false_when_terraform_in_state_but_not_db(db, project):
    # terraform inputs exist in state, nothing persisted → MUST be incomplete.
    audit = WorkflowTraceService.audit_artifact_completeness(
        db, project_id="proj-1", task_state=_TF_STATE,
    )
    assert audit["expected_terraform_count"] == 6
    assert audit["persisted_terraform_count"] == 0
    assert audit["terraform_complete"] is False
    assert audit["complete"] is False
    assert len(audit["missing"]) == 6


def test_completeness_true_after_terraform_persisted(db, project):
    APS.persist_state_artifacts(
        db, project_id="proj-1", workflow_id=None, state=_TF_STATE,
        generated_by_agent="TerraformAgent",
    )
    audit = WorkflowTraceService.audit_artifact_completeness(
        db, project_id="proj-1", task_state=_TF_STATE,
    )
    assert audit["persisted_terraform_count"] == 6
    assert audit["terraform_complete"] is True
    assert audit["missing"] == []
    assert audit["complete"] is True


def test_completeness_catches_partial_terraform(db, project):
    # Only 1 of 6 terraform files persisted → still incomplete (missing 5).
    APS.upsert_artifact(
        db, project_id="proj-1", workflow_id=None, artifact_type="terraform",
        artifact_subtype="terraform_main", content='resource "x" "y" {}\n',
    )
    db.commit()
    audit = WorkflowTraceService.audit_artifact_completeness(
        db, project_id="proj-1", task_state=_TF_STATE,
    )
    assert audit["persisted_terraform_count"] == 1
    assert audit["terraform_complete"] is True   # at least one terraform present
    assert audit["complete"] is False            # but 5 specific inputs missing
    assert len(audit["missing"]) == 5
