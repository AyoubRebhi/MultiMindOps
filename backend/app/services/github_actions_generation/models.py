"""Deployment context model (Phase 1).

The ``DeploymentContext`` is the typed, self-contained input to GitHub Actions
generation. It is assembled ONCE by :class:`DeploymentContextBuilder` from data
earlier phases already persisted, then handed to the template selector + renderer.

It deliberately carries only what a deploy workflow needs:

* ``cloud_provider`` / ``deployment_target`` — WHERE we deploy (from the plan).
* ``aws_region`` + pre-resolved resource names — the SAME names Terraform creates
  (ECR repo / ECS cluster+service / EKS cluster / Lambda function), so the
  rendered workflow references real infrastructure, never a guessed name.
* ``docker_artifacts`` / ``terraform_artifacts`` — provenance of the inputs this
  deployment orchestrates (filenames only; the bytes live in the artifact store).
* ``infrastructure_summary`` — a small read-only digest for the UI / enrichment.

No secrets ever live here — AWS credentials are referenced as GitHub Actions
secrets inside the template (``${{ secrets.* }}``), not injected at generation
time.
"""

from __future__ import annotations

from typing import Dict, List, Literal

from pydantic import BaseModel, Field

# AWS is the only provider the platform targets today (blueprints are AWS-typed).
CloudProvider = Literal["aws"]

# Derived deterministically from the selected blueprint's ``compute.type``:
#   ECS → ecs   |   EKS → eks   |   Lambda → lambda   |   EC2 → ec2
DeploymentTarget = Literal["ecs", "eks", "lambda", "ec2"]


class DeploymentContext(BaseModel):
    """Typed input to GitHub Actions deployment-workflow generation."""

    # ── Where / how we deploy (from the architecture decision) ────────────────
    cloud_provider: CloudProvider = "aws"
    deployment_target: DeploymentTarget
    aws_region: str = "us-east-1"

    # ── Naming (resolved to match Terraform-created resources) ────────────────
    project_name: str = "app"
    # Local Docker image name + the ECR repository it is pushed to. Equal by
    # convention so ``docker build -t <image>`` and ``docker push <ecr>/<repo>``
    # line up without a second name to keep in sync.
    image_name: str = "app"
    repository_name: str = "app"
    # Target-specific identifiers — only the one(s) for ``deployment_target`` are
    # consumed by its template; the rest are harmless context.
    cluster_name: str = ""
    service_name: str = ""
    function_name: str = ""
    container_port: int = 8080

    # ── Where the consumed artifacts live in the repo ─────────────────────────
    terraform_directory: str = "terraform"
    dockerfile_path: str = "Dockerfile"

    # ── Provenance of the consumed artifacts (filenames, not content) ─────────
    docker_artifacts: List[str] = Field(default_factory=list)
    terraform_artifacts: List[str] = Field(default_factory=list)

    # ── Read-only digest for UI + optional enrichment ─────────────────────────
    infrastructure_summary: Dict = Field(default_factory=dict)

    def render_variables(self) -> Dict[str, object]:
        """Flat dict handed to the Jinja2 template (the renderer's context).

        Only literal, deterministic values — never secrets. Every key here must
        be referenced by at least one template (StrictUndefined catches drift in
        the other direction: a template var missing from this dict raises).
        """
        return {
            "cloud_provider": self.cloud_provider,
            "deployment_target": self.deployment_target,
            "aws_region": self.aws_region,
            "project_name": self.project_name,
            "image_name": self.image_name,
            "repository_name": self.repository_name,
            "cluster_name": self.cluster_name,
            "service_name": self.service_name,
            "function_name": self.function_name,
            "container_port": self.container_port,
            "terraform_directory": self.terraform_directory,
            "dockerfile_path": self.dockerfile_path,
        }
