"""
TemplateArtifactValidator — detect unresolved template placeholders.

Any artifact that reaches the build executor MUST be fully rendered. This
validator rejects anything still containing:

  - {{ ... }}  (Jinja-style)
  - {% ... %}  (Jinja control blocks)
  - ${{ ... }} (GitHub Actions style)
  - <%= ... %> (ERB style)
  - <% ... %>  (ERB control blocks)

The validator is intentionally artifact-agnostic — it runs on Dockerfile,
docker-compose, .dockerignore, env files alike.

Issue type emitted to the gate: ``unresolved_template_variable``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Patterns ordered by specificity to avoid double-matching (e.g. ${{ before {{).
_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("github_actions_expression", re.compile(r"\$\{\{\s*([^{}\n]+?)\s*\}\}")),
    ("erb_expression",            re.compile(r"<%=\s*([^<>\n]+?)\s*%>")),
    ("erb_control",               re.compile(r"<%\s*([^<>\n]+?)\s*%>")),
    ("jinja_control",             re.compile(r"\{%\s*([^{}\n]+?)\s*%\}")),
    ("jinja_expression",          re.compile(r"\{\{\s*([^{}\n]+?)\s*\}\}")),
)


@dataclass
class TemplateIssue:
    artifact: str               # e.g. "dockerfile" or "docker_compose"
    token: str                  # raw token, e.g. "{{ healthcheck_retries }}"
    variable: str               # parsed variable name, e.g. "healthcheck_retries"
    line_number: int            # 1-based
    line: str                   # the offending source line
    pattern: str                # which pattern matched
    suggested_fix: str          # short remediation

    def message(self) -> str:
        return (
            f"Unresolved template variable '{self.token}' detected in "
            f"{self.artifact} (line {self.line_number}). Artifact rendering "
            "failed before execution."
        )

    def to_dict(self) -> dict:
        return {
            "artifact": self.artifact,
            "token": self.token,
            "variable": self.variable,
            "line_number": self.line_number,
            "line": self.line,
            "pattern": self.pattern,
            "message": self.message(),
            "suggested_fix": self.suggested_fix,
        }


# Stable, machine-readable reason code surfaced to the API / UI contract.
UNRESOLVED_TEMPLATE_TOKEN = "UNRESOLVED_TEMPLATE_TOKEN"


@dataclass
class TemplateValidationResult:
    valid: bool = True
    issues: List[TemplateIssue] = field(default_factory=list)

    @property
    def reason(self) -> Optional[str]:
        """Machine-readable failure code, or None when valid."""
        return None if self.valid else UNRESOLVED_TEMPLATE_TOKEN

    @property
    def affected_artifacts(self) -> List[str]:
        """Distinct artifacts carrying unresolved tokens (e.g. ["dockerfile"])."""
        return sorted({i.artifact for i in self.issues})

    def to_dict(self) -> dict:
        # ``reason`` + ``details`` form the structured contract consumed by the
        # PrebuildGate and the frontend; ``issue_count`` + ``issues`` are kept
        # for the richer diagnostics the corrector + debug panels already read.
        return {
            "valid": self.valid,
            "reason": self.reason,
            "details": self.affected_artifacts,
            "issue_count": len(self.issues),
            "issues": [i.to_dict() for i in self.issues],
        }


class TemplateArtifactValidator:
    """Rejects artifacts that still contain unresolved template placeholders."""

    def validate(
        self,
        artifacts: Dict[str, str],
    ) -> TemplateValidationResult:
        issues: List[TemplateIssue] = []
        for artifact_name, content in (artifacts or {}).items():
            if not content or not isinstance(content, str):
                continue
            issues.extend(self._scan(artifact_name, content))

        if issues:
            logger.warning(
                "[TemplateValidator] %d unresolved template token(s) detected — "
                "artifacts: %s",
                len(issues),
                sorted({i.artifact for i in issues}),
            )

        return TemplateValidationResult(valid=not issues, issues=issues)

    def validate_one(
        self,
        artifact_name: str,
        content: Optional[str],
    ) -> TemplateValidationResult:
        if not content:
            return TemplateValidationResult(valid=True)
        issues = self._scan(artifact_name, content)
        return TemplateValidationResult(valid=not issues, issues=issues)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _scan(self, artifact_name: str, content: str) -> List[TemplateIssue]:
        results: List[TemplateIssue] = []
        seen: set = set()  # dedupe identical token+line combos
        for line_no, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.rstrip()
            for pattern_name, regex in _PATTERNS:
                for m in regex.finditer(line):
                    token = m.group(0)
                    variable = m.group(1).strip()
                    key = (token, line_no)
                    if key in seen:
                        continue
                    seen.add(key)
                    results.append(TemplateIssue(
                        artifact=artifact_name,
                        token=token,
                        variable=variable,
                        line_number=line_no,
                        line=line,
                        pattern=pattern_name,
                        suggested_fix=(
                            f"Re-render the {artifact_name}: variable "
                            f"'{variable}' was not substituted. Either provide "
                            "a value during generation or rerun the artifact "
                            "generation phase."
                        ),
                    ))
        return results
