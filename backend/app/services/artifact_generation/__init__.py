"""
Structured Constrained Generation System — Phase 1.

Replaces free-form LLM artifact generation with:
  Blueprint-driven → Section-level synthesis → RAG slot-filling → Deterministic assembly

Primary entry point:
    from backend.app.services.artifact_generation import StructuredDockerfileGenerator
"""
from backend.app.services.artifact_generation.pipeline import StructuredDockerfileGenerator

__all__ = ["StructuredDockerfileGenerator"]
