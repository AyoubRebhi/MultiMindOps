"""
Typed validation result models.

Used by ``TerraformValidator`` and surfaced through ``TerraformValidationError``
so the orchestrator and frontend can route on machine-readable severity rather
than parsing stderr strings.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ValidationSeverity = Literal["info", "warning", "error", "critical"]
ValidationStatus = Literal["passed", "warnings", "failed", "skipped"]
ValidatorName = Literal[
    "backend_config",
    "hcl2_parse",
    "terraform_fmt",
    "terraform_init",
    "terraform_validate",
    "tfsec",
    "checkov",
]


class TerraformValidationIssue(BaseModel):
    """A single problem reported by one of the syntactic/semantic validators."""

    model_config = ConfigDict(extra="forbid")

    severity: ValidationSeverity
    source: ValidatorName
    file: Optional[str] = None
    line: Optional[int] = None
    message: str
    remediation: Optional[str] = None


class TerraformSecurityIssue(BaseModel):
    """
    Security finding from tfsec / checkov. Carries the rule identifier so it
    can be suppressed by ID later, plus a remediation hint when the scanner
    provides one.
    """

    model_config = ConfigDict(extra="forbid")

    severity: ValidationSeverity
    source: Literal["tfsec", "checkov"]
    rule_id: str
    file: Optional[str] = None
    line: Optional[int] = None
    message: str
    remediation: Optional[str] = None
    resource: Optional[str] = None


class TerraformValidationResult(BaseModel):
    """
    Aggregated outcome of running the full pipeline against a rendered set
    of .tf files. ``status`` is the gate the orchestrator uses to decide
    whether to advance to the user-review step.
    """

    model_config = ConfigDict(extra="forbid")

    status: ValidationStatus
    issues: List[TerraformValidationIssue] = Field(default_factory=list)
    security_issues: List[TerraformSecurityIssue] = Field(default_factory=list)
    # Per-validator status map — useful for the UI to render "tfsec skipped"
    # vs "tfsec passed" vs "tfsec found 3 issues" distinctly.
    validators_run: Dict[ValidatorName, ValidationStatus] = Field(default_factory=dict)
    skipped_validators: List[ValidatorName] = Field(default_factory=list)
    duration_ms: int = 0

    @property
    def is_blocking(self) -> bool:
        """
        ``True`` when validation must stop the pipeline. Critical/error severity
        from any validator blocks; warnings do not.
        """
        if self.status == "failed":
            return True
        blocking = {"error", "critical"}
        return any(i.severity in blocking for i in self.issues) or any(
            s.severity in blocking for s in self.security_issues
        )

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity in ("error", "critical"))

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def security_critical_count(self) -> int:
        return sum(
            1 for s in self.security_issues if s.severity in ("error", "critical")
        )
