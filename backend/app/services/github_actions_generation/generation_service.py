"""GitHubActionsGenerationService — orchestrates the generation pipeline.

    deployment context → template selection → render → (optional enrich) → validate

Returns a typed :class:`GenerationResult`; persistence + phase recording live in
``WorkflowOrchestrationService`` (this service is pure generation, no DB writes,
no LLM-from-scratch, no infrastructure execution). Validation runs LAST so an
invalid workflow is surfaced to the caller and never persisted.
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
from backend.app.services.github_actions_generation.enrichment import enrich_workflow
from backend.app.services.github_actions_generation.models import DeploymentContext
from backend.app.services.github_actions_generation.renderer import render_workflow
from backend.app.services.github_actions_generation.yaml_validator import (
    YamlValidationResult,
    validate_workflow_yaml,
)

logger = logging.getLogger(__name__)

# Canonical on-disk path for the generated workflow + its artifact subtype.
WORKFLOW_PATH = ".github/workflows/deploy.yml"


@dataclass
class GenerationResult:
    deployment_context: DeploymentContext
    template: str
    content: str
    validation: YamlValidationResult
    enrichment_applied: bool = False
    enrichment_reason: str = "disabled"
    logs: List[dict] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.validation.valid

    @property
    def workflow_path(self) -> str:
        return WORKFLOW_PATH


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
        """Build context, render, optionally enrich, then validate.

        Raises ``DeploymentContextNotReady`` / ``TemplateSelectionError`` /
        ``WorkflowRenderError`` for genuine pipeline failures. A workflow that
        renders but fails YAML validation is returned with ``valid=False`` (the
        caller decides not to persist it) rather than raising.
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

        # ── Phases 2-3: select template + render (template = source of truth) ──
        template_filename, rendered = render_workflow(context)
        logs.append({
            "step": "github_actions",
            "message": f"Rendered '{template_filename}' → {WORKFLOW_PATH}.",
        })

        # ── Optional: lightweight LLM enrichment (default OFF, fully guarded) ──
        enrichment = enrich_workflow(rendered, context, enabled=enrich)
        content = enrichment.content
        if enrichment.applied:
            logs.append({
                "step": "github_actions",
                "message": "Applied optional LLM enrichment (jobs preserved).",
            })
        elif enrichment.reason not in ("disabled",):
            logs.append({
                "step": "github_actions",
                "message": (
                    f"Skipped LLM enrichment ({enrichment.reason}); kept the "
                    "deterministic template output."
                ),
            })

        # ── Phase 5: YAML validation BEFORE persistence ───────────────────────
        validation = validate_workflow_yaml(content)
        if not validation.valid:
            logs.append({
                "step": "github_actions",
                "message": "Generated workflow failed YAML validation: "
                           + "; ".join(validation.errors),
            })
            logger.warning(
                "[GitHubActions] generated workflow invalid for project=%s: %s",
                project.id, validation.errors,
            )
        else:
            logs.append({
                "step": "github_actions",
                "message": "Generated workflow passed YAML validation.",
            })

        return GenerationResult(
            deployment_context=context,
            template=template_filename,
            content=content,
            validation=validation,
            enrichment_applied=enrichment.applied,
            enrichment_reason=enrichment.reason,
            logs=logs,
        )
