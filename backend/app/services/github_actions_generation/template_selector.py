"""Template selection (Phase 3).

Maps a deployment target to exactly one Jinja2 template. The choice is purely
mechanical and driven by the architecture decision (``DeploymentContext.
deployment_target``) — the CI/CD phase never asks the user and never guesses.
"""

from __future__ import annotations

from pathlib import Path

from backend.app.services.github_actions_generation.models import DeploymentTarget

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# deployment_target → template filename. One target, one template.
_TEMPLATE_BY_TARGET: dict[DeploymentTarget, str] = {
    "ecs": "ecs_deploy.yml.j2",
    "eks": "eks_deploy.yml.j2",
    "lambda": "lambda_deploy.yml.j2",
    "ec2": "ec2_deploy.yml.j2",
}


class TemplateSelectionError(Exception):
    """Raised when no template exists for a deployment target (packaging error)."""


def select_template(deployment_target: DeploymentTarget) -> str:
    """Return the template filename for ``deployment_target``.

    Raises :class:`TemplateSelectionError` for an unknown target (a packaging or
    enum-drift bug) rather than silently falling back to a wrong deployment.
    """
    filename = _TEMPLATE_BY_TARGET.get(deployment_target)
    if not filename:
        raise TemplateSelectionError(
            f"No GitHub Actions template for deployment_target='{deployment_target}'. "
            f"Known targets: {sorted(_TEMPLATE_BY_TARGET)}."
        )
    if not (TEMPLATES_DIR / filename).exists():
        raise TemplateSelectionError(
            f"Template '{filename}' for target '{deployment_target}' is missing "
            f"from {TEMPLATES_DIR}."
        )
    return filename
