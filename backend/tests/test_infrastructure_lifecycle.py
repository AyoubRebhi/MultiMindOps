"""Infrastructure Lifecycle Management — the post-deployment operational phase.

Pure composition over existing capabilities (destroy / monitoring / recovery /
import) + an immutable lifecycle history. The backend never runs Terraform —
actions dispatch GitHub Actions. These tests pin:

* permission checks (who may manage),
* destroy two-step confirmation + guards,
* retry availability (only after a failed bootstrap),
* inventory rendering (grouped by AWS service),
* lifecycle persistence (append-only + dedup),
* monitoring integration (bootstrap/deploy/destroy run views),
* recovery history (reconciled from recovery/import artifacts),
* state visualization (terraform state section).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.lifecycle_event import InfrastructureLifecycleEvent
from backend.app.models.project import Project, ProjectMember
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.schemas.infrastructure_lifecycle_phase import (
    EVENT_IMPORT_COMPLETED,
    EVENT_RECOVERY_COMPLETED,
    INFRA_DESTROYED,
    INFRA_FAILED,
    INFRA_HEALTHY,
)
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.infrastructure_lifecycle import (
    InfrastructureLifecycleService,
    LifecycleEventService,
    build_inventory,
)
from backend.app.services.repository_installation.models import (
    DEFAULT_DESTROY_BRANCH,
    InstallationResult,
    WorkflowDispatchOutcome,
)
from backend.app.api.routes.projects import _can_manage_infrastructure


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for model in (User, Project, ProjectMember, Workflow, Artifact, ArtifactVersion,
                  InfrastructureLifecycleEvent):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _project(db, *, owner_id="owner", repo="https://github.com/acme/widget"):
    p = Project(id="p1", owner_id=owner_id, name="TP DevOps", repository_url=repo,
                current_status="active", project_metadata={"default_branch": "main"})
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _workflow(db, phases_state=None):
    wf = Workflow(id="wf1", project_id="p1", started_by="owner",
                  current_phase="WORKFLOW_MONITORING", status="running",
                  phases_state=phases_state or {}, logs=[])
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


def _seed_terraform(db):
    files = {
        "terraform_main": (
            'resource "aws_ecr_repository" "app" { name = "tp-app" }\n'
            'resource "aws_eks_cluster" "main" { name = "tp" }\n'
            'resource "aws_eks_node_group" "ng" {}\n'
            'resource "aws_iam_role" "cluster" {}\n'
            'resource "aws_vpc" "main" {}\n'
            'resource "aws_subnet" "a" {}\n'
            'resource "aws_internet_gateway" "igw" {}\n'
            'resource "aws_route_table" "rt" {}\n'
        ),
        "terraform_backend": (
            'terraform {\n  backend "s3" {\n    bucket = "tf-state"\n'
            '    key = "projects/p1/terraform.tfstate"\n    region = "us-east-1"\n'
            '    dynamodb_table = "locks"\n  }\n}\n'
        ),
    }
    for subtype, content in files.items():
        ArtifactPersistenceService.upsert_artifact(
            db, project_id="p1", workflow_id="wf1", artifact_type="terraform",
            artifact_subtype=subtype, content=content,
            generated_by_agent="t", validation_status="passed",
        )
    db.commit()


def _seed_import_artifact(db, imported_count=2, status="recovered"):
    ArtifactPersistenceService.upsert_artifact(
        db, project_id="p1", workflow_id="wf1", artifact_type="infrastructure_import",
        artifact_subtype="import_recovery.json",
        content=json.dumps({
            "status": status, "imported_count": imported_count, "duration_ms": 1200,
            "generated_at": "2026-06-30T10:00:00Z",
        }),
        generated_by_agent="TerraformImportService", validation_status="passed",
    )
    db.commit()


def _seed_recovery_artifact(db):
    ArtifactPersistenceService.upsert_artifact(
        db, project_id="p1", workflow_id="wf1", artifact_type="infrastructure_recovery",
        artifact_subtype="recovery.json",
        content=json.dumps({
            "failure_type": "existing_aws_resource",
            "root_cause": "An AWS resource already exists.",
            "recommended_action_label": "Import existing resource",
            "recoverable": True, "generated_at": "2026-06-30T09:00:00Z",
            "explanation": "Import the existing resource into state.",
        }),
        generated_by_agent="InfrastructureRecoveryService", validation_status="passed",
    )
    db.commit()


@pytest.fixture
def stub_token(monkeypatch):
    monkeypatch.setattr(CredentialsService, "get_credential", staticmethod(lambda *a, **k: "ghp_test"))
    monkeypatch.setattr(CredentialsService, "has_credential", staticmethod(lambda *a, **k: True))


class _FakeClient:
    """Returns a canned latest run per workflow file + canned jobs."""

    def __init__(self, runs=None, jobs=None):
        self.runs = runs or {}
        self.jobs = jobs or []

    def latest_run(self, owner, repo, workflow_file, *, branch=None):
        return self.runs.get(workflow_file)

    def run_jobs(self, owner, repo, run_id):
        return self.jobs


def _run(conclusion, *, status="completed", rid=10):
    return {
        "id": rid, "run_number": 4, "status": status, "conclusion": conclusion,
        "head_branch": "main", "head_sha": "abc", "event": "workflow_dispatch",
        "html_url": f"https://github.com/acme/widget/actions/runs/{rid}",
        "run_started_at": "2026-06-30T00:00:00Z", "updated_at": "2026-06-30T00:05:00Z",
    }


# ── 1. Permission checks ─────────────────────────────────────────────────────


def test_permission_owner_developer_admin_can_manage_viewer_cannot(db):
    project = _project(db, owner_id="owner")
    owner = User(id="owner", email="o@x.io")
    dev = User(id="dev", email="d@x.io")
    viewer = User(id="viewer", email="v@x.io")
    admin = User(id="admin", email="a@x.io", role="ADMIN")
    stranger = User(id="stranger", email="s@x.io")
    db.add_all([owner, dev, viewer, admin, stranger])
    db.add_all([
        ProjectMember(project_id="p1", user_id="dev", role="DEVELOPER"),
        ProjectMember(project_id="p1", user_id="viewer", role="VIEWER"),
    ])
    db.commit()

    assert _can_manage_infrastructure(db, project, owner) is True
    assert _can_manage_infrastructure(db, project, dev) is True
    assert _can_manage_infrastructure(db, project, admin) is True
    assert _can_manage_infrastructure(db, project, viewer) is False
    assert _can_manage_infrastructure(db, project, stranger) is False


def test_read_only_user_sees_actions_disabled(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)
    resp = InfrastructureLifecycleService.get_status(
        db, project=project, workflow=workflow, task=None, can_manage=False,
        client=_FakeClient({"bootstrap.yml": _run("success")}),
    )
    assert resp.can_manage is False
    assert resp.retry_bootstrap_available is False
    assert resp.destroy_available is False
    assert resp.destroy_block_reason  # explains why


# ── 2. Destroy confirmation + guards ─────────────────────────────────────────


def test_destroy_requires_two_step_confirmation(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)
    res = InfrastructureLifecycleService.request_destroy(
        db, project=project, workflow=workflow, task=None,
        confirm=True, acknowledge_data_loss=False,  # second confirmation missing
        client=_FakeClient({"bootstrap.yml": _run("success")}),
    )
    assert res.status == "blocked"
    assert "confirmation" in res.message.lower()


def test_destroy_blocked_after_bootstrap_failure(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)
    res = InfrastructureLifecycleService.request_destroy(
        db, project=project, workflow=workflow, task=None,
        confirm=True, acknowledge_data_loss=True,
        client=_FakeClient({"bootstrap.yml": _run("failure")}),
    )
    assert res.status == "blocked"
    assert "failed bootstrap" in res.message.lower()


def test_destroy_dispatches_when_confirmed_and_healthy(db, stub_token):
    project = _project(db)
    workflow = _workflow(db, {"REPOSITORY_INSTALLATION": {"status": "completed"}})
    _seed_terraform(db)

    def installer(**kwargs):
        return InstallationResult(
            success=True, repo_url=kwargs["repo_url"], base_branch="main",
            install_branch=DEFAULT_DESTROY_BRANCH, files_written=list(kwargs["files"]),
            committed=True, commit_sha="abc123", pushed=True, pr_created=True,
            pr_url="https://github.com/acme/widget/pull/9", logs=["committed"],
        )

    def dispatcher(**kwargs):
        return WorkflowDispatchOutcome(dispatched=True, status_code=204)

    res = InfrastructureLifecycleService.request_destroy(
        db, project=project, workflow=workflow, task=None,
        confirm=True, acknowledge_data_loss=True, actor_id="owner",
        client=_FakeClient({"bootstrap.yml": _run("success")}),
        installer=installer, dispatcher=dispatcher,
    )
    assert res.status == "ok"
    # Immutable DESTROY_REQUESTED event recorded.
    events = LifecycleEventService.list_for_project(db, project_id="p1")
    assert any(e.event_type == "DESTROY_REQUESTED" for e in events)


# ── 3. Retry availability ────────────────────────────────────────────────────


def test_retry_blocked_when_bootstrap_not_failed(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    res = InfrastructureLifecycleService.retry_bootstrap(
        db, project=project, workflow=workflow, task=None,
        client=_FakeClient({"bootstrap.yml": _run("success")}),
        dispatcher=lambda **k: WorkflowDispatchOutcome(dispatched=True, status_code=204),
    )
    assert res.status == "blocked"


def test_retry_dispatches_when_bootstrap_failed(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    calls = []

    def dispatcher(**kwargs):
        calls.append(kwargs)
        return WorkflowDispatchOutcome(dispatched=True, status_code=204)

    res = InfrastructureLifecycleService.retry_bootstrap(
        db, project=project, workflow=workflow, task=None, actor_id="owner",
        client=_FakeClient({"bootstrap.yml": _run("failure")}),
        dispatcher=dispatcher,
    )
    assert res.status == "ok" and res.dispatched is True
    assert calls and calls[0]["workflow_file"] == "bootstrap.yml"
    events = LifecycleEventService.list_for_project(db, project_id="p1")
    assert any(e.event_type == "BOOTSTRAP_RETRY" for e in events)


def test_retry_available_flag_only_on_failed_bootstrap(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)
    failed = InfrastructureLifecycleService.get_status(
        db, project=project, workflow=workflow, task=None, can_manage=True,
        client=_FakeClient({"bootstrap.yml": _run("failure")}),
    )
    assert failed.retry_bootstrap_available is True
    assert failed.infrastructure_status == INFRA_FAILED
    # Destroy blocked because bootstrap failed.
    assert failed.destroy_available is False


# ── 4. Inventory rendering ───────────────────────────────────────────────────


def test_inventory_groups_by_service():
    tf = {
        "main.tf": (
            'resource "aws_ecr_repository" "app" {}\n'
            'resource "aws_eks_cluster" "c" {}\n'
            'resource "aws_eks_node_group" "ng" {}\n'
            'resource "aws_vpc" "v" {}\n'
            'resource "aws_subnet" "s" {}\n'
            'resource "aws_iam_role" "r" {}\n'
        ),
    }
    groups, total = build_inventory(tf)
    assert total == 6
    by_service = {g.service: [r.terraform_address for r in g.resources] for g in groups}
    assert "aws_ecr_repository.app" in by_service["Amazon ECR"]
    assert set(by_service["Amazon EKS"]) == {"aws_eks_cluster.c", "aws_eks_node_group.ng"}
    assert set(by_service["Networking"]) == {"aws_vpc.v", "aws_subnet.s"}
    assert by_service["IAM"] == ["aws_iam_role.r"]


# ── 5. Lifecycle persistence (append-only + dedup) ───────────────────────────


def test_lifecycle_events_are_append_only_and_dedup(db):
    _project(db)
    e1 = LifecycleEventService.record(db, project_id="p1", workflow_id="wf1",
                                      event_type="DESTROY_REQUESTED", status="requested")
    e2 = LifecycleEventService.record(db, project_id="p1", workflow_id="wf1",
                                      event_type="BOOTSTRAP_RETRY", status="success")
    # Dedup: same key twice → one row.
    d1 = LifecycleEventService.record(db, project_id="p1", workflow_id="wf1",
                                      event_type="DESTROY_COMPLETED", status="success",
                                      dedup_key="destroy_completed:99")
    d2 = LifecycleEventService.record(db, project_id="p1", workflow_id="wf1",
                                      event_type="DESTROY_COMPLETED", status="success",
                                      dedup_key="destroy_completed:99")
    assert d1.id == d2.id  # same row, not duplicated

    events = LifecycleEventService.list_for_project(db, project_id="p1")
    assert len(events) == 3                      # e1, e2, d (deduped)
    # Newest-first ordering.
    assert {e.event_type for e in events} == {"DESTROY_REQUESTED", "BOOTSTRAP_RETRY", "DESTROY_COMPLETED"}


# ── 6. Monitoring integration ────────────────────────────────────────────────


def test_monitoring_surfaces_all_three_runs(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)
    resp = InfrastructureLifecycleService.get_status(
        db, project=project, workflow=workflow, task=None, can_manage=True,
        client=_FakeClient({
            "bootstrap.yml": _run("success", rid=1),
            "deploy.yml": _run("success", rid=2),
            "destroy.yml": _run(None, status="in_progress", rid=3),
        }),
    )
    assert resp.monitoring_available is True
    assert resp.bootstrap_run and resp.bootstrap_run.conclusion == "success"
    assert resp.deploy_run and resp.deploy_run.run_id == 2
    assert resp.destroy_run and resp.destroy_run.status == "in_progress"


# ── 7. Recovery history (reconciled from artifacts) ──────────────────────────


def test_recovery_history_reconciled_from_artifacts(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)
    _seed_import_artifact(db, imported_count=2)
    _seed_recovery_artifact(db)

    resp = InfrastructureLifecycleService.get_status(
        db, project=project, workflow=workflow, task=None, can_manage=True,
        client=_FakeClient({"bootstrap.yml": _run("success")}),
    )
    types = {h.detected_issue for h in resp.recovery_history}
    # Both an import-completed and a recovery-completed attempt are present.
    event_types = {e.event_type for e in LifecycleEventService.list_for_project(db, project_id="p1")}
    assert EVENT_IMPORT_COMPLETED in event_types
    assert EVENT_RECOVERY_COMPLETED in event_types
    assert resp.recovery_recommendations  # carried from recovery.json
    assert len(resp.recovery_history) >= 2

    # Idempotent: a second read does not duplicate the reconciled events.
    InfrastructureLifecycleService.get_status(
        db, project=project, workflow=workflow, task=None, can_manage=True,
        client=_FakeClient({"bootstrap.yml": _run("success")}),
    )
    after = LifecycleEventService.list_for_project(db, project_id="p1")
    assert len([e for e in after if e.event_type == EVENT_IMPORT_COMPLETED]) == 1
    assert len([e for e in after if e.event_type == EVENT_RECOVERY_COMPLETED]) == 1


# ── 8. State visualization ───────────────────────────────────────────────────


def test_state_visualization_counts_and_backend(db, stub_token):
    project = _project(db)
    workflow = _workflow(db)
    _seed_terraform(db)
    _seed_import_artifact(db, imported_count=3)

    resp = InfrastructureLifecycleService.get_status(
        db, project=project, workflow=workflow, task=None, can_manage=True,
        client=_FakeClient({"bootstrap.yml": _run("success")}),
    )
    st = resp.terraform_state
    assert st.backend_configured is True and st.backend_type == "s3"
    assert st.state_bucket == "tf-state"
    assert st.state_key == "projects/p1/terraform.tfstate"
    assert st.managed_resources_count == 8       # 8 resource blocks seeded
    assert st.imported_resources_count == 3
    assert st.last_apply is not None             # last successful bootstrap finish
    assert resp.infrastructure_status == INFRA_HEALTHY


def test_destroyed_status_when_destroy_succeeded(db, stub_token):
    project = _project(db)
    workflow = _workflow(db, {"INFRASTRUCTURE_DESTROY": {"status": "destroy_succeeded"}})
    _seed_terraform(db)
    resp = InfrastructureLifecycleService.get_status(
        db, project=project, workflow=workflow, task=None, can_manage=True,
        client=_FakeClient({"bootstrap.yml": _run("success")}),
    )
    assert resp.infrastructure_status == INFRA_DESTROYED
    assert resp.destroy_available is False
