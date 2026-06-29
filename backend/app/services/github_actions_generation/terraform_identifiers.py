"""Read the canonical infrastructure identifiers Terraform declares.

Terraform is the SINGLE SOURCE OF TRUTH for every infrastructure name. The
generated ``.tf`` files carry those names as LITERALS — the terraform variable
context pre-resolves each AWS-bounded name and injects it verbatim (e.g.
``name = "tp-devops"``, ``function_name = "..."``), so the identifiers can be
read back deterministically with a few HCL regexes. No terraform binary, no
state file, no AWS API call.

These extracted identifiers are what the GitHub Actions pipelines MUST reference:
:class:`DeploymentContextBuilder` populates the deployment context from them
(so the rendered workflow targets the real ECR repo / ECS cluster+service / EKS
cluster / Lambda function Terraform creates), and the consistency guard
(:mod:`architecture_consistency`) compares the rendered pipelines back against
them — failing ``GITHUB_ACTIONS_GENERATION`` on any divergence.

This module is pure (no DB, no I/O, no LLM): ``{filename: hcl} → identifiers``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional

# Terraform resource type → the argument that holds its name. These are the
# resources whose names the deploy/bootstrap pipelines reference at run time.
_RESOURCE_NAME_ATTR: dict[str, str] = {
    "aws_ecr_repository": "name",
    "aws_ecs_cluster": "name",
    "aws_ecs_service": "name",
    "aws_eks_cluster": "name",
    "aws_lambda_function": "function_name",
}


@dataclass
class TerraformIdentifiers:
    """The infrastructure identifiers a generated Terraform module declares.

    Every field is ``None`` when the corresponding resource is not present —
    the consumers (context builder, consistency guard) only act on the fields
    that exist, so a serverless module (Lambda, no ECS) leaves the ECS fields
    ``None`` and they are simply not checked.
    """

    ecr_repository: Optional[str] = None
    ecs_cluster: Optional[str] = None
    ecs_service: Optional[str] = None
    eks_cluster: Optional[str] = None
    lambda_function: Optional[str] = None
    aws_region: Optional[str] = None

    @property
    def cluster(self) -> Optional[str]:
        """The orchestrator cluster name (ECS or EKS — whichever the module has)."""
        return self.ecs_cluster or self.eks_cluster


def _extract_resource_name(hcl: str, resource_type: str, attr: str) -> Optional[str]:
    """Return the literal ``attr`` of the first ``resource "<type>"`` block.

    The name argument is always the first attribute in the generated blocks, so
    we match from the resource header up to (but not into) the first ``}`` — the
    ``[^}]*?`` lazily skips any whitespace/comment lines without crossing a block
    boundary, which keeps nested ``jsonencode({...})`` / ``network_configuration
    { ... }`` blocks (that appear AFTER the name) from being mis-parsed.
    """
    pattern = re.compile(
        r'resource\s+"' + re.escape(resource_type) + r'"\s+"[^"]+"\s*\{'
        r'[^}]*?\b' + re.escape(attr) + r'\s*=\s*"([^"]+)"',
        re.DOTALL,
    )
    match = pattern.search(hcl or "")
    return match.group(1) if match else None


def _extract_region(hcl: str) -> Optional[str]:
    """Return the literal ``aws_region`` assignment (from terraform.tfvars).

    The provider reads ``region = var.aws_region`` and the literal value lives in
    ``terraform.tfvars`` as ``aws_region = "us-east-1"``. We match that assignment
    (not the ``default`` inside the ``variable "aws_region"`` block, which uses a
    different left-hand side) so the value reflects what actually gets applied.
    """
    match = re.search(r'(?m)^\s*aws_region\s*=\s*"([^"]+)"', hcl or "")
    return match.group(1) if match else None


def extract_terraform_identifiers(
    terraform_files: Mapping[str, str],
) -> TerraformIdentifiers:
    """Parse the generated Terraform ``{filename: hcl}`` into typed identifiers.

    Scans the concatenation of every file so an identifier is found regardless of
    which ``.tf`` it lives in (resources in ``main.tf``, the region literal in
    ``terraform.tfvars``).
    """
    combined = "\n".join(
        str(content) for content in (terraform_files or {}).values()
        if isinstance(content, str)
    )
    return TerraformIdentifiers(
        ecr_repository=_extract_resource_name(
            combined, "aws_ecr_repository", _RESOURCE_NAME_ATTR["aws_ecr_repository"]
        ),
        ecs_cluster=_extract_resource_name(
            combined, "aws_ecs_cluster", _RESOURCE_NAME_ATTR["aws_ecs_cluster"]
        ),
        ecs_service=_extract_resource_name(
            combined, "aws_ecs_service", _RESOURCE_NAME_ATTR["aws_ecs_service"]
        ),
        eks_cluster=_extract_resource_name(
            combined, "aws_eks_cluster", _RESOURCE_NAME_ATTR["aws_eks_cluster"]
        ),
        lambda_function=_extract_resource_name(
            combined, "aws_lambda_function", _RESOURCE_NAME_ATTR["aws_lambda_function"]
        ),
        aws_region=_extract_region(combined),
    )
