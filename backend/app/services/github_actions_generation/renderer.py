"""Jinja2 renderer for GitHub Actions deployment workflows.

Mirrors the deterministic ``TerraformTemplateRenderer`` pattern (FileSystemLoader
+ StrictUndefined so an undeclared variable raises, never renders blank) with ONE
critical difference: GitHub Actions expressions use ``${{ ... }}``, which collides
with Jinja's default ``{{ ... }}`` delimiters. We therefore configure CUSTOM
delimiters so the template author writes ``<< var >>`` for generation-time
substitution and every ``${{ secrets.* }}`` / ``${{ steps.* }}`` passes through to
the rendered YAML untouched.

The renderer is the SOURCE OF TRUTH for the workflow: it performs no LLM calls and
no defaulting (all defaulting happens in DeploymentContextBuilder), so a reviewer
can audit exactly what each target deploys by reading its template.
"""

from __future__ import annotations

import logging

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError

from backend.app.services.github_actions_generation.models import DeploymentContext
from backend.app.services.github_actions_generation.template_selector import (
    TEMPLATES_DIR,
    select_template,
)

logger = logging.getLogger(__name__)


class WorkflowRenderError(Exception):
    """Raised when the selected template cannot be rendered (syntax / missing var)."""


def _build_environment() -> Environment:
    """Jinja2 environment with GitHub-Actions-safe delimiters.

    ``<< >>`` for variables, ``<% %>`` for blocks, ``<# #>`` for comments — chosen
    so the literal ``${{ }}`` GitHub expression syntax is never interpreted.
    ``StrictUndefined`` turns any undeclared ``<< var >>`` into a hard error.
    """
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )


def render_workflow(context: DeploymentContext) -> tuple[str, str]:
    """Render the deploy workflow for ``context``.

    Returns ``(template_filename, rendered_yaml)``. Raises
    :class:`WorkflowRenderError` on a template syntax error or an undeclared
    variable (StrictUndefined) — both indicate template/context drift that must
    fail loudly rather than emit a half-blank workflow.
    """
    template_filename = select_template(context.deployment_target)
    env = _build_environment()
    try:
        template = env.get_template(template_filename)
        rendered = template.render(**context.render_variables())
    except TemplateError as exc:
        raise WorkflowRenderError(
            f"Failed to render '{template_filename}' for target "
            f"'{context.deployment_target}': {exc}"
        ) from exc

    logger.info(
        "[GitHubActions] rendered template=%s target=%s bytes=%d",
        template_filename, context.deployment_target, len(rendered),
    )
    return template_filename, rendered
