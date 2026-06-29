"""FIX 3 — Architecture consistency guard for GitHub Actions generation.

Before the generated deploy/bootstrap workflows are persisted, verify that the
Terraform artifacts actually provision the compute resource the deployment
target assumes. The deploy templates are keyed on ``compute.type`` while the
Terraform templates are keyed on ``architecture_style`` — a divergence (e.g. an
``eks`` deploy workflow over Terraform that declares no ``aws_eks_cluster``)
would install a pipeline that can only fail at run time.

This module is pure (no DB, no I/O, no LLM): given the deployment target and the
``{filename: hcl}`` Terraform artifacts, it asserts the required resource is
declared. The orchestrator fails GITHUB_ACTIONS_GENERATION when it is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from backend.app.services.github_actions_generation.terraform_identifiers import (
    TerraformIdentifiers,
    extract_terraform_identifiers,
)

# deployment_target → the Terraform resource type that MUST be declared for the
# generated workflow to target real infrastructure.
REQUIRED_RESOURCE_BY_TARGET: Dict[str, str] = {
    "ecs": "aws_ecs_cluster",
    "eks": "aws_eks_cluster",
    "ec2": "aws_instance",
    "lambda": "aws_lambda_function",
}

# Pipeline env var → the human-readable resource it names. The deploy/bootstrap
# templates expose each infrastructure identifier as a top-level ``env:`` entry
# (e.g. ``ECR_REPOSITORY: << repository_name >>``); these are the keys the
# name-consistency guard reads back out of the RENDERED workflow.
_PIPELINE_ENV_KEYS = (
    "AWS_REGION",
    "ECR_REPOSITORY",
    "ECS_CLUSTER",
    "ECS_SERVICE",
    "EKS_CLUSTER",
    "LAMBDA_FUNCTION",
)


@dataclass
class ConsistencyResult:
    """Outcome of the architecture-consistency check."""

    consistent: bool
    deployment_target: str
    required_resource: str
    errors: List[str] = field(default_factory=list)


def _declares_resource(terraform_hcl: str, resource_type: str) -> bool:
    """True when ``terraform_hcl`` declares a ``resource "<resource_type>"`` block."""
    pattern = re.compile(r'resource\s+"' + re.escape(resource_type) + r'"')
    return bool(pattern.search(terraform_hcl or ""))


def verify_architecture_consistency(
    deployment_target: str,
    terraform_files: Mapping[str, str],
) -> ConsistencyResult:
    """Verify the Terraform artifacts declare the resource ``deployment_target`` needs.

    Returns a :class:`ConsistencyResult`. An unknown target is treated as
    consistent (there is no rule to assert) so this never blocks on an enum it
    does not recognise — the deployment_target Literal is validated elsewhere.
    """
    required = REQUIRED_RESOURCE_BY_TARGET.get(deployment_target)
    if required is None:
        return ConsistencyResult(
            consistent=True,
            deployment_target=deployment_target,
            required_resource="",
        )

    combined_hcl = "\n".join(str(content) for content in terraform_files.values())
    if _declares_resource(combined_hcl, required):
        return ConsistencyResult(
            consistent=True,
            deployment_target=deployment_target,
            required_resource=required,
        )

    return ConsistencyResult(
        consistent=False,
        deployment_target=deployment_target,
        required_resource=required,
        errors=[
            f"Deployment target '{deployment_target}' requires the Terraform "
            f"artifacts to declare a '{required}' resource, but none was found. "
            f"The generated deploy workflow would target infrastructure that the "
            f"Terraform never provisions — regenerate Terraform for this target "
            f"before installing the pipelines."
        ],
    )


# ── Resource-NAME consistency (Terraform identifiers vs pipeline references) ──


def _extract_pipeline_env(content: str) -> Dict[str, str]:
    """Pull the infrastructure identifiers a rendered workflow references.

    Reads the top-level ``env:`` entries the templates expose (``ECR_REPOSITORY``,
    ``ECS_CLUSTER``, …). Values are bare literals (e.g. ``ECR_REPOSITORY: tp-devops``);
    surrounding quotes are stripped. Entries whose value is a GitHub expression
    (``${{ ... }}``) — e.g. ``IMAGE_TAG`` — are ignored (not in the key set).
    """
    refs: Dict[str, str] = {}
    for key in _PIPELINE_ENV_KEYS:
        m = re.search(
            r'(?m)^\s*' + re.escape(key) + r'\s*:\s*(.+?)\s*$', content or ""
        )
        if not m:
            continue
        value = m.group(1).strip().strip('"').strip("'")
        if value and "${{" not in value:
            refs[key] = value
    return refs


def _expected_identifiers(
    deployment_target: str, tf: TerraformIdentifiers,
) -> Dict[str, Optional[str]]:
    """Map the pipeline env keys RELEVANT to ``deployment_target`` → Terraform names.

    ECR + region are universal; the orchestrator name is whichever the target
    uses (ECS cluster+service, EKS cluster, Lambda function). EC2 has no
    name-bearing compute resource (instances are tag-identified), so only ECR +
    region are asserted for it.
    """
    expected: Dict[str, Optional[str]] = {
        "ECR_REPOSITORY": tf.ecr_repository,
        "AWS_REGION": tf.aws_region,
    }
    if deployment_target == "ecs":
        expected["ECS_CLUSTER"] = tf.ecs_cluster
        expected["ECS_SERVICE"] = tf.ecs_service
    elif deployment_target == "eks":
        expected["EKS_CLUSTER"] = tf.eks_cluster
    elif deployment_target == "lambda":
        expected["LAMBDA_FUNCTION"] = tf.lambda_function
    return expected


def verify_resource_name_consistency(
    *,
    deployment_target: str,
    terraform_files: Mapping[str, str],
    pipeline_files: Iterable[Tuple[str, str]],
) -> ConsistencyResult:
    """Assert every infrastructure name a pipeline references matches Terraform.

    For each rendered workflow (``(label, yaml)``), compare the identifiers it
    references in its ``env:`` block against the literal names the Terraform
    artifacts declare (the source of truth). A pipeline that points at a resource
    name Terraform never created can only fail at run time, so a mismatch makes
    the result ``inconsistent`` and the orchestrator fails
    ``GITHUB_ACTIONS_GENERATION``.

    Only fields present on BOTH sides are compared: an identifier Terraform did
    not declare, or one the pipeline does not reference, is skipped (the
    resource-presence guard already covers a missing required resource).
    """
    tf = extract_terraform_identifiers(terraform_files)
    expected = _expected_identifiers(deployment_target, tf)
    errors: List[str] = []

    for label, content in pipeline_files:
        refs = _extract_pipeline_env(content)
        for env_key, tf_value in expected.items():
            ref_value = refs.get(env_key)
            if not tf_value or not ref_value:
                continue
            if ref_value != tf_value:
                errors.append(
                    f"{label}: {env_key}='{ref_value}' but Terraform declares "
                    f"'{tf_value}'. The pipeline references a resource name the "
                    f"Terraform never creates — regenerate so GitHub Actions "
                    f"consumes the Terraform-generated identifier."
                )

    return ConsistencyResult(
        consistent=not errors,
        deployment_target=deployment_target,
        required_resource=REQUIRED_RESOURCE_BY_TARGET.get(deployment_target, ""),
        errors=errors,
    )
