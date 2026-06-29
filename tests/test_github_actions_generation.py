"""GITHUB_ACTIONS_GENERATION phase.

A DEPLOYMENT orchestration phase: it consumes the validated Docker + Terraform
artifacts and the selected architecture decision, then renders a single
``.github/workflows/deploy.yml`` whose deployment target is DERIVED from the
blueprint's ``compute.type`` (never asked).

Coverage:
  * deployment-target derivation + template selection + render + YAML validation
    for every target (ecs/eks/lambda/ec2),
  * the YAML validator rejects empty / invalid / malformed workflows,
  * the full ``run_phase`` path against a REAL in-memory SQLite session:
    artifact persisted as ``github_actions``, phase ``completed``, workflow
    ``completed``, GitHub ``${{ }}`` expressions preserved,
  * the read projection surfaces the generated file,
  * prerequisites are enforced (PLAN_SELECTED + DOCKER + TERRAFORM_GENERATION).
"""

from __future__ import annotations

import types

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.artifact import Artifact, ArtifactVersion
from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.services.core.workflow_orchestration_service import (
    PHASE_GH_ACTIONS,
    WorkflowOrchestrationService as WOS,
)


# ── Blueprint fixtures (one valid blueprint per compute type) ────────────────

def _blueprint(compute_type: str) -> dict:
    base = {
        "networking": {"multi_az": True, "load_balancer": "ALB"},
        "scaling": {"strategy": "horizontal", "auto_scaling": True},
        "aws_region": "eu-west-1",
        "strategy_tier": "balanced",
    }
    if compute_type == "ECS":
        return {**base, "architecture_style": "monolith",
                "compute": {"type": "ECS", "instance_type": "t3.medium"}}
    if compute_type == "EC2":
        return {**base, "architecture_style": "monolith",
                "compute": {"type": "EC2", "instance_type": "t3.small"}}
    if compute_type == "EKS":
        return {**base, "architecture_style": "microservices",
                "compute": {"type": "EKS", "node_type": "t3.medium",
                            "min_nodes": 2, "max_nodes": 4}}
    if compute_type == "Lambda":
        return {**base, "architecture_style": "serverless",
                "networking": {"multi_az": False, "load_balancer": "API Gateway"},
                "compute": {"type": "Lambda", "runtime": "python3.12"}}
    raise ValueError(compute_type)


_COMPUTE_TO_TARGET = {"ECS": "ecs", "EKS": "eks", "Lambda": "lambda", "EC2": "ec2"}

# Compute type → the Terraform resource the FIX 3 consistency guard requires the
# seeded artifacts to declare so the deploy workflow targets real infrastructure.
_COMPUTE_TO_TF_RESOURCE = {
    "ECS": "aws_ecs_cluster",
    "EC2": "aws_instance",
    "EKS": "aws_eks_cluster",
    "Lambda": "aws_lambda_function",
}


# ── DB harness (mirrors tests/test_terraform_generation_status.py) ───────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for model in (Project, Workflow, Task, Artifact, ArtifactVersion):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed(db, compute_type: str, *, docker=True, tf=True, plan_selected=True,
          docker_done=True, tf_done=True):
    """Create a project + workflow + task + DB artifacts ready for the phase."""
    proj = Project(id="proj-1", owner_id="user-1", name="ghapp", current_status="active")
    db.add(proj)

    phases: dict = {}
    if plan_selected:
        phases["PLAN_SELECTED"] = {"status": "completed"}
    if docker_done:
        phases["DOCKER"] = {"status": "completed"}
    if tf_done:
        phases["TERRAFORM_GENERATION"] = {"status": "completed"}

    wf = Workflow(id="wf-1", project_id="proj-1", started_by="user-1",
                  current_phase="TERRAFORM_GENERATION", status="running",
                  phases_state=phases, logs=[])
    db.add(wf)

    task = Task(
        id="task-1", prompt="deploy", project_id="proj-1", workflow_id="wf-1",
        status="in_progress",
        workflow_state={
            "plan": {"infrastructure_blueprint": _blueprint(compute_type)},
            "selected_plan_id": "balanced",
            "logs": [],
        },
    )
    db.add(task)

    if docker:
        db.add(Artifact(project_id="proj-1", workflow_id="wf-1",
                        artifact_type="docker", artifact_subtype="dockerfile",
                        content="FROM python:3.12-slim\nEXPOSE 8000\nCMD [\"x\"]\n",
                        content_hash="h1", version=1))
    if tf:
        # Declare the compute resource the FIX 3 consistency guard requires for
        # this target so the deploy/bootstrap workflows are allowed to persist.
        resource = _COMPUTE_TO_TF_RESOURCE[compute_type]
        main_tf = f'resource "{resource}" "app" {{}}\n'
        for sub, body in (("terraform_main", main_tf),
                          ("terraform_providers", "terraform {}\n")):
            db.add(Artifact(project_id="proj-1", workflow_id="wf-1",
                            artifact_type="terraform", artifact_subtype=sub,
                            content=body, content_hash=sub, version=1))
    db.commit()
    return proj, wf, task


# ── 1. Unit: target derivation + render + validate per target ────────────────

@pytest.mark.parametrize("compute_type", ["ECS", "EKS", "Lambda", "EC2"])
def test_render_and_validate_each_target(db, compute_type):
    proj, wf, task = _seed(db, compute_type)
    state, ids = WOS.run_phase(
        db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS,
    )

    entry = wf.phases_state[PHASE_GH_ACTIONS]
    assert entry["status"] == "completed"
    assert entry["deployment_target"] == _COMPUTE_TO_TARGET[compute_type]
    assert entry["validation_status"] == "passed"

    # TWO github_actions artifacts (bootstrap + deploy), one type, two subtypes.
    rows = (db.query(Artifact)
              .filter(Artifact.project_id == "proj-1",
                      Artifact.artifact_type == "github_actions").all())
    assert len(rows) == 2
    assert {r.id for r in rows} == set(ids)
    by_path = {r.artifact_subtype: r.content for r in rows}
    assert set(by_path) == {
        ".github/workflows/bootstrap.yml",
        ".github/workflows/deploy.yml",
    }

    bootstrap = by_path[".github/workflows/bootstrap.yml"]
    deploy = by_path[".github/workflows/deploy.yml"]

    # Both are valid GitHub Actions YAML with GH expressions preserved untouched.
    for content in (bootstrap, deploy):
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict) and "jobs" in parsed
        assert "${{ secrets.AWS_ACCESS_KEY_ID }}" in content
        assert "configure-aws-credentials" in content

    # bootstrap PROVISIONS (terraform) and is manual-only (no push trigger).
    assert "terraform init" in bootstrap
    assert "terraform apply" in bootstrap
    assert "workflow_dispatch" in bootstrap
    assert "push:" not in bootstrap

    # deploy DELIVERS only — never any terraform; push-triggered + concurrency.
    assert "terraform init" not in deploy
    assert "terraform apply" not in deploy
    assert "docker build" in deploy
    assert "docker push" in deploy
    assert "push:" in deploy
    assert "concurrency:" in deploy


# ── 2. Workflow reaches a terminal completed state ───────────────────────────

def test_phase_completes_workflow(db):
    proj, wf, task = _seed(db, "ECS")
    WOS.run_phase(db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS)
    assert wf.status == "completed"
    assert wf.current_phase == PHASE_GH_ACTIONS
    assert wf.finished_at is not None


# ── 3. Read projection surfaces the generated workflow ───────────────────────

def test_projection_after_generation(db):
    proj, wf, task = _seed(db, "EKS")
    WOS.run_phase(db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS)

    from backend.app.services.core.github_actions_phase_projection_service import (
        GitHubActionsPhaseProjectionService,
    )
    resp = GitHubActionsPhaseProjectionService.build(
        db, project_id="proj-1", workflow=wf, task=task,
    )
    assert resp.generated is True
    assert resp.deployment_target == "eks"
    assert resp.phase_status == "completed"

    # Both pipelines are projected, bootstrap first then deploy.
    assert [p.kind for p in resp.pipelines] == ["bootstrap", "deploy"]
    pipelines = {p.kind: p for p in resp.pipelines}
    assert pipelines["bootstrap"].path == ".github/workflows/bootstrap.yml"
    assert pipelines["deploy"].path == ".github/workflows/deploy.yml"
    assert pipelines["bootstrap"].name == "Infrastructure Pipeline"
    assert pipelines["deploy"].name == "Delivery Pipeline"
    assert "terraform apply" in pipelines["bootstrap"].content
    assert "terraform apply" not in pipelines["deploy"].content
    assert pipelines["deploy"].version == 1  # DB-backed provenance

    # Back-compat: workflow_file still points at the delivery (deploy.yml) file.
    assert resp.workflow_file is not None
    assert resp.workflow_file.path == ".github/workflows/deploy.yml"
    assert "jobs:" in resp.workflow_file.content
    assert "terraform apply" not in resp.workflow_file.content
    assert resp.deployment_context.terraform_artifacts  # consumed artifacts listed


def test_projection_before_generation_is_graceful(db):
    proj, wf, task = _seed(db, "ECS", docker_done=False, tf_done=False)
    from backend.app.services.core.github_actions_phase_projection_service import (
        GitHubActionsPhaseProjectionService,
    )
    resp = GitHubActionsPhaseProjectionService.build(
        db, project_id="proj-1", workflow=wf, task=task,
    )
    assert resp.generated is False
    assert resp.workflow_file is None


# ── 4. Prerequisites enforced ────────────────────────────────────────────────

def test_requires_plan_selected(db):
    proj, wf, task = _seed(db, "ECS", plan_selected=False)
    with pytest.raises(ValueError, match="PLAN_SELECTED"):
        WOS.run_phase(db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS)


def test_requires_docker(db):
    proj, wf, task = _seed(db, "ECS", docker_done=False)
    with pytest.raises(ValueError, match="DOCKER"):
        WOS.run_phase(db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS)


def test_requires_terraform_generation(db):
    proj, wf, task = _seed(db, "ECS", tf_done=False)
    with pytest.raises(ValueError, match="TERRAFORM_GENERATION"):
        WOS.run_phase(db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS)


def test_missing_artifacts_is_rejected(db):
    """Prereqs marked done but the artifacts are absent → builder rejects (400)."""
    proj, wf, task = _seed(db, "ECS", docker=False)
    with pytest.raises(ValueError, match="Docker artifacts"):
        WOS.run_phase(db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS)


# ── 5. YAML validator unit ───────────────────────────────────────────────────

def test_yaml_validator_rejects_empty_invalid_malformed():
    from backend.app.services.github_actions_generation.yaml_validator import (
        validate_workflow_yaml,
    )
    assert validate_workflow_yaml("").valid is False
    assert validate_workflow_yaml("   \n  ").valid is False
    assert validate_workflow_yaml("a: [b: c").valid is False          # invalid YAML
    # Parses, but no jobs / no trigger → malformed workflow.
    res = validate_workflow_yaml("name: x\n")
    assert res.valid is False
    assert any("jobs" in e for e in res.errors)
    # A real workflow passes ('on' parses to the boolean True under YAML 1.1).
    ok = "name: x\non:\n  push:\n    branches: [main]\njobs:\n  d:\n    steps:\n      - run: echo hi\n"
    assert validate_workflow_yaml(ok).valid is True


# ── 6. Idempotent re-run keeps a single artifact ─────────────────────────────

def test_two_artifact_persistence_subtypes(db):
    """The phase persists exactly two github_actions rows keyed by on-disk path."""
    proj, wf, task = _seed(db, "Lambda")
    _, ids = WOS.run_phase(
        db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS,
    )
    rows = (db.query(Artifact)
              .filter(Artifact.project_id == "proj-1",
                      Artifact.artifact_type == "github_actions").all())
    assert len(ids) == 2 and len(rows) == 2
    # One artifact_type, two subtypes — no new artifact type introduced.
    assert {r.artifact_type for r in rows} == {"github_actions"}
    assert {r.artifact_subtype for r in rows} == {
        ".github/workflows/bootstrap.yml",
        ".github/workflows/deploy.yml",
    }
    assert all(r.validation_status == "passed" for r in rows)


# ── 7. Pipeline-aware validation: terraform required/forbidden ───────────────

def test_validate_pipeline_bootstrap_requires_terraform():
    from backend.app.services.github_actions_generation.yaml_validator import (
        validate_pipeline,
    )
    from backend.app.services.github_actions_generation.models import DeploymentContext
    from backend.app.services.github_actions_generation.renderer import render_workflow

    ctx = DeploymentContext(deployment_target="ecs", project_name="x",
                            cluster_name="c", service_name="s")
    _, bootstrap = render_workflow(ctx, "bootstrap")
    assert validate_pipeline(bootstrap, kind="bootstrap").valid is True

    # A structurally valid workflow that provisions nothing (terraform init but
    # no apply) must be rejected as a bootstrap pipeline.
    no_apply = (
        "name: x\n"
        "on:\n  workflow_dispatch:\n"
        "jobs:\n  bootstrap:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: init\n        run: terraform init -input=false\n"
    )
    res = validate_pipeline(no_apply, kind="bootstrap")
    assert res.valid is False
    assert any("terraform apply" in e for e in res.errors)


def test_validate_pipeline_deploy_forbids_terraform():
    from backend.app.services.github_actions_generation.yaml_validator import (
        validate_pipeline,
    )
    from backend.app.services.github_actions_generation.models import DeploymentContext
    from backend.app.services.github_actions_generation.renderer import render_workflow

    ctx = DeploymentContext(deployment_target="ecs", project_name="x",
                            cluster_name="c", service_name="s")
    _, deploy = render_workflow(ctx, "deploy")
    assert validate_pipeline(deploy, kind="deploy", deployment_target="ecs").valid is True

    # Inject a terraform step → delivery workflow must be rejected.
    bad = deploy + "\n      - name: oops\n        run: terraform apply\n"
    res = validate_pipeline(bad, kind="deploy", deployment_target="ecs")
    assert res.valid is False
    assert any("must not contain 'terraform apply'" in e for e in res.errors)


@pytest.mark.parametrize("target,command", [
    ("ecs", "aws ecs update-service"),
    ("eks", "kubectl"),
    ("lambda", "aws lambda update-function-code"),
    ("ec2", "aws ssm send-command"),
])
def test_deploy_requires_docker_and_deployment_command(target, command):
    from backend.app.services.github_actions_generation.yaml_validator import (
        validate_pipeline,
    )
    from backend.app.services.github_actions_generation.models import DeploymentContext
    from backend.app.services.github_actions_generation.renderer import render_workflow

    ctx = DeploymentContext(deployment_target=target, project_name="x",
                            cluster_name="c", service_name="s", function_name="f")
    _, deploy = render_workflow(ctx, "deploy")
    assert "docker build" in deploy and "docker push" in deploy
    assert command in deploy
    assert validate_pipeline(deploy, kind="deploy", deployment_target=target).valid is True


def test_deploy_has_test_detection_and_concurrency():
    """Option B: deploy.yml auto-detects the toolchain and serialises deploys."""
    from backend.app.services.github_actions_generation.models import DeploymentContext
    from backend.app.services.github_actions_generation.renderer import render_workflow

    ctx = DeploymentContext(deployment_target="ecs", project_name="x",
                            cluster_name="c", service_name="s")
    _, deploy = render_workflow(ctx, "deploy")
    # Toolchain detection markers (Spring Boot / Gradle / Node / Angular / Python).
    for marker in ("pom.xml", "build.gradle", "package.json", "angular.json",
                   "pytest", "mvn -B test"):
        assert marker in deploy
    assert "continue-on-error: true" in deploy
    assert "concurrency:" in deploy and "cancel-in-progress: true" in deploy


def test_architecture_inconsistency_fails_phase_and_persists_nothing(db):
    """FIX 3 — an eks target over Terraform that declares no aws_eks_cluster
    fails GITHUB_ACTIONS_GENERATION and persists no workflow artifacts."""
    proj, wf, task = _seed(db, "EKS")
    # Replace the seeded Terraform so it no longer declares aws_eks_cluster
    # (simulating Terraform generated for the wrong target).
    main = (db.query(Artifact)
              .filter(Artifact.project_id == "proj-1",
                      Artifact.artifact_type == "terraform",
                      Artifact.artifact_subtype == "terraform_main").one())
    main.content = 'resource "aws_ecs_cluster" "main" {}\n'
    db.commit()

    state, ids = WOS.run_phase(
        db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS,
    )

    entry = wf.phases_state[PHASE_GH_ACTIONS]
    assert entry["status"] == "failed"
    assert entry["architecture_consistency"]["consistent"] is False
    assert entry["architecture_consistency"]["required_resource"] == "aws_eks_cluster"
    assert ids == []
    # Nothing was persisted — no half-installed pipeline pointing at missing infra.
    rows = (db.query(Artifact)
              .filter(Artifact.project_id == "proj-1",
                      Artifact.artifact_type == "github_actions").all())
    assert rows == []
    # The run stays open so it can be re-run after Terraform is regenerated.
    assert wf.status == "running"


def test_rerun_is_idempotent(db):
    proj, wf, task = _seed(db, "ECS")
    WOS.run_phase(db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS)
    WOS.run_phase(db, project=proj, workflow=wf, task=task, phase=PHASE_GH_ACTIONS)
    rows = (db.query(Artifact)
              .filter(Artifact.project_id == "proj-1",
                      Artifact.artifact_type == "github_actions").all())
    # Still exactly TWO rows — upsert dedupes by (project, type, subtype); the two
    # subtypes (bootstrap.yml + deploy.yml) are the only github_actions artifacts.
    assert len(rows) == 2
    assert {r.artifact_subtype for r in rows} == {
        ".github/workflows/bootstrap.yml",
        ".github/workflows/deploy.yml",
    }
    assert all(r.version == 1 for r in rows)  # identical content → no version bump
