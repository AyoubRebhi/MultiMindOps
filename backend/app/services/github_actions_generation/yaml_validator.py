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
from typing import Any, Dict, List

import yaml

logger = logging.getLogger(__name__)


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
