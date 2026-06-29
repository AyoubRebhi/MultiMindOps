"""DeploymentContextBuilder — assemble a DeploymentContext from prior phases.

This is the ONLY place that reaches across phases to gather the deployment
inputs. It is pure assembly: it reads the selected architecture decision and the
DB-backed Docker/Terraform artifacts, then resolves them into a typed
:class:`DeploymentContext`. It performs NO generation, NO LLM calls, and NO
infrastructure execution.

Crucially, the deployment target is DERIVED from the selected plan's
``compute.type`` — the user is never asked (per the phase contract).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.task_service import TaskService
from backend.app.services.github_actions_generation.models import (
    DeploymentContext,
    DeploymentTarget,
)
from backend.app.services.github_actions_generation.terraform_identifiers import (
    TerraformIdentifiers,
    extract_terraform_identifiers,
)

logger = logging.getLogger(__name__)

# Blueprint compute.type → deployment target. The blueprint Literal is the
# authoritative source; this is a 1:1 lowercase map kept explicit so an
# unexpected value fails loudly rather than silently picking a wrong target.
_COMPUTE_TYPE_TO_TARGET: Dict[str, DeploymentTarget] = {
    "ECS": "ecs",
    "EKS": "eks",
    "LAMBDA": "lambda",
    "EC2": "ec2",
}

# Fallback when no blueprint compute.type is available — derive from the coarse
# architecture style instead (serverless→lambda, microservices→eks, else ec2).
_STYLE_TO_TARGET: Dict[str, DeploymentTarget] = {
    "serverless": "lambda",
    "microservices": "eks",
    "monolith": "ec2",
}

_DEFAULT_PORT = 8080


class DeploymentContextNotReady(Exception):
    """Raised when prior phases have not produced enough to deploy.

    Surfaced as an HTTP 400 by the phase route — the prerequisites gate should
    normally prevent this, but the builder fails loudly rather than emitting a
    workflow that references non-existent artifacts.
    """


class DeploymentContextBuilder:
    @staticmethod
    def build(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
    ) -> DeploymentContext:
        state: Dict[str, Any] = (
            TaskService.load_workflow_state(db, task) if task else {}
        ) or {}

        blueprint, blueprint_dict = DeploymentContextBuilder._load_blueprint(state)
        target = DeploymentContextBuilder._resolve_target(blueprint, blueprint_dict)

        # Pull DB-backed artifacts produced by the Docker + Terraform phases.
        docker_files = ArtifactPersistenceService.get_docker_artifacts(
            db, project_id=project.id
        )
        terraform_files = ArtifactPersistenceService.get_terraform_files(
            db, project_id=project.id
        )
        if not docker_files:
            raise DeploymentContextNotReady(
                "No Docker artifacts found — run the Docker Generation phase first."
            )
        if not terraform_files:
            raise DeploymentContextNotReady(
                "No Terraform artifacts found — run the Terraform Generation phase first."
            )

        # Terraform is the SOURCE OF TRUTH for every infrastructure name. Read the
        # identifiers it actually declares so the pipelines reference the real
        # ECR repo / cluster / service / function — never a name re-derived here
        # (which is exactly how the ECR repo and ECR_REPOSITORY diverged).
        tf_identifiers = extract_terraform_identifiers(terraform_files)

        names = DeploymentContextBuilder._resolve_resource_names(
            blueprint,
            project_name=project.name,
            container_port=DeploymentContextBuilder._extract_port(
                docker_files.get("dockerfile")
            ),
            tf_identifiers=tf_identifiers,
        )

        ctx = DeploymentContext(
            cloud_provider="aws",
            deployment_target=target,
            aws_region=names["aws_region"],
            project_name=names["project_name"],
            image_name=names["repository_name"],
            repository_name=names["repository_name"],
            cluster_name=names["cluster_name"],
            service_name=names["service_name"],
            function_name=names["function_name"],
            container_port=names["container_port"],
            terraform_directory="terraform",
            dockerfile_path="Dockerfile",
            docker_artifacts=sorted(docker_files.keys()),
            terraform_artifacts=sorted(terraform_files.keys()),
            infrastructure_summary=DeploymentContextBuilder._build_summary(
                workflow, blueprint_dict, target
            ),
        )
        logger.info(
            "[GitHubActions] deployment context built project=%s target=%s "
            "region=%s docker=%d tf=%d",
            project.id, ctx.deployment_target, ctx.aws_region,
            len(ctx.docker_artifacts), len(ctx.terraform_artifacts),
        )
        return ctx

    # ── Blueprint loading ─────────────────────────────────────────────────────

    @staticmethod
    def _load_blueprint(state: Dict[str, Any]):
        """Return ``(parsed_blueprint_or_None, raw_blueprint_dict)``.

        The selected plan's blueprint lives at ``state["plan"]
        ["infrastructure_blueprint"]`` after ``resume_with_selected_plan``.
        Parsing is best-effort: a parse failure falls back to style-based target
        resolution rather than blocking the whole deployment.
        """
        plan = state.get("plan") or {}
        raw = plan.get("infrastructure_blueprint") or {}
        if not raw:
            raise DeploymentContextNotReady(
                "No architecture decision found — select a plan before generating "
                "the deployment workflow."
            )

        from backend.app.schemas.blueprint import parse_blueprint

        try:
            return parse_blueprint(raw), raw
        except Exception as exc:  # noqa: BLE001 — degrade, do not block
            logger.warning(
                "[GitHubActions] blueprint parse failed (%s) — deriving target "
                "from architecture_style only",
                exc.__class__.__name__,
            )
            return None, raw

    @staticmethod
    def _resolve_target(blueprint: Any, blueprint_dict: Dict[str, Any]) -> DeploymentTarget:
        """Deployment target from the selected architecture (never from the user)."""
        if blueprint is not None:
            mapped = _COMPUTE_TYPE_TO_TARGET.get(str(blueprint.compute.type).upper())
            if mapped:
                return mapped

        # Fallbacks: raw compute.type, then architecture_style, then ec2.
        compute = (blueprint_dict.get("compute") or {})
        raw_type = str(compute.get("type") or "").upper()
        if raw_type in _COMPUTE_TYPE_TO_TARGET:
            return _COMPUTE_TYPE_TO_TARGET[raw_type]

        style = str(blueprint_dict.get("architecture_style") or "").lower()
        return _STYLE_TO_TARGET.get(style, "ec2")

    # ── Resource names (aligned with Terraform) ───────────────────────────────

    @staticmethod
    def _resolve_resource_names(
        blueprint: Any,
        *,
        project_name: Optional[str],
        container_port: int,
        tf_identifiers: TerraformIdentifiers,
    ) -> Dict[str, Any]:
        """Resolve names, with the generated Terraform as the SOURCE OF TRUTH.

        The blueprint-derived names (via ``build_variable_context``) are only a
        FALLBACK/seed — for ``project_name`` (no Terraform resource carries it
        verbatim) and for any identifier a degraded module did not emit. Every
        identifier Terraform actually declares (ECR repo / ECS cluster+service /
        EKS cluster / Lambda function / region) OVERRIDES the derived value, so
        the deploy workflow can only ever reference real, provisioned resources.
        """
        from backend.app.services.terraform_generation.utils.variable_context import (
            sanitize_terraform_name,
        )

        if blueprint is not None:
            from backend.app.services.terraform_generation.utils.variable_context import (
                build_variable_context,
            )

            vctx = build_variable_context(
                blueprint,
                project_name=project_name,
                container_port=container_port,
            )
            names: Dict[str, Any] = {
                "aws_region": vctx["aws_region"],
                "project_name": vctx["project_name"],
                "repository_name": vctx["ecr_repository_name"],
                "cluster_name": vctx.get("ecs_cluster_name")
                or vctx.get("eks_cluster_name")
                or "",
                "service_name": vctx.get("ecs_service_name") or "",
                "function_name": vctx.get("lambda_function_name") or "",
                "container_port": container_port,
            }
        else:
            safe = sanitize_terraform_name(project_name, fallback="devsecops-app")
            names = {
                "aws_region": "us-east-1",
                "project_name": safe,
                "repository_name": safe,
                "cluster_name": safe,
                "service_name": safe,
                "function_name": safe,
                "container_port": container_port,
            }

        # Terraform overrides — these are the names that actually exist in AWS.
        DeploymentContextBuilder._apply_terraform_identifiers(names, tf_identifiers)
        return names

    @staticmethod
    def _apply_terraform_identifiers(
        names: Dict[str, Any], tf: TerraformIdentifiers,
    ) -> None:
        """Overlay the Terraform-declared identifiers onto ``names`` in place.

        Only non-empty Terraform values win; a missing identifier leaves the
        blueprint-derived fallback untouched so a partially-degraded Terraform
        module still yields a renderable context.
        """
        if tf.aws_region:
            names["aws_region"] = tf.aws_region
        if tf.ecr_repository:
            names["repository_name"] = tf.ecr_repository
        if tf.cluster:
            names["cluster_name"] = tf.cluster
        if tf.ecs_service:
            names["service_name"] = tf.ecs_service
        if tf.lambda_function:
            names["function_name"] = tf.lambda_function

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_port(dockerfile: Optional[str]) -> int:
        """Best-effort container port from the generated Dockerfile's EXPOSE."""
        if isinstance(dockerfile, str):
            m = re.search(r"(?im)^\s*EXPOSE\s+(\d+)", dockerfile)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    pass
        return _DEFAULT_PORT

    @staticmethod
    def _build_summary(
        workflow: Workflow,
        blueprint_dict: Dict[str, Any],
        target: DeploymentTarget,
    ) -> Dict[str, Any]:
        """Read-only digest: validation statuses + the terraform plan summary.

        Pure projection over ``Workflow.phases_state`` — no recomputation. Lets
        the UI (and the optional enrichment step) show what the deploy workflow
        is built on top of without a second query.
        """
        phases = workflow.phases_state or {}
        tf_plan = phases.get("TERRAFORM_PLAN") or {}
        summary: Dict[str, Any] = {
            "deployment_target": target,
            "architecture_style": blueprint_dict.get("architecture_style"),
            "docker_status": (phases.get("DOCKER") or {}).get("status"),
            "terraform_generation_status": (
                phases.get("TERRAFORM_GENERATION") or {}
            ).get("status"),
            "terraform_validation_status": (
                phases.get("TERRAFORM_VALIDATION") or {}
            ).get("status"),
            "terraform_plan_status": tf_plan.get("status"),
        }
        # Carry the categorized resource counts from the plan when present.
        if isinstance(tf_plan.get("infrastructure_summary"), dict):
            summary["resources"] = tf_plan["infrastructure_summary"]
        return summary
