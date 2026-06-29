"""Terraform → GitHub Actions resource-name propagation.

Terraform is the SOURCE OF TRUTH for every infrastructure identifier. These
tests pin the two halves of the guarantee:

1. ``extract_terraform_identifiers`` reads the literal names Terraform declares
   (ECR repo / ECS cluster+service / EKS cluster / Lambda function / region).
2. The deployment context is populated FROM those identifiers (not re-derived),
   and ``verify_resource_name_consistency`` fails when a rendered pipeline
   references a name Terraform never created — the exact ECR divergence the bug
   report described (``ECR_REPOSITORY=tp-devops`` over a UUID-named repository).

All pure ({hcl}/{yaml} → result), so no DB or network is needed.
"""

from __future__ import annotations

from backend.app.services.github_actions_generation.architecture_consistency import (
    verify_resource_name_consistency,
)
from backend.app.services.github_actions_generation.deployment_context_builder import (
    DeploymentContextBuilder,
)
from backend.app.services.github_actions_generation.terraform_identifiers import (
    TerraformIdentifiers,
    extract_terraform_identifiers,
)

# ── Realistic generated Terraform (literal names, as the templates render) ─────

ECS_MAIN_TF = """
resource "aws_ecr_repository" "app" {
  name                 = "tp-devops"
  image_tag_mutability = "IMMUTABLE"
}

resource "aws_ecs_cluster" "main" {
  name = "tp-devops-cluster"
}

resource "aws_ecs_service" "app" {
  name            = "tp-devops-service"
  cluster         = aws_ecs_cluster.main.id
  desired_count   = 1

  network_configuration {
    subnets          = aws_subnet.public[*].id
    assign_public_ip = true
  }
}
"""
ECS_TFVARS = 'project_name = "tp-devops"\naws_region   = "eu-west-3"\n'
ECS_FILES = {"main.tf": ECS_MAIN_TF, "terraform.tfvars": ECS_TFVARS}

EKS_FILES = {
    "main.tf": 'resource "aws_ecr_repository" "app" {\n  name = "svc"\n}\n'
    'resource "aws_eks_cluster" "main" {\n  name     = "svc-eks"\n'
    '  role_arn = aws_iam_role.c.arn\n}\n',
    "terraform.tfvars": 'aws_region = "us-east-1"\n',
}
LAMBDA_FILES = {
    "main.tf": 'resource "aws_ecr_repository" "app" {\n  name = "fn"\n}\n'
    'resource "aws_lambda_function" "app" {\n  function_name = "fn-handler"\n'
    '  role          = aws_iam_role.l.arn\n}\n',
    "terraform.tfvars": 'aws_region = "us-east-1"\n',
}


# ── Identifier extraction ──────────────────────────────────────────────────


def test_extract_ecs_identifiers():
    ids = extract_terraform_identifiers(ECS_FILES)
    assert ids.ecr_repository == "tp-devops"
    assert ids.ecs_cluster == "tp-devops-cluster"
    assert ids.ecs_service == "tp-devops-service"
    assert ids.aws_region == "eu-west-3"
    assert ids.cluster == "tp-devops-cluster"
    # No EKS / Lambda in an ECS module.
    assert ids.eks_cluster is None
    assert ids.lambda_function is None


def test_extract_eks_and_lambda_identifiers():
    eks = extract_terraform_identifiers(EKS_FILES)
    assert eks.ecr_repository == "svc"
    assert eks.eks_cluster == "svc-eks"
    assert eks.cluster == "svc-eks"

    lam = extract_terraform_identifiers(LAMBDA_FILES)
    assert lam.ecr_repository == "fn"
    assert lam.lambda_function == "fn-handler"


def test_extract_ignores_variable_default_for_region():
    # The literal applied region lives in tfvars (`aws_region = "..."`), NOT in
    # the `variable "aws_region" { default = ... }` block.
    files = {
        "variables.tf": 'variable "aws_region" {\n  default = "us-west-2"\n}\n',
        "terraform.tfvars": 'aws_region = "eu-central-1"\n',
    }
    assert extract_terraform_identifiers(files).aws_region == "eu-central-1"


def test_extract_empty_terraform_yields_all_none():
    ids = extract_terraform_identifiers({})
    assert ids == TerraformIdentifiers()


# ── Deployment context is sourced FROM Terraform ────────────────────────────


def test_context_names_take_terraform_ecr_over_derived():
    # blueprint=None forces the sanitized-project-name fallback (would be
    # "tp-devops"); the Terraform identifiers must OVERRIDE it. This is the fix:
    # the ECR name the pipeline uses is whatever Terraform actually created.
    tf = TerraformIdentifiers(
        ecr_repository="d96e-49b7-4499-8472-c79ca134c376",
        ecs_cluster="d96e-cluster",
        ecs_service="d96e-service",
        aws_region="eu-west-3",
    )
    names = DeploymentContextBuilder._resolve_resource_names(
        None, project_name="TP DevOps", container_port=8080, tf_identifiers=tf,
    )
    assert names["repository_name"] == "d96e-49b7-4499-8472-c79ca134c376"
    assert names["cluster_name"] == "d96e-cluster"
    assert names["service_name"] == "d96e-service"
    assert names["aws_region"] == "eu-west-3"


def test_context_keeps_fallback_when_terraform_identifier_absent():
    # A degraded Terraform module that emitted no ECR resource must not blank the
    # name — the derived fallback stands.
    names = DeploymentContextBuilder._resolve_resource_names(
        None, project_name="acme-api", container_port=8080,
        tf_identifiers=TerraformIdentifiers(),
    )
    assert names["repository_name"] == "acme-api"


# ── Name-consistency guard ──────────────────────────────────────────────────


def _ecs_pipeline(*, ecr="tp-devops", cluster="tp-devops-cluster",
                  service="tp-devops-service", region="eu-west-3"):
    return (
        "deploy.yml",
        "env:\n"
        f"  AWS_REGION: {region}\n"
        f"  ECR_REPOSITORY: {ecr}\n"
        f"  ECS_CLUSTER: {cluster}\n"
        f"  ECS_SERVICE: {service}\n"
        "  IMAGE_TAG: ${{ github.sha }}\n",
    )


def test_consistent_when_pipeline_matches_terraform():
    result = verify_resource_name_consistency(
        deployment_target="ecs",
        terraform_files=ECS_FILES,
        pipeline_files=[_ecs_pipeline()],
    )
    assert result.consistent
    assert result.errors == []


def test_ecr_mismatch_fails_generation():
    # The reported bug: Terraform created a UUID-named repository, but the
    # pipeline references ECR_REPOSITORY=tp-devops.
    tf = {
        "main.tf": 'resource "aws_ecr_repository" "app" {\n'
        '  name = "d96e-49b7-4499-8472-c79ca134c376"\n}\n'
        'resource "aws_ecs_cluster" "main" {\n  name = "d96e-cluster"\n}\n'
        'resource "aws_ecs_service" "app" {\n  name = "d96e-service"\n}\n',
        "terraform.tfvars": 'aws_region = "eu-west-3"\n',
    }
    result = verify_resource_name_consistency(
        deployment_target="ecs",
        terraform_files=tf,
        pipeline_files=[_ecs_pipeline()],  # ECR_REPOSITORY=tp-devops
    )
    assert not result.consistent
    assert any("ECR_REPOSITORY" in e for e in result.errors)
    assert any("d96e-49b7-4499-8472-c79ca134c376" in e for e in result.errors)
    assert any("tp-devops" in e for e in result.errors)


def test_region_mismatch_fails_generation():
    result = verify_resource_name_consistency(
        deployment_target="ecs",
        terraform_files=ECS_FILES,  # region eu-west-3
        pipeline_files=[_ecs_pipeline(region="us-east-1")],
    )
    assert not result.consistent
    assert any("AWS_REGION" in e for e in result.errors)


def test_ecs_service_mismatch_fails_generation():
    result = verify_resource_name_consistency(
        deployment_target="ecs",
        terraform_files=ECS_FILES,
        pipeline_files=[_ecs_pipeline(service="wrong-service")],
    )
    assert not result.consistent
    assert any("ECS_SERVICE" in e for e in result.errors)


def test_eks_cluster_consistency():
    ok = (
        "deploy.yml",
        "env:\n  AWS_REGION: us-east-1\n  ECR_REPOSITORY: svc\n"
        "  EKS_CLUSTER: svc-eks\n",
    )
    bad = (
        "deploy.yml",
        "env:\n  AWS_REGION: us-east-1\n  ECR_REPOSITORY: svc\n"
        "  EKS_CLUSTER: other\n",
    )
    assert verify_resource_name_consistency(
        deployment_target="eks", terraform_files=EKS_FILES, pipeline_files=[ok],
    ).consistent
    assert not verify_resource_name_consistency(
        deployment_target="eks", terraform_files=EKS_FILES, pipeline_files=[bad],
    ).consistent


def test_lambda_function_consistency():
    bad = (
        "deploy.yml",
        "env:\n  AWS_REGION: us-east-1\n  ECR_REPOSITORY: fn\n"
        "  LAMBDA_FUNCTION: wrong\n",
    )
    result = verify_resource_name_consistency(
        deployment_target="lambda", terraform_files=LAMBDA_FILES, pipeline_files=[bad],
    )
    assert not result.consistent
    assert any("LAMBDA_FUNCTION" in e for e in result.errors)


def test_ec2_only_checks_ecr_and_region():
    # EC2 instances are tag-identified — there is no name-bearing compute
    # resource to compare, so only ECR + region are asserted. A pipeline that
    # matches those is consistent even though no cluster/service is checked.
    tf = {
        "main.tf": 'resource "aws_ecr_repository" "app" {\n  name = "mono"\n}\n'
        'resource "aws_instance" "app" {\n  ami = "ami-1"\n}\n',
        "terraform.tfvars": 'aws_region = "us-east-1"\n',
    }
    pipeline = (
        "deploy.yml",
        "env:\n  AWS_REGION: us-east-1\n  ECR_REPOSITORY: mono\n"
        '  PROJECT_TAG: mono\n  CONTAINER_PORT: "8080"\n',
    )
    assert verify_resource_name_consistency(
        deployment_target="ec2", terraform_files=tf, pipeline_files=[pipeline],
    ).consistent


def test_bootstrap_and_deploy_both_checked():
    # Both rendered files are audited; a divergence in EITHER fails the phase.
    bad_bootstrap = (
        "bootstrap.yml",
        "env:\n  AWS_REGION: eu-west-3\n  ECR_REPOSITORY: stale-name\n"
        "  ECS_CLUSTER: tp-devops-cluster\n  ECS_SERVICE: tp-devops-service\n",
    )
    result = verify_resource_name_consistency(
        deployment_target="ecs",
        terraform_files=ECS_FILES,
        pipeline_files=[bad_bootstrap, _ecs_pipeline()],
    )
    assert not result.consistent
    assert any(e.startswith("bootstrap.yml:") for e in result.errors)


def test_missing_identifier_is_skipped_not_failed():
    # When Terraform did not declare a name (None) the field is simply not
    # compared — the resource-PRESENCE guard handles a genuinely missing
    # resource; this guard is only about NAME divergence.
    tf = {"terraform.tfvars": 'aws_region = "us-east-1"\n'}  # no ECR resource
    result = verify_resource_name_consistency(
        deployment_target="ecs",
        terraform_files=tf,
        pipeline_files=[_ecs_pipeline(region="us-east-1")],
    )
    # ECR/cluster/service are None in TF → skipped; region matches → consistent.
    assert result.consistent
