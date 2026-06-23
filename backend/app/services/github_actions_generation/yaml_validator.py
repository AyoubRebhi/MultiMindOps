"""YAML validation (Phase 5).

Runs BEFORE persistence: a workflow that is empty, not valid YAML, or structurally
not a GitHub Actions workflow is rejected so it never lands in the artifact store.

Note on the ``on:`` key: PyYAML (YAML 1.1) parses the bare word ``on`` as the
boolean ``True``, so a workflow's trigger block surfaces under the key ``True``
after ``safe_load``. The structural check accepts either ``"on"`` or ``True`` to
stay correct for idiomatic (unquoted) workflows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

# ── Pipeline-kind marker rules (Phase 4) ─────────────────────────────────────
# Markers are matched case-insensitively against the rendered text. They encode
# the bootstrap/deploy contract: provisioning belongs ONLY to bootstrap.yml.
_TERRAFORM_MARKERS: tuple[str, ...] = ("terraform init", "terraform apply")
_DELIVERY_MARKERS: tuple[str, ...] = ("docker build", "docker push")

# Target-specific deployment command a delivery workflow must contain.
_DEPLOY_COMMAND_BY_TARGET: Dict[str, tuple[str, ...]] = {
    "ecs": ("aws ecs update-service",),
    "eks": ("kubectl",),
    "lambda": ("aws lambda update-function-code",),
    "ec2": ("aws ssm send-command",),
}


@dataclass
class YamlValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    parsed: Dict[str, Any] | None = None

    @property
    def status(self) -> str:
        if not self.valid:
            return "failed"
        return "warnings" if self.warnings else "passed"


def validate_workflow_yaml(content: str) -> YamlValidationResult:
    """Validate a rendered GitHub Actions workflow.

    Rejects (``valid=False``):
      * empty / whitespace-only content,
      * content that is not parseable YAML,
      * YAML that does not parse to a mapping,
      * a workflow with no ``jobs`` mapping or no trigger (``on``) block,
      * a workflow whose jobs have no ``steps``.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not content or not content.strip():
        return YamlValidationResult(valid=False, errors=["Workflow file is empty."])

    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return YamlValidationResult(
            valid=False, errors=[f"Invalid YAML: {exc}"]
        )

    if not isinstance(parsed, dict):
        return YamlValidationResult(
            valid=False,
            errors=["Workflow must be a YAML mapping (got "
                    f"{type(parsed).__name__})."],
        )

    # Trigger block — 'on' parses to the boolean True under YAML 1.1.
    if "on" not in parsed and True not in parsed:
        errors.append("Workflow is missing the 'on' trigger block.")

    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        errors.append("Workflow is missing a non-empty 'jobs' mapping.")
    else:
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                errors.append(f"Job '{job_name}' is not a mapping.")
                continue
            steps = job.get("steps")
            if not isinstance(steps, list) or not steps:
                errors.append(f"Job '{job_name}' has no steps.")

    if not parsed.get("name"):
        warnings.append("Workflow has no top-level 'name'.")

    valid = not errors
    if not valid:
        logger.warning("[GitHubActions] YAML validation failed: %s", errors)
    return YamlValidationResult(
        valid=valid, errors=errors, warnings=warnings, parsed=parsed
    )


def validate_pipeline(
    content: str,
    *,
    kind: str,
    deployment_target: Optional[str] = None,
) -> YamlValidationResult:
    """Validate a rendered workflow for its pipeline ``kind`` (Phase 4).

    Layers kind-specific marker rules on top of the base structural validation:

    * ``bootstrap`` — MUST contain ``terraform init`` + ``terraform apply``
      (it is the one place infrastructure is provisioned).
    * ``deploy`` — MUST NOT contain any terraform step, and MUST contain
      ``docker build`` + ``docker push`` and the target's deployment command
      (e.g. ``aws ecs update-service`` / ``kubectl`` / ``aws lambda
      update-function-code`` / ``aws ssm send-command``).

    An unknown ``kind`` falls back to base structural validation only.
    """
    base = validate_workflow_yaml(content)
    lowered = (content or "").lower()
    errors: List[str] = list(base.errors)

    if kind == "bootstrap":
        for marker in _TERRAFORM_MARKERS:
            if marker not in lowered:
                errors.append(
                    f"bootstrap workflow is missing required step '{marker}'."
                )
    elif kind == "deploy":
        for marker in _TERRAFORM_MARKERS:
            if marker in lowered:
                errors.append(
                    f"deploy workflow must not contain '{marker}' — infrastructure "
                    "provisioning belongs to bootstrap.yml."
                )
        for marker in _DELIVERY_MARKERS:
            if marker not in lowered:
                errors.append(
                    f"deploy workflow is missing required step '{marker}'."
                )
        commands = _DEPLOY_COMMAND_BY_TARGET.get((deployment_target or "").lower())
        if commands is None:
            # Unknown target — accept any recognised deployment command.
            commands = tuple(
                cmd for cmds in _DEPLOY_COMMAND_BY_TARGET.values() for cmd in cmds
            )
        if not any(cmd in lowered for cmd in commands):
            errors.append(
                "deploy workflow is missing its deployment command "
                f"({' or '.join(commands)})."
            )

    valid = not errors
    if not valid:
        logger.warning(
            "[GitHubActions] pipeline validation failed (kind=%s target=%s): %s",
            kind, deployment_target, errors,
        )
    return YamlValidationResult(
        valid=valid, errors=errors, warnings=base.warnings, parsed=base.parsed
    )
