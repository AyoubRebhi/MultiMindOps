"""Blueprint data models — define the structural contract for artifact generation."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class BlueprintSection(BaseModel):
    """One ordered section of an artifact blueprint."""

    id: str
    required: bool = True
    description: str = ""
    template: str = ""
    required_variables: List[str] = Field(default_factory=list)
    optional_variables: List[str] = Field(default_factory=list)
    validation_hints: List[str] = Field(default_factory=list)
    security_rules: List[str] = Field(default_factory=list)
    rag_tags: List[str] = Field(default_factory=list)
    # When True: template has no placeholders — rendered directly, no LLM call needed.
    static: bool = False

    @property
    def all_variables(self) -> List[str]:
        return self.required_variables + self.optional_variables

    @property
    def has_variables(self) -> bool:
        return bool(self.required_variables or self.optional_variables)

    @property
    def needs_llm(self) -> bool:
        return self.has_variables and not self.static


class BlueprintMetadata(BaseModel):
    """Identification metadata for a blueprint."""

    framework: str = "generic"
    language: str = "generic"
    strategy: str = "single_stage"
    version: str = "v1"


class Blueprint(BaseModel):
    """
    A complete artifact blueprint.

    Defines the ordered sections that compose a generated artifact, along with
    per-section templates, variable contracts, and validation hints.
    """

    artifact_type: str
    metadata: BlueprintMetadata = Field(default_factory=BlueprintMetadata)
    sections: List[BlueprintSection] = Field(default_factory=list)

    @property
    def blueprint_id(self) -> str:
        m = self.metadata
        return f"{m.framework}_{m.strategy}_{m.version}"

    def get_section(self, section_id: str) -> Optional[BlueprintSection]:
        return next((s for s in self.sections if s.id == section_id), None)

    def required_sections(self) -> List[BlueprintSection]:
        return [s for s in self.sections if s.required]

    def dynamic_sections(self) -> List[BlueprintSection]:
        """Sections that require LLM variable generation."""
        return [s for s in self.sections if s.needs_llm]

    def static_sections(self) -> List[BlueprintSection]:
        """Sections rendered directly without LLM."""
        return [s for s in self.sections if not s.needs_llm]
