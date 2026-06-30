"""Infrastructure Destroy phase — generate / install / dispatch / monitor / guard.

The backend NEVER runs Terraform; it commits ``destroy.yml`` and asks GitHub
Actions to run ``terraform destroy``. These tests pin each step of that flow with
the git + GitHub seams injected (no network, no real repo):

* generation     — destroy.yml carries the exact required steps,
* installation   — destroy.yml + terraform/ are committed (and ONLY those),
* dispatch       — destroy.yml is auto-triggered; not-dispatched → requested,
* monitoring     — the live run is observed like bootstrap.yml and reconciled
                   into destroy_succeeded / destroy_failed,
* deletion guard — a project is deletable only with no infra OR destroy succeeded.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.schemas.infrastructure_destroy_phase import (
    DESTROY_FAILED,
    DESTROY_REQUESTED,
    DESTROY_RUNNING,
    DESTROY_SUCCEEDED,
)
from backend.app.services.core import credentials_service as creds_mod
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.core.project_service import ProjectService
from backend.app.services.github_actions_generation.renderer import render_workflow
from backend.app.services.infrastructure_destroy.destroy_service import (
    InfrastructureDestroyService,
)
from backend.app.services.repository_installation.models import (
    DEFAULT_DESTROY_BRANCH,
    DESTROY_PATH,
    InstallationResult,
    WorkflowDispatchOutcome,
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


def _workflow(db, phases_state):
    wf = Workflow(
        id="wf1", project_id="p1", started_by="u1",
        current_phase="REPOSITORY_INSTALLATION", status="completed",
        phases_state=phases_state, logs=[],
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def _seed_terraform(db, *, region="eu-west-3"):
    ArtifactPersistenceService.upsert_artifact(
        db, project_id="p1", workflow_id="wf1", artifact_type="terraform",
        artifact_subtype="terraform_main",
        content='resource "aws_ecs_cluster" "main" {\n  name = "tp-cluster"\n}\n',
        generated_by_agent="t", validation_status="passed",
    )
    ArtifactPersistenceService.upsert_artifact(
        db, project_id="p1", workflow_id="wf1", artifact_type="terraform",
        artifact_subtype="terraform_tfvars",
        content=f'project_name = "tp"\naws_region   = "{region}"\n',
        generated_by_agent="t", validation_status="passed",
    )
    db.commit()


@pytest.fixture
def stub_token(monkeypatch):
    """Stub credential reads so the service sees a token without the creds table."""
    monkeypatch.setattr(
        CredentialsService, "get_credential", staticmethod(lambda *a, **k: "ghp_test"),
    )
    monkeypatch.setattr(
        CredentialsService, "has_credential", staticmethod(lambda *a, **k: True),
    )


def _ok_install(**kwargs):
    """A successful installer that records the files it was asked to commit."""
    _ok_install.calls.append(kwargs)
    return InstallationResult(
        success=True,
        repo_url=kwargs["repo_url"],
        base_branch=kwargs.get("base_branch") or "main",
        install_branch=kwargs.get("install_branch") or DEFAULT_DESTROY_BRANCH,
        files_written=list(kwargs["files"].keys()),
        committed=True,
        commit_sha="abc123",
        pushed=True,
        pr_created=True,
        pr_url="https://github.com/acme/widget/pull/7",
        logs=["committed destroy.yml"],
    )


def _dispatched(**kwargs):
    _dispatched.calls.append(kwargs)
    return WorkflowDispatchOutcome(dispatched=True, status_code=204)


def _not_dispatched(**kwargs):
    _not_dispatched.calls.append(kwargs)
    return WorkflowDispatchOutcome(
        dispatched=False, status_code=404, error="not on default branch yet",
    )


# ── 1. Generation ──────────────────────────────────────────────────────────


def test_destroy_workflow_has_required_steps():
    ctx = InfrastructureDestroyService._build_context(
        SimpleNamespace(name="TP DevOps"),
        {"terraform.tfvars": 'aws_region = "eu-west-3"\n', "main.tf": "resource x {}"},
    )
    _template, content = render_workflow(ctx, "destroy")

    # The exact workflow the brief specifies.
    assert "actions/checkout@v4" in content
    assert "aws-actions/configure-aws-credentials@v4" in content
    assert "hashicorp/setup-terraform@v3" in content
    assert "terraform init" in content
    assert "terraform destroy -auto-approve" in content
    # Region comes from the GENERATED terraform (source of truth), not a guess.
    assert "eu-west-3" in content
    # Manual + auto dispatchable.
    assert "workflow_dispatch" in content


# ── 2. Installation + 3. Dispatch ──────────────────────────────────────────


def test_run_installs_destroy_and_dispatches(db, stub_token, monkeypatch):
    _ok_install.calls = []
    _dispatched.calls = []
    project = _project(db)
    workflow = _workflow(db, {"REPOSITORY_INSTALLATION": {"status": "completed"}})
    _seed_terraform(db)

    state, ids = InfrastructureDestroyService.run(
        db, project=project, workflow=workflow, task=None,
        installer=_ok_install, dispatcher=_dispatched,
    )

    # Installation committed destroy.yml + terraform/ and ONLY those.
    assert len(_ok_install.calls) == 1
    files = _ok_install.calls[0]["files"]
    assert DESTROY_PATH in files
    assert "terraform/main.tf" in files
    assert "terraform/terraform.tfvars" in files
    assert all(
        p == DESTROY_PATH or p.startswith("terraform/") for p in files
    ), files
    assert _ok_install.calls[0]["install_branch"] == DEFAULT_DESTROY_BRANCH

    # Dispatch auto-triggered destroy.yml on the install branch.
    assert len(_dispatched.calls) == 1
    assert _dispatched.calls[0]["workflow_file"] == "destroy.yml"
    assert _dispatched.calls[0]["ref"] == DEFAULT_DESTROY_BRANCH

    # Persisted lifecycle: dispatched ⇒ running.
    db.refresh(workflow)
    entry = workflow.phases_state["INFRASTRUCTURE_DESTROY"]
    assert entry["status"] == DESTROY_RUNNING
    assert entry["dispatched"] is True
    assert entry["commit"] == "abc123"

    # destroy.yml is DB-backed (github_actions artifact) + a destroy record exists.
    gh = ArtifactPersistenceService.get_github_actions_files(db, project_id="p1")
    assert DESTROY_PATH in gh
    record = (
        db.query(Artifact)
        .filter(Artifact.artifact_type == "infrastructure_destroy")
        .first()
    )
    assert record is not None
    assert len(ids) >= 2


def test_run_records_requested_when_not_dispatched(db, stub_token):
    _ok_install.calls = []
    _not_dispatched.calls = []
    project = _project(db)
    workflow = _workflow(db, {"REPOSITORY_INSTALLATION": {"status": "completed"}})
    _seed_terraform(db)

    InfrastructureDestroyService.run(
        db, project=project, workflow=workflow, task=None,
        installer=_ok_install, dispatcher=_not_dispatched,
    )
    db.refresh(workflow)
    entry = workflow.phases_state["INFRASTRUCTURE_DESTROY"]
    # Committed but the run is not confirmed (404 until on the default branch).
    assert entry["status"] == DESTROY_REQUESTED
    assert entry["dispatched"] is False


def test_run_failed_install_records_destroy_failed(db, stub_token):
    project = _project(db)
    workflow = _workflow(db, {"REPOSITORY_INSTALLATION": {"status": "completed"}})
    _seed_terraform(db)

    def failing_install(**kwargs):
        return InstallationResult(
            success=False, repo_url=kwargs["repo_url"], base_branch="main",
            install_branch=DEFAULT_DESTROY_BRANCH, error="push rejected", logs=["boom"],
        )

    state, ids = InfrastructureDestroyService.run(
        db, project=project, workflow=workflow, task=None,
        installer=failing_install, dispatcher=_dispatched,
    )
    db.refresh(workflow)
    assert workflow.phases_state["INFRASTRUCTURE_DESTROY"]["status"] == DESTROY_FAILED


def test_run_requires_terraform(db, stub_token):
    project = _project(db)
    workflow = _workflow(db, {"REPOSITORY_INSTALLATION": {"status": "completed"}})
    # No terraform artifacts seeded.
    with pytest.raises(ValueError, match="no Terraform artifacts"):
        InfrastructureDestroyService.run(
            db, project=project, workflow=workflow, task=None,
            installer=_ok_install, dispatcher=_dispatched,
        )


def test_run_requires_token(db, monkeypatch):
    monkeypatch.setattr(
        CredentialsService, "get_credential", staticmethod(lambda *a, **k: None),
    )
    project = _project(db)
    workflow = _workflow(db, {"REPOSITORY_INSTALLATION": {"status": "completed"}})
    _seed_terraform(db)
    with pytest.raises(ValueError, match="GitHub token"):
        InfrastructureDestroyService.run(
            db, project=project, workflow=workflow, task=None,
            installer=_ok_install, dispatcher=_dispatched,
        )


# ── 4. Monitoring (observe destroy.yml like bootstrap.yml + reconcile) ──────


class _FakeClient:
    """Stands in for GitHubActionsClient — returns a canned latest run."""

    def __init__(self, run):
        self._run = run

    def latest_run(self, owner, repo, workflow_file, *, branch=None):
        return self._run

    def run_jobs(self, owner, repo, run_id):
        return []


def _completed_run(conclusion):
    return {
        "id": 99, "run_number": 3, "status": "completed", "conclusion": conclusion,
        "head_branch": DEFAULT_DESTROY_BRANCH, "head_sha": "abc123",
        "event": "workflow_dispatch", "html_url": "https://github.com/x/y/actions/runs/99",
        "run_started_at": "2026-06-29T00:00:00Z", "updated_at": "2026-06-29T00:05:00Z",
    }


def test_monitoring_reconciles_success(db, stub_token):
    project = _project(db)
    workflow = _workflow(
        db, {"INFRASTRUCTURE_DESTROY": {"status": DESTROY_RUNNING, "branch": DEFAULT_DESTROY_BRANCH}},
    )
    _seed_terraform(db)

    resp = InfrastructureDestroyService.get_status(
        db, project=project, workflow=workflow, task=None,
        client=_FakeClient(_completed_run("success")),
    )
    assert resp.phase_status == DESTROY_SUCCEEDED
    assert resp.succeeded is True
    assert resp.run is not None and resp.run.conclusion == "success"
    # Persisted so the deletion guard sees it.
    db.refresh(workflow)
    assert workflow.phases_state["INFRASTRUCTURE_DESTROY"]["status"] == DESTROY_SUCCEEDED


def test_monitoring_reconciles_failure(db, stub_token):
    project = _project(db)
    workflow = _workflow(
        db, {"INFRASTRUCTURE_DESTROY": {"status": DESTROY_RUNNING}},
    )
    _seed_terraform(db)

    resp = InfrastructureDestroyService.get_status(
        db, project=project, workflow=workflow, task=None,
        client=_FakeClient(_completed_run("failure")),
    )
    assert resp.phase_status == DESTROY_FAILED
    assert resp.failed is True


def test_monitoring_keeps_running_while_in_progress(db, stub_token):
    project = _project(db)
    workflow = _workflow(db, {"INFRASTRUCTURE_DESTROY": {"status": DESTROY_RUNNING}})
    _seed_terraform(db)
    active = {"id": 1, "status": "in_progress", "conclusion": None,
              "run_started_at": "2026-06-29T00:00:00Z"}
    resp = InfrastructureDestroyService.get_status(
        db, project=project, workflow=workflow, task=None,
        client=_FakeClient(active),
    )
    assert resp.phase_status == DESTROY_RUNNING
    assert resp.running is True


# ── 5. Deletion guard ───────────────────────────────────────────────────────


def test_guard_blocks_when_infrastructure_live(db):
    project = _project(db)
    _workflow(db, {"REPOSITORY_INSTALLATION": {"status": "completed"}})
    state = InfrastructureDestroyService.infrastructure_state(db, project)
    assert state["has_infrastructure"] is True
    assert state["destroy_succeeded"] is False
    assert state["deletable"] is False
    assert state["reason"]


def test_guard_allows_after_destroy_succeeded(db):
    project = _project(db)
    _workflow(db, {
        "REPOSITORY_INSTALLATION": {"status": "completed"},
        "INFRASTRUCTURE_DESTROY": {"status": DESTROY_SUCCEEDED},
    })
    state = InfrastructureDestroyService.infrastructure_state(db, project)
    assert state["has_infrastructure"] is True
    assert state["destroy_succeeded"] is True
    assert state["deletable"] is True


def test_guard_allows_when_no_infrastructure(db):
    project = _project(db)
    _workflow(db, {"DOCKER": {"status": "completed"}})  # generated but never installed
    state = InfrastructureDestroyService.infrastructure_state(db, project)
    assert state["has_infrastructure"] is False
    assert state["deletable"] is True


def test_delete_project_removes_row(db):
    project = _project(db)
    _workflow(db, {"DOCKER": {"status": "completed"}})
    ProjectService.delete_project(db, project)
    assert db.query(Project).filter(Project.id == "p1").first() is None
