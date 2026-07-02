"""Automatic Terraform import recovery.

The backend turns a failed ``terraform apply`` (resources already exist) into
``detect → import → refresh → plan → apply`` with no manual ``terraform import``.
The terraform runner is injected (a stateful fake here), so these tests exercise
the full recovery logic without a terraform binary or AWS.

Covered: RepositoryAlreadyExists, IAM role exists, already-imported, invalid
import, region mismatch, wrong account, idempotent rerun, partial success.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.services.terraform_import import (
    ImportableResource,
    ImportSafetyContext,
    TerraformImportService,
    parse_failure,
    validate_resource,
)
from backend.app.services.terraform_import.models import (
    CommandResult,
    STATUS_ABORTED,
    STATUS_FAILED,
    STATUS_PARTIAL,
    STATUS_RECOVERED,
)

WD = Path("/tmp/tfimport")  # never touched — the fake runner ignores cwd


# ── Failure fixtures (real terraform diagnostic shapes) ──────────────────────

ECR_FAILURE = """
Error: creating ECR Repository (tp-app): operation error ECR: CreateRepository,
https response error StatusCode: 400, RepositoryAlreadyExistsException: The
repository with name 'tp-app' already exists in the registry with id '123'

  with aws_ecr_repository.app,
  on main.tf line 12, in resource "aws_ecr_repository" "app":
  12: resource "aws_ecr_repository" "app" {
"""

IAM_FAILURE = """
Error: creating IAM Role (tp-eks-cluster): operation error IAM: CreateRole,
https response error StatusCode: 409, EntityAlreadyExists: Role with name
tp-eks-cluster already exists.

  with aws_iam_role.eks_cluster,
  on main.tf line 30, in resource "aws_iam_role" "eks_cluster":
  30: resource "aws_iam_role" "eks_cluster" {
"""

ECR_AND_IAM_FAILURE = ECR_FAILURE + "\n" + IAM_FAILURE


# ── Stateful fake terraform runner ───────────────────────────────────────────


class FakeRunner:
    """Simulates terraform: tracks state, fails configured imports, records calls."""

    def __init__(self):
        self.state: set[str] = set()
        self.calls: list[list[str]] = []
        self.import_fail: dict[str, str] = {}   # address -> stderr
        self.init_rc = 0
        self.refresh_rc = 0
        self.plan_rc = 0
        self.apply_rc = 0

    def __call__(self, args, cwd):
        self.calls.append(list(args))
        cmd = args[0]
        if cmd == "init":
            return CommandResult(self.init_rc, "Terraform has been successfully initialized!")
        if cmd == "state" and len(args) > 1 and args[1] == "list":
            return CommandResult(0, "\n".join(sorted(self.state)))
        if cmd == "import":
            address, ident = args[-2], args[-1]
            if address in self.state:
                return CommandResult(1, "", "Error: Resource already managed by Terraform")
            if address in self.import_fail:
                return CommandResult(1, "", self.import_fail[address])
            self.state.add(address)
            return CommandResult(0, f"Import successful! {address} -> {ident}")
        if cmd == "apply" and "-refresh-only" in args:
            return CommandResult(self.refresh_rc, "Refresh complete")
        if cmd == "plan":
            return CommandResult(self.plan_rc, "Plan: 0 to add")
        if cmd == "apply":
            return CommandResult(self.apply_rc, "Apply complete!")
        return CommandResult(0, "")

    def import_calls(self):
        return [c for c in self.calls if c and c[0] == "import"]

    def ran(self, cmd):
        return any(c and c[0] == cmd for c in self.calls)


SAFE = ImportSafetyContext(project_id="p1")  # no account/region/prefix constraints


# ── 1. Detection ─────────────────────────────────────────────────────────────


def test_detect_repository_already_exists():
    resources = parse_failure(ECR_FAILURE)
    assert len(resources) == 1
    r = resources[0]
    assert r.terraform_address == "aws_ecr_repository.app"
    assert r.resource_type == "aws_ecr_repository"
    assert r.aws_identifier == "tp-app"


def test_detect_iam_role_exists():
    resources = parse_failure(IAM_FAILURE)
    assert len(resources) == 1
    assert resources[0].terraform_address == "aws_iam_role.eks_cluster"
    assert resources[0].aws_identifier == "tp-eks-cluster"


def test_detect_ignores_unrelated_errors():
    # A syntax error has no "already exists" → nothing importable.
    txt = ('Error: Unsupported argument\n\n  with aws_ecr_repository.app,\n'
           '  on main.tf line 12\n')
    assert parse_failure(txt) == []


def test_build_import_command():
    r = parse_failure(ECR_FAILURE)[0]
    assert TerraformImportService.build_import_command(r) == (
        "terraform import aws_ecr_repository.app tp-app"
    )


# ── 2. RepositoryAlreadyExists → full recovery ───────────────────────────────


def test_repository_already_exists_recovers():
    runner = FakeRunner()
    svc = TerraformImportService(runner=runner)
    result = svc.recover_from_failure(working_dir=WD, failure_text=ECR_FAILURE, safety=SAFE)

    assert result.status == STATUS_RECOVERED
    assert result.imported_count == 1
    assert result.imported[0].resource.terraform_address == "aws_ecr_repository.app"
    assert result.imported[0].command == "terraform import aws_ecr_repository.app tp-app"
    # Full retry sequence ran.
    assert runner.ran("init") and runner.ran("plan") and runner.ran("apply")
    assert result.apply_ok is True


# ── 3. Already imported → skipped (no duplicate) ─────────────────────────────


def test_already_imported_is_skipped():
    runner = FakeRunner()
    runner.state.add("aws_ecr_repository.app")  # already in state
    svc = TerraformImportService(runner=runner)
    result = svc.recover_from_failure(working_dir=WD, failure_text=ECR_FAILURE, safety=SAFE)

    assert result.status == STATUS_RECOVERED
    assert result.imported_count == 0
    assert len(result.skipped) == 1
    assert not runner.import_calls()  # never attempted an import


# ── 4. Invalid import → failed, no apply ─────────────────────────────────────


def test_invalid_import_fails_and_skips_apply():
    runner = FakeRunner()
    runner.import_fail["aws_ecr_repository.app"] = (
        "Error: Cannot import non-existent remote object"
    )
    svc = TerraformImportService(runner=runner)
    result = svc.recover_from_failure(working_dir=WD, failure_text=ECR_FAILURE, safety=SAFE)

    assert result.status == STATUS_FAILED
    assert len(result.failed) == 1
    assert result.imported_count == 0
    # A failed import must NOT proceed to apply.
    assert not runner.ran("apply")
    assert result.apply_ok is None


# ── 5. Region mismatch → abort ───────────────────────────────────────────────


def test_region_mismatch_aborts():
    runner = FakeRunner()
    svc = TerraformImportService(runner=runner)
    resource = ImportableResource(
        terraform_address="aws_lb.main",
        resource_type="aws_lb",
        resource_name="main",
        aws_identifier="arn:aws:elasticloadbalancing:eu-west-1:111122223333:loadbalancer/app/x/abc",
    )
    ctx = ImportSafetyContext(
        project_id="p1", expected_account_id="111122223333", expected_region="us-east-1",
    )
    result = svc.recover(working_dir=WD, resources=[resource], safety=ctx)

    assert result.status == STATUS_ABORTED
    assert not runner.import_calls()  # nothing imported
    assert result.aborted and "region" in result.aborted[0].message.lower()


# ── 6. Wrong account → abort ─────────────────────────────────────────────────


def test_wrong_account_aborts():
    runner = FakeRunner()
    svc = TerraformImportService(runner=runner)
    resource = ImportableResource(
        terraform_address="aws_lb.main",
        resource_type="aws_lb",
        resource_name="main",
        aws_identifier="arn:aws:elasticloadbalancing:us-east-1:999999999999:loadbalancer/app/x/abc",
    )
    ctx = ImportSafetyContext(
        project_id="p1", expected_account_id="111122223333", expected_region="us-east-1",
    )
    result = svc.recover(working_dir=WD, resources=[resource], safety=ctx)

    assert result.status == STATUS_ABORTED
    assert not runner.import_calls()
    assert result.aborted and "account" in result.aborted[0].message.lower()


def test_validate_resource_account_and_region_directly():
    r = ImportableResource(
        "aws_lb.main", "aws_lb", "main",
        "arn:aws:elasticloadbalancing:eu-west-1:999999999999:loadbalancer/app/x/abc",
    )
    v = validate_resource(r, ImportSafetyContext(
        project_id="p1", expected_account_id="111122223333", expected_region="us-east-1"))
    assert v is not None and v.category == "region_mismatch"


def test_ownership_violation_skips_foreign_resource():
    runner = FakeRunner()
    svc = TerraformImportService(runner=runner)
    ctx = ImportSafetyContext(project_id="p1", allowed_name_prefix="myproject")
    # ECR id "tp-app" does not match the project prefix → per-resource skip.
    result = svc.recover_from_failure(working_dir=WD, failure_text=ECR_FAILURE, safety=ctx)
    assert result.imported_count == 0
    assert result.aborted and result.aborted[0].status == "aborted_validation"
    assert not runner.import_calls()


# ── 7. Idempotent rerun → second run imports nothing ─────────────────────────


def test_idempotent_rerun_imports_nothing_the_second_time():
    runner = FakeRunner()
    svc = TerraformImportService(runner=runner)

    first = svc.recover_from_failure(working_dir=WD, failure_text=ECR_AND_IAM_FAILURE, safety=SAFE)
    assert first.status == STATUS_RECOVERED
    assert first.imported_count == 2
    after_first = len(runner.import_calls())

    second = svc.recover_from_failure(working_dir=WD, failure_text=ECR_AND_IAM_FAILURE, safety=SAFE)
    assert second.status == STATUS_RECOVERED
    assert second.imported_count == 0           # nothing re-imported
    assert len(second.skipped) == 2             # both already in state
    assert len(runner.import_calls()) == after_first  # no new import commands


# ── 8. Partial import success → partial, no apply ────────────────────────────


def test_partial_import_success():
    runner = FakeRunner()
    runner.import_fail["aws_iam_role.eks_cluster"] = "Error: AccessDenied importing role"
    svc = TerraformImportService(runner=runner)

    result = svc.recover_from_failure(working_dir=WD, failure_text=ECR_AND_IAM_FAILURE, safety=SAFE)

    assert result.status == STATUS_PARTIAL
    assert result.imported_count == 1
    assert len(result.failed) == 1
    # A partial import must NOT apply (state is left consistent, not advanced).
    assert not runner.ran("apply")


# ── Structured logging ───────────────────────────────────────────────────────


def test_logs_capture_each_step():
    runner = FakeRunner()
    svc = TerraformImportService(runner=runner)
    result = svc.recover_from_failure(working_dir=WD, failure_text=ECR_FAILURE, safety=SAFE)
    steps = {entry["step"] for entry in result.logs}
    assert {"detect", "init", "import", "plan", "apply", "summary"} <= steps
    assert result.duration_ms >= 0


# ── Workflow integration: persistence (does NOT touch orchestration) ─────────


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for model in (User, Project, Workflow, Artifact, ArtifactVersion):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_recover_for_workflow_persists_outcome(db):
    project = Project(id="p1", owner_id="u1", name="TP", current_status="active")
    workflow = Workflow(id="wf1", project_id="p1", started_by="u1",
                        current_phase="REPOSITORY_INSTALLATION", status="running",
                        phases_state={}, logs=[])
    db.add(project)
    db.add(workflow)
    db.commit()

    runner = FakeRunner()
    svc = TerraformImportService(runner=runner)
    result = svc.recover_for_workflow(
        db, project=project, workflow=workflow,
        failure_text=ECR_FAILURE, working_dir=WD,
        safety=ImportSafetyContext(project_id="p1"),
    )
    assert result.status == STATUS_RECOVERED

    # Persisted under its OWN artifact type (never overwrites terraform artifacts).
    record = (
        db.query(Artifact)
        .filter(Artifact.artifact_type == "infrastructure_import")
        .first()
    )
    assert record is not None and record.artifact_subtype == "import_recovery.json"
    db.refresh(workflow)
    marker = workflow.phases_state["TERRAFORM_IMPORT_RECOVERY"]
    assert marker["status"] == STATUS_RECOVERED
    assert marker["imported_count"] == 1
