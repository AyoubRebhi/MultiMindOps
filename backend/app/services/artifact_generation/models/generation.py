"""Generation result models — carry section-level provenance through the pipeline."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SectionGenerationResult(BaseModel):
    """Result of generating variables and rendering one blueprint section."""

    section_id: str
    blueprint_id: str
    variables: Dict[str, Any] = Field(default_factory=dict)
    rendered_content: str = ""
    rag_sources: List[str] = Field(default_factory=list)
    generation_time_ms: float = 0.0
    used_fallback: bool = False
    skipped: bool = False
    error: Optional[str] = None


class ArtifactGenerationResult(BaseModel):
    """
    Complete result of the structured artifact generation pipeline.

    Carries:
    - The final assembled artifact string
    - Per-section generation traces (for corrector feedback targeting)
    - Validation results with section-mapped errors
    - RAG retrieval provenance
    - Pipeline metadata (blueprint used, timing, fallback counts)
    """

    artifact_type: str = "dockerfile"
    blueprint_used: str = ""
    sections: Dict[str, SectionGenerationResult] = Field(default_factory=dict)
    validation: Dict[str, Any] = Field(default_factory=dict)
    artifact: str = ""
    rag_sources: List[Dict[str, Any]] = Field(default_factory=list)
    generation_metadata: Dict[str, Any] = Field(default_factory=dict)

    def is_successful(self) -> bool:
        return bool(self.artifact and not self.validation.get("errors"))

    def has_validation_errors(self) -> bool:
        return bool(self.validation.get("errors"))

    def fallback_section_count(self) -> int:
        return sum(1 for r in self.sections.values() if r.used_fallback)
