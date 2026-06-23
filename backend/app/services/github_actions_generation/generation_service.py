"""GitHubActionsGenerationService — orchestrates the generation pipeline.

For EACH pipeline kind (bootstrap, deploy):

    deployment context → template selection → render → (optional enrich) → validate

Returns a typed :class:`GenerationResult` carrying BOTH files (the Infrastructure
``bootstrap.yml`` and the Delivery ``deploy.yml``); persistence + phase recording
live in ``WorkflowOrchestrationService`` (this service is pure generation, no DB
writes, no LLM-from-scratch, no infrastructure execution). Validation runs LAST
per file so an invalid workflow is surfaced to the caller and never persisted.

The split is the heart of the platform's DevOps model:

* ``bootstrap.yml`` provisions infrastructure (terraform init/apply) + first deploy
  and is triggered MANUALLY (``workflow_dispatch``) — run once.
* ``deploy.yml`` performs continuous delivery on every push and MUST NOT contain
  any terraform step — it assumes the infrastructure already exists.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.services.github_actions_generation.deployment_context_builder import (
    DeploymentContextBuilder,
)
from backend.app.services.github_actions_generation.github_actions_enrichment_service import (
    GitHubActionsEnrichmentService,
)
from backend.app.services.github_actions_generation.models import DeploymentContext
from backend.app.services.github_actions_generation.renderer import render_workflow
from backend.app.services.github_actions_generation.template_selector import PipelineKind
from backend.app.services.github_actions_generation.yaml_validator import (
    YamlValidationResult,
    validate_pipeline,
)

logger = logging.getLogger(__name__)

# Canonical on-disk paths (also used as the artifact subtypes). ``WORKFLOW_PATH``
# stays as a backward-compatible alias for the delivery workflow.
BOOTSTRAP_PATH = ".github/workflows/bootstrap.yml"
DEPLOY_PATH = ".github/workflows/deploy.yml"
WORKFLOW_PATH = DEPLOY_PATH

# Per-pipeline spec: (kind, human name, on-disk path, forbidden markers). The
# delivery pipeline forbids terraform steps — provisioning belongs to bootstrap.
_PIPELINE_SPECS: tuple[tuple[PipelineKind, str, str, tuple[str, ...]], ...] = (
    ("bootstrap", "Infrastructure Pipeline", BOOTSTRAP_PATH, ()),
    ("deploy", "Delivery Pipeline", DEPLOY_PATH, ("terraform init", "terraform apply")),
)


@dataclass
class PipelineFile:
    """One generated workflow file (bootstrap OR deploy) with its provenance."""

    name: str           # human label, e.g. "Infrastructure Pipeline"
    kind: PipelineKind  # "bootstrap" | "deploy"
    path: str           # ".github/workflows/bootstrap.yml" | ".../deploy.yml"
    template: str       # template filename used
    content: str        # rendered (and optionally enriched) YAML
    validation: YamlValidationResult
    enrichment_applied: bool = False
    enrichment_reason: str = "disabled"

    @property
    def valid(self) -> bool:
        return self.validation.valid


@dataclass
class GenerationResult:
    deployment_context: DeploymentContext
    bootstrap: PipelineFile
    deploy: PipelineFile
    logs: List[dict] = field(default_factory=list)

    @property
    def files(self) -> List[PipelineFile]:
        """Both generated files, bootstrap first."""
        return [self.bootstrap, self.deploy]

    @property
    def valid(self) -> bool:
        """True only when BOTH files validated (the phase-completion contract)."""
        return self.bootstrap.valid and self.deploy.valid


class GitHubActionsGenerationService:
    @staticmethod
    def generate(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
        enrich: Optional[bool] = None,
    ) -> GenerationResult:
        """Build context once, then render+enrich+validate BOTH pipeline files.

        Raises ``DeploymentContextNotReady`` / ``TemplateSelectionError`` /
        ``WorkflowRenderError`` for genuine pipeline failures. A file that renders
        but fails validation is returned with ``valid=False`` (the caller decides
        not to persist it) rather than raising.
        """
        logs: List[dict] = []

        # ── Phase 1: deployment context (target derived, not asked) ───────────
        context = DeploymentContextBuilder.build(
            db, project=project, workflow=workflow, task=task
        )
        logs.append({
            "step": "github_actions",
            "message": (
                f"Deployment target '{context.deployment_target}' resolved from "
                f"the architecture decision; consuming "
                f"{len(context.docker_artifacts)} Docker + "
                f"{len(context.terraform_artifacts)} Terraform artifacts."
            ),
        })

        # ── Render + enrich + validate each pipeline (template = source of truth)
        files = {
            kind: GitHubActionsGenerationService._build_pipeline(
                context,
                kind=kind,
                name=name,
                path=path,
                forbidden_markers=forbidden,
                enrich=enrich,
                logs=logs,
            )
            for kind, name, path, forbidden in _PIPELINE_SPECS
        }

        return GenerationResult(
            deployment_context=context,
            bootstrap=files["bootstrap"],
            deploy=files["deploy"],
            logs=logs,
        )

    @staticmethod
    def _build_pipeline(
        context: DeploymentContext,
        *,
        kind: PipelineKind,
        name: str,
        path: str,
        forbidden_markers: tuple[str, ...],
        enrich: Optional[bool],
        logs: List[dict],
    ) -> PipelineFile:
        """Render → optional GPT-5-mini enrichment → pipeline-aware validation."""
        # ── Phases 2-3: select template + render ──────────────────────────────
        template_filename, rendered = render_workflow(context, kind)
        logs.append({
            "step": "github_actions",
            "message": f"Rendered '{template_filename}' → {path}.",
        })

        # ── Optional enrichment (default OFF, fully guarded, never lossy) ──────
        enrichment = GitHubActionsEnrichmentService.enrich(
            rendered, context,
            enabled=enrich, logs=logs, forbidden_markers=forbidden_markers,
        )
        content = enrichment.content

        # ── Phase 5: pipeline-aware validation BEFORE persistence ─────────────
        validation = validate_pipeline(
            content, kind=kind, deployment_target=context.deployment_target
        )
        if validation.valid:
            logs.append({
                "step": "github_actions",
                "message": f"{name} ({path}) passed validation.",
            })
        else:
            logs.append({
                "step": "github_actions",
                "message": f"{name} ({path}) failed validation: "
                           + "; ".join(validation.errors),
            })
            logger.warning(
                "[GitHubActions] %s invalid (target=%s): %s",
                path, context.deployment_target, validation.errors,
            )

        return PipelineFile(
            name=name,
            kind=kind,
            path=path,
            template=template_filename,
            content=content,
            validation=validation,
            enrichment_applied=enrichment.applied,
            enrichment_reason=enrichment.reason,
        )
