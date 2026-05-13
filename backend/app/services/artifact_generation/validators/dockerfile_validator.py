"""
DockerfileValidator — section-aware Dockerfile correctness and security checker.

Unlike the generic ValidationService.validate_dockerfile(), this validator:
  • Maps each finding to the blueprint section that produced it.
  • Returns structured SectionValidationIssue objects (with section_id).
  • Enables the CorrectorAgent to target per-section regeneration (Phase 2).
  • Provides actionable recommendations beyond pass/fail.

Validation rules:
  Errors (blocking):
    from_missing           — no FROM instruction
    workdir_missing        — no WORKDIR instruction
    startup_missing        — no CMD or ENTRYPOINT
    hardcoded_credentials  — password/secret in ENV/ARG

  Warnings (non-blocking, best-practice):
    latest_tag             — :latest tag used
    root_user              — running as root (no USER)
    duplicate_user         — more than two USER directives
    invalid_expose         — non-numeric EXPOSE value
    no_copy                — no COPY instruction

  Recommendations (advisory):
    no_healthcheck         — suggest HEALTHCHECK
    no_labels              — suggest OCI labels
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from backend.app.services.artifact_generation.models.blueprint import Blueprint
from backend.app.services.artifact_generation.models.generation import SectionGenerationResult
from backend.app.services.artifact_generation.models.validation import (
    DockerfileValidationResult,
    SectionValidationIssue,
)

logger = logging.getLogger(__name__)

# Maps rule name → likely blueprint section ID for error attribution
_RULE_SECTION_HINT: Dict[str, str] = {
    "from_missing": "base_image",
    "workdir_missing": "workdir",
    "startup_missing": "startup",
    "hardcoded_credentials": "environment",
    "latest_tag": "base_image",
    "root_user": "user",
    "duplicate_user": "user",
    "invalid_expose": "expose",
    "no_copy": "copy_source",
}

# Credential pattern — catches ENV/ARG with literal values
_CRED_PATTERN = re.compile(
    r"(?i)(PASSWORD|SECRET|API_KEY|TOKEN|PRIVATE_KEY)\s*=\s*(?!\$)[^\s\\]+",
    re.MULTILINE,
)


class DockerfileValidator:
    """
    Section-aware Dockerfile validator.

    Validates assembled Dockerfiles and attributes each finding to the
    blueprint section responsible for it — enabling targeted correction.
    """

    def validate(
        self,
        content: str,
        blueprint: Optional[Blueprint] = None,
        section_results: Optional[Dict[str, SectionGenerationResult]] = None,
    ) -> DockerfileValidationResult:
        """
        Validate a Dockerfile with section-level error attribution.

        Args:
            content:         Assembled Dockerfile string.
            blueprint:       Blueprint used during generation (for section mapping).
            section_results: Per-section results (reserved for future fine-grained mapping).

        Returns:
            DockerfileValidationResult with mapped errors, warnings, and recommendations.
        """
        errors: List[SectionValidationIssue] = []
        warnings: List[SectionValidationIssue] = []
        recommendations: List[str] = []

        if not content or not content.strip():
            errors.append(SectionValidationIssue(
                section_id=None,
                rule="content_empty",
                message="Dockerfile is empty",
                severity="error",
            ))
            return DockerfileValidationResult(valid=False, errors=errors)

        lines = content.strip().splitlines()

        # ── Blocking errors ───────────────────────────────────────────────────

        # Rule: FROM must be the first non-comment instruction
        first_instruction = next(
            (ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")),
            "",
        )
        if not re.match(r"(?i)^FROM\s+", first_instruction):
            errors.append(self._issue(
                "from_missing",
                "Dockerfile must start with a FROM instruction",
                blueprint,
            ))

        # Rule: WORKDIR must be present
        if not re.search(r"(?im)^WORKDIR\s+\S", content):
            errors.append(self._issue(
                "workdir_missing",
                "WORKDIR instruction is missing — set an explicit working directory",
                blueprint,
            ))

        # Rule: CMD or ENTRYPOINT must exist
        if not re.search(r"(?im)^(CMD|ENTRYPOINT)\s+", content):
            errors.append(self._issue(
                "startup_missing",
                "No CMD or ENTRYPOINT instruction — container has no startup command",
                blueprint,
            ))

        # Rule: No hardcoded credentials
        if _CRED_PATTERN.search(content):
            errors.append(self._issue(
                "hardcoded_credentials",
                "Potential hardcoded credential detected — use runtime secrets or environment injection",
                blueprint,
                override_severity="error",
            ))

        # ── Warnings ──────────────────────────────────────────────────────────

        # Rule: :latest tag
        if re.search(r"(?i)\bFROM\s+\S+:latest\b", content):
            warnings.append(self._issue(
                "latest_tag",
                "Using ':latest' image tag — pin to a specific version for reproducibility",
                blueprint,
                override_severity="warning",
            ))

        # Rule: Running as root (no USER instruction)
        if not re.search(r"(?im)^USER\s+\S", content):
            warnings.append(self._issue(
                "root_user",
                "No USER instruction — container runs as root (security risk)",
                blueprint,
                override_severity="warning",
            ))

        # Rule: Duplicate USER directives (more than 2 is suspicious)
        user_count = len(re.findall(r"(?im)^USER\s+", content))
        if user_count > 2:
            warnings.append(self._issue(
                "duplicate_user",
                f"Multiple USER instructions ({user_count}) — verify this is intentional",
                blueprint,
                override_severity="warning",
            ))

        # Rule: Invalid EXPOSE port
        for port_str in re.findall(r"(?im)^EXPOSE\s+(\S+)", content):
            if not re.match(r"^\d{1,5}(/tcp|/udp)?$", port_str.strip()):
                warnings.append(self._issue(
                    "invalid_expose",
                    f"EXPOSE has non-numeric port value: '{port_str}'",
                    blueprint,
                    override_severity="warning",
                ))

        # Rule: No COPY instruction at all
        if not re.search(r"(?im)^COPY\s+", content):
            warnings.append(self._issue(
                "no_copy",
                "No COPY instruction found — source code may not be included",
                blueprint,
                override_severity="warning",
            ))

        # ── Recommendations ───────────────────────────────────────────────────

        if not re.search(r"(?im)^HEALTHCHECK\s+", content):
            recommendations.append(
                "Add a HEALTHCHECK instruction for container orchestration health monitoring"
            )

        if not re.search(r"(?im)^LABEL\s+", content):
            recommendations.append(
                "Add OCI image labels (org.opencontainers.image.*) for metadata and governance"
            )

        valid = not errors

        logger.info(
            "[DockerfileValidator] valid=%s errors=%d warnings=%d recommendations=%d",
            valid, len(errors), len(warnings), len(recommendations),
        )

        return DockerfileValidationResult(
            valid=valid,
            errors=errors,
            warnings=warnings,
            recommendations=recommendations,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _issue(
        rule: str,
        message: str,
        blueprint: Optional[Blueprint],
        override_severity: Optional[str] = None,
    ) -> SectionValidationIssue:
        section_id = _resolve_section(rule, blueprint)
        severity = override_severity or ("error" if rule in _BLOCKING_RULES else "warning")
        return SectionValidationIssue(
            section_id=section_id,
            rule=rule,
            message=message,
            severity=severity,
        )


_BLOCKING_RULES = {
    "from_missing",
    "workdir_missing",
    "startup_missing",
    "hardcoded_credentials",
    "content_empty",
}


def _resolve_section(rule: str, blueprint: Optional[Blueprint]) -> Optional[str]:
    """Find the blueprint section ID most likely responsible for a rule violation."""
    hint = _RULE_SECTION_HINT.get(rule)
    if not hint or not blueprint:
        return hint

    # Direct ID match
    if blueprint.get_section(hint):
        return hint

    # Partial match (e.g. "base_image" hint → "builder_base" or "runtime_base" section)
    for section in blueprint.sections:
        if hint in section.id or section.id in hint:
            return section.id

    return hint
