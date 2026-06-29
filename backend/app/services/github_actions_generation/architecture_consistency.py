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
from typing import Dict, List, Mapping

# deployment_target → the Terraform resource type that MUST be declared for the
# generated workflow to target real infrastructure.
REQUIRED_RESOURCE_BY_TARGET: Dict[str, str] = {
    "ecs": "aws_ecs_cluster",
    "eks": "aws_eks_cluster",
    "ec2": "aws_instance",
    "lambda": "aws_lambda_function",
}


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
