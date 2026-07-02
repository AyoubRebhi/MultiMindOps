"""Infrastructure Recovery phase — read-only failure diagnosis.

The recovery layer NEVER runs Terraform and never touches AWS. These tests pin:

* classification — each failure category maps to the right recovery recommendation,
* resource detection — "already exists" errors surface the resource identity,
* diagnosis — a failed bootstrap run produces + persists a RecoveryReport,
* safety — no failure → recovery_available=False, nothing persisted; a missing
  token degrades gracefully; the service never raises.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.schemas.infrastructure_recovery_phase import (
    FAILURE_AWS_API_ERROR,
    FAILURE_EXISTING_RESOURCE,
    FAILURE_INVALID_CREDENTIALS,
    FAILURE_MISSING_PERMISSIONS,
    FAILURE_MISSING_STATE,
    FAILURE_PROVIDER_ERROR,
    FAILURE_TERRAFORM_SYNTAX,
    FAILURE_UNKNOWN,
    NO_FAILURE_DETECTED,
    RECOVERY_AVAILABLE,
)
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.infrastructure_recovery.recovery_classifier import (
    ACTION_FIX_TERRAFORM,
    ACTION_IMPORT,
    ACTION_MANUAL,
    ACTION_REBUILD_STATE,
    ACTION_RETRY,
    ACTION_REVIEW_IAM,
    ACTION_UPDATE_CREDENTIALS,
    classify_failure,
)
from backend.app.services.infrastructure_recovery.recovery_service import (
    InfrastructureRecoveryService,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


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
    p = Project(
        id="p1", owner_id="u1", name="TP DevOps", repository_url=repo,
        current_status="active", project_metadata={"default_branch": "main"},
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _workflow(db, phases_state=None):
    wf = Workflow(
        id="wf1", project_id="p1", started_by="u1",
        current_phase="REPOSITORY_INSTALLATION", status="running",
        phases_state=phases_state or {}, logs=[],
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def _seed_terraform(db, *, with_backend=True):
    ArtifactPersistenceService.upsert_artifact(
        db, project_id="p1", workflow_id="wf1", artifact_type="terraform",
        artifact_subtype="terraform_main",
        content='resource "aws_ecr_repository" "app" { name = "app" }\n',
        generated_by_agent="t", validation_status="passed",
    )
    ArtifactPersistenceService.upsert_artifact(
        db, project_id="p1", workflow_id="wf1", artifact_type="terraform",
        artifact_subtype="terraform_outputs",
        content='output "url" { value = "" }\n',
        generated_by_agent="t", validation_status="passed",
    )
    if with_backend:
        ArtifactPersistenceService.upsert_artifact(
            db, project_id="p1", workflow_id="wf1", artifact_type="terraform",
            artifact_subtype="terraform_backend",
            content=(
                'terraform {\n  backend "s3" {\n    bucket = "st"\n'
                '    key = "projects/p1/terraform.tfstate"\n'
                '    region = "us-east-1"\n    dynamodb_table = "lk"\n  }\n}\n'
            ),
            generated_by_agent="t", validation_status="passed",
        )
    db.commit()


@pytest.fixture
def stub_token(monkeypatch):
    monkeypatch.setattr(
        CredentialsService, "get_credential", staticmethod(lambda *a, **k: "ghp_test"),
    )
    monkeypatch.setattr(
        CredentialsService, "has_credential", staticmethod(lambda *a, **k: True),
    )


class _FakeClient:
    """Stands in for GitHubActionsClient — returns a canned bootstrap run + jobs."""

    def __init__(self, run, jobs=None):
        self._run = run
        self._jobs = jobs or []

    def latest_run(self, owner, repo, workflow_file, *, branch=None):
        return self._run

    def run_jobs(self, owner, repo, run_id):
        return self._jobs


def _failed_run():
    return {
        "id": 42, "run_number": 5, "status": "completed", "conclusion": "failure",
        "head_branch": "main", "head_sha": "abc123", "event": "workflow_dispatch",
        "html_url": "https://github.com/acme/widget/actions/runs/42",
        "run_started_at": "2026-06-30T00:00:00Z", "updated_at": "2026-06-30T00:05:00Z",
    }


# ── 1. Classification ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, expected_type, expected_action",
    [
        ("Error: creating ECR Repository: RepositoryAlreadyExistsException: "
         "repository with name 'app' already exists",
         FAILURE_EXISTING_RESOURCE, ACTION_IMPORT),
        ("Error: Failed to load state: NoSuchBucket: The specified bucket does not exist",
         FAILURE_MISSING_STATE, ACTION_REBUILD_STATE),
        ("Error: error configuring Terraform AWS Provider: InvalidClientTokenId: "
         "The security token included in the request is invalid",
         FAILURE_INVALID_CREDENTIALS, ACTION_UPDATE_CREDENTIALS),
        ("Error: AccessDenied: User: arn:aws:iam::1:user/ci is not authorized to "
         "perform: ecs:CreateCluster",
         FAILURE_MISSING_PERMISSIONS, ACTION_REVIEW_IAM),
        ("Error: Unsupported argument; An argument named \"foo\" is not expected here.",
         FAILURE_TERRAFORM_SYNTAX, ACTION_FIX_TERRAFORM),
        ("Error: Failed to install provider: could not retrieve the list of "
         "available versions for provider hashicorp/aws",
         FAILURE_PROVIDER_ERROR, ACTION_RETRY),
        ("Error: ThrottlingException: Rate exceeded", FAILURE_AWS_API_ERROR, ACTION_RETRY),
        ("something totally unrecognized happened", FAILURE_UNKNOWN, ACTION_MANUAL),
        ("", FAILURE_UNKNOWN, ACTION_MANUAL),
    ],
)
def test_classify_failure_categories(text, expected_type, expected_action):
    cls = classify_failure(text)
    assert cls.failure_type == expected_type
    assert cls.recommended_action == expected_action


def test_unknown_and_empty_are_low_confidence_not_recoverable():
    assert classify_failure("").confidence == "low"
    assert classify_failure("").recoverable is False
    assert classify_failure("weird").failure_type == FAILURE_UNKNOWN


def test_existing_resource_detects_ecr_identity():
    cls = classify_failure(
        "RepositoryAlreadyExistsException: repository with name 'my-app' already exists"
    )
    assert cls.failure_type == FAILURE_EXISTING_RESOURCE
    ids = {(r.resource_type, r.identifier) for r in cls.detected_resources}
    assert ("ecr_repository", "my-app") in ids


def test_credentials_classified_before_permissions():
    # A blob mentioning BOTH must classify as invalid-credentials (more specific).
    cls = classify_failure(
        "InvalidClientTokenId: token invalid. AccessDenied: not authorized"
    )
    assert cls.failure_type == FAILURE_INVALID_CREDENTIALS


# ── 2. build_report (pure) ──────────────────────────────────────────────────


def test_build_report_existing_resource_recommends_import():
    report = InfrastructureRecoveryService.build_report(
        failure_text="repository with name 'app' already exists",
        terraform_state_available=True,
        terraform_outputs_available=True,
    )
    assert report.status == RECOVERY_AVAILABLE
    assert report.failure_type == FAILURE_EXISTING_RESOURCE
    assert report.recommended_action == ACTION_IMPORT
    assert report.recoverable is True
    assert report.terraform_state_available is True
    # The three placeholder actions are present and all DISABLED.
    assert {a.id for a in report.available_actions} == {"retry", "import", "destroy"}
    assert all(a.enabled is False for a in report.available_actions)
    # Import is flagged recommended for an existing-resource failure.
    assert next(a for a in report.available_actions if a.id == "import").recommended


# ── 3. Diagnosis (read-only) + persistence ──────────────────────────────────


def test_failed_bootstrap_produces_and_persists_report(db, stub_token):
    project = _project(db)
    workflow = _workflow(db, {"REPOSITORY_INSTALLATION": {"status": "completed"}})
    _seed_terraform(db)

    jobs = [{
        "name": "Provision and first deploy",
        "steps": [{"name": "Terraform apply", "conclusion": "failure"}],
    }]
    resp = InfrastructureRecoveryService.get_status(
        db, project=project, workflow=workflow, task=None,
        client=_FakeClient(_failed_run(), jobs=jobs),
        failure_log="RepositoryAlreadyExistsException: repository with name 'app' already exists",
    )

    assert resp.recovery_available is True
    assert resp.failed is True
    assert resp.phase_status == RECOVERY_AVAILABLE
    assert resp.report is not None
    assert resp.report.failure_type == FAILURE_EXISTING_RESOURCE
    assert resp.report.recommended_action == ACTION_IMPORT
    assert resp.report.terraform_state_available is True
    assert resp.run is not None and resp.run.conclusion == "failure"

    # Persisted as an infrastructure_recovery artifact (NOT a terraform artifact).
    record = (
        db.query(Artifact)
        .filter(Artifact.artifact_type == "infrastructure_recovery")
        .first()
    )
    assert record is not None and record.artifact_subtype == "recovery.json"
    # Terraform artifacts are untouched.
    tf = ArtifactPersistenceService.get_terraform_files(db, project_id="p1")
    assert "main.tf" in tf and "backend.tf" in tf
    # Diagnostic phase marker recorded (no lifecycle gating).
    db.refresh(workflow)
    assert workflow.phases_state["INFRASTRUCTURE_RECOVERY"]["status"] == RECOVERY_AVAILABLE


def test_classifies_from_run_when_no_backend_state(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db, with_backend=False)

    resp = InfrastructureRecoveryService.get_status(
        db, project=project, workflow=workflow, task=None,
        client=_FakeClient(_failed_run()),
        failure_log="Error: NoSuchBucket: the state bucket does not exist",
    )
    assert resp.recovery_available is True
    assert resp.report.failure_type == FAILURE_MISSING_STATE
    assert resp.report.terraform_state_available is False
    assert resp.report.recommended_action == ACTION_REBUILD_STATE


def test_no_failure_means_no_recovery_and_nothing_persisted(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)

    success_run = {**_failed_run(), "conclusion": "success"}
    resp = InfrastructureRecoveryService.get_status(
        db, project=project, workflow=workflow, task=None,
        client=_FakeClient(success_run),
    )
    assert resp.recovery_available is False
    assert resp.failed is False
    assert resp.phase_status == NO_FAILURE_DETECTED
    assert resp.report is None
    assert (
        db.query(Artifact)
        .filter(Artifact.artifact_type == "infrastructure_recovery")
        .first()
        is None
    )


def test_degrades_without_token_and_never_raises(db, monkeypatch):
    monkeypatch.setattr(
        CredentialsService, "get_credential", staticmethod(lambda *a, **k: None),
    )
    monkeypatch.setattr(
        CredentialsService, "has_credential", staticmethod(lambda *a, **k: False),
    )
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)

    # No client, no token, no failure_log → cannot observe → no diagnosis, no raise.
    resp = InfrastructureRecoveryService.get_status(
        db, project=project, workflow=workflow, task=None,
    )
    assert resp.recovery_available is False
    assert resp.has_github_token is False
    assert resp.has_terraform is True


def test_explicit_failure_log_diagnoses_without_a_run(db, stub_token):
    """An engineer-supplied apply error is enough to diagnose, even with no run."""
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)

    resp = InfrastructureRecoveryService.get_status(
        db, project=project, workflow=workflow, task=None,
        client=_FakeClient(None),  # no bootstrap run observed
        failure_log="AccessDenied: User is not authorized to perform iam:CreateRole",
    )
    assert resp.recovery_available is True
    assert resp.report.failure_type == FAILURE_MISSING_PERMISSIONS
    assert resp.report.recommended_action == ACTION_REVIEW_IAM
