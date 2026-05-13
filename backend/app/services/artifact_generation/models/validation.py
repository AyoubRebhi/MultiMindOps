"""Section-aware validation models for Dockerfile correctness checking."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class SectionValidationIssue(BaseModel):
    """A validation error or warning mapped to a specific blueprint section."""

    section_id: Optional[str] = None
    rule: str
    message: str
    severity: str = "error"  # "error" | "warning" | "recommendation"


class DockerfileValidationResult(BaseModel):
    """
    Result of section-aware Dockerfile validation.

    Errors and warnings are mapped to their originating blueprint section,
    enabling the CorrectorAgent to target section-level regeneration.
    """

    valid: bool
    errors: List[SectionValidationIssue] = []
    warnings: List[SectionValidationIssue] = []
    recommendations: List[str] = []

    @property
    def error_messages(self) -> List[str]:
        return [e.message for e in self.errors]

    @property
    def warning_messages(self) -> List[str]:
        return [w.message for w in self.warnings]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [e.model_dump() for e in self.errors],
            "warnings": [w.model_dump() for w in self.warnings],
            "recommendations": self.recommendations,
        }
