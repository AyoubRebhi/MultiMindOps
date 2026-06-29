"""FIX 3 — architecture consistency guard for GitHub Actions generation.

Pins the rule that a deployment target may only ship its deploy/bootstrap
workflows when the Terraform artifacts actually declare the compute resource the
target assumes. The check is pure ({target, terraform files} → result), so these
tests need no DB or network.
"""

from __future__ import annotations

from backend.app.services.github_actions_generation.architecture_consistency import (
    REQUIRED_RESOURCE_BY_TARGET,
    verify_architecture_consistency,
)

# Minimal HCL fragments — only the resource header matters to the guard.
ECS_TF = {"main.tf": 'resource "aws_ecs_cluster" "main" {\n  name = "x"\n}\n'}
EKS_TF = {"main.tf": 'resource "aws_eks_cluster" "main" {\n  name = "x"\n}\n'}
EC2_TF = {"main.tf": 'resource "aws_instance" "app" {\n  ami = "ami-1"\n}\n'}
LAMBDA_TF = {"main.tf": 'resource "aws_lambda_function" "app" {\n  function_name = "x"\n}\n'}


def test_each_target_consistent_with_its_required_resource():
    assert verify_architecture_consistency("ecs", ECS_TF).consistent
    assert verify_architecture_consistency("eks", EKS_TF).consistent
    assert verify_architecture_consistency("ec2", EC2_TF).consistent
    assert verify_architecture_consistency("lambda", LAMBDA_TF).consistent


def test_eks_target_over_ecs_terraform_is_inconsistent():
    result = verify_architecture_consistency("eks", ECS_TF)
    assert not result.consistent
    assert result.required_resource == "aws_eks_cluster"
    assert result.errors and "aws_eks_cluster" in result.errors[0]


def test_ec2_target_over_monolith_ecs_terraform_is_inconsistent():
    # The real EC2 trap: monolith Terraform provisions ECS Fargate, never an
    # aws_instance, but the ec2 deploy workflow SSMs into tagged instances.
    result = verify_architecture_consistency("ec2", ECS_TF)
    assert not result.consistent
    assert result.required_resource == "aws_instance"


def test_lambda_target_without_lambda_function_is_inconsistent():
    result = verify_architecture_consistency("lambda", ECS_TF)
    assert not result.consistent
    assert result.required_resource == "aws_lambda_function"


def test_resource_match_spans_all_terraform_files():
    files = {
        "variables.tf": 'variable "x" {}\n',
        "main.tf": 'resource "aws_eks_cluster" "main" {}\n',
    }
    assert verify_architecture_consistency("eks", files).consistent


def test_empty_terraform_is_inconsistent_for_every_known_target():
    for target, required in REQUIRED_RESOURCE_BY_TARGET.items():
        result = verify_architecture_consistency(target, {})
        assert not result.consistent
        assert result.required_resource == required


def test_unknown_target_is_treated_as_consistent():
    # No rule to assert — never block on an enum we don't recognise.
    assert verify_architecture_consistency("fargate-spot", ECS_TF).consistent
