"""Template selection (Phase 3).

Maps a deployment target to its Jinja2 templates. The choice is purely mechanical
and driven by the architecture decision (``DeploymentContext.deployment_target``)
— the CI/CD phase never asks the user and never guesses.

Each target ships TWO templates, one per pipeline kind:

* ``bootstrap`` — infrastructure provisioning + first deploy (``*_bootstrap.yml.j2``),
* ``deploy``    — continuous application delivery (``*_deploy.yml.j2``).

:func:`select_templates` returns the ``(bootstrap, deploy)`` pair for a target;
:func:`select_template` returns one named kind (defaults to ``deploy`` for
backward compatibility with callers that only know the single-file world).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Tuple

from backend.app.services.github_actions_generation.models import DeploymentTarget

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

PipelineKind = Literal["bootstrap", "deploy", "destroy"]

# deployment_target → {kind → template filename}. One target, one template per kind.
_TEMPLATES_BY_TARGET: dict[DeploymentTarget, dict[PipelineKind, str]] = {
    "ecs": {"bootstrap": "ecs_bootstrap.yml.j2", "deploy": "ecs_deploy.yml.j2"},
    "eks": {"bootstrap": "eks_bootstrap.yml.j2", "deploy": "eks_deploy.yml.j2"},
    "lambda": {"bootstrap": "lambda_bootstrap.yml.j2", "deploy": "lambda_deploy.yml.j2"},
    "ec2": {"bootstrap": "ec2_bootstrap.yml.j2", "deploy": "ec2_deploy.yml.j2"},
}

# The destroy pipeline is TARGET-AGNOSTIC: tearing down the Terraform state
# removes whatever was provisioned (ECS/EKS/Lambda/EC2), so a single template
# (``terraform init`` + ``terraform destroy``) serves every target.
DESTROY_TEMPLATE = "destroy.yml.j2"


class TemplateSelectionError(Exception):
    """Raised when no template exists for a deployment target (packaging error)."""


def select_template(
    deployment_target: DeploymentTarget, kind: PipelineKind = "deploy"
) -> str:
    """Return the template filename for ``deployment_target`` + pipeline ``kind``.

    Raises :class:`TemplateSelectionError` for an unknown target/kind (a packaging
    or enum-drift bug) rather than silently falling back to a wrong deployment.
    """
    # The destroy template is shared across every target (it only runs
    # ``terraform destroy``), so it is selected independently of the target.
    if kind == "destroy":
        if not (TEMPLATES_DIR / DESTROY_TEMPLATE).exists():
            raise TemplateSelectionError(
                f"Destroy template '{DESTROY_TEMPLATE}' is missing from {TEMPLATES_DIR}."
            )
        return DESTROY_TEMPLATE

    by_kind = _TEMPLATES_BY_TARGET.get(deployment_target)
    if not by_kind:
        raise TemplateSelectionError(
            f"No GitHub Actions templates for deployment_target='{deployment_target}'. "
            f"Known targets: {sorted(_TEMPLATES_BY_TARGET)}."
        )
    filename = by_kind.get(kind)
    if not filename:
        raise TemplateSelectionError(
            f"No '{kind}' template for deployment_target='{deployment_target}'. "
            f"Known kinds: {sorted(by_kind)}."
        )
    if not (TEMPLATES_DIR / filename).exists():
        raise TemplateSelectionError(
            f"Template '{filename}' for target '{deployment_target}' ({kind}) is "
            f"missing from {TEMPLATES_DIR}."
        )
    return filename


def select_templates(deployment_target: DeploymentTarget) -> Tuple[str, str]:
    """Return ``(bootstrap_template, deploy_template)`` for ``deployment_target``."""
    return (
        select_template(deployment_target, "bootstrap"),
        select_template(deployment_target, "deploy"),
    )
