"""
StructuredDockerfileGenerator — the main pipeline coordinator for Phase 1.

Pipeline:
  1. BlueprintSelector   — choose the best blueprint for the project
  2. SectionAwareRetriever — retrieve RAG context per section (inside SectionGenerator)
  3. ArtifactSectionGenerator — one batched LLM call fills all section variables
  4. ArtifactAssembler  — render sections in order into the final Dockerfile
  5. DockerfileValidator — section-mapped correctness and security check
  6. Return ArtifactGenerationResult (carries full provenance for CorrectorAgent)

Design principles:
  • The LLM never generates the full Dockerfile — only fills structured variable slots.
  • Every section has a deterministic fallback, guaranteeing an artifact on LLM failure.
  • All errors are section-mapped so the CorrectorAgent can target regeneration (Phase 2).
  • The pipeline is additive to InfrastructureAgent — backward compatibility is preserved.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from backend.app.services.artifact_generation.assemblers.artifact_assembler import ArtifactAssembler
from backend.app.services.artifact_generation.blueprints.loader import BlueprintLoader
from backend.app.services.artifact_generation.blueprints.selector import BlueprintSelector
from backend.app.services.artifact_generation.generators.section_generator import ArtifactSectionGenerator
from backend.app.services.artifact_generation.models.generation import ArtifactGenerationResult, SectionGenerationResult
from backend.app.services.artifact_generation.rag.section_retriever import SectionAwareRetriever
from backend.app.services.artifact_generation.validators.dockerfile_validator import DockerfileValidator
from backend.app.services.core.llm_service import LLMService
from backend.app.services.rag.rag_pipeline_service import RAGPipelineService

logger = logging.getLogger(__name__)


class StructuredDockerfileGenerator:
    """
    Generates Dockerfiles using blueprint-driven, section-level synthesis.

    This is the Phase 1 implementation of the Structured Constrained Generation
    System. It replaces free-form LLM generation with:

      Blueprint → Section Variables (LLM constrained) → Template Rendering → Assembly

    The generator is designed to be called from InfrastructureAgent as an
    alternative to the monolithic ReAct loop. It produces the same Dockerfile
    string but with significantly more structure, predictability, and observability.
    """

    def __init__(
        self,
        llm: LLMService,
        rag_pipeline: Optional[RAGPipelineService] = None,
    ):
        loader = BlueprintLoader()
        retriever = SectionAwareRetriever(rag_pipeline)
        self._selector = BlueprintSelector(loader)
        self._generator = ArtifactSectionGenerator(llm, retriever)
        self._assembler = ArtifactAssembler()
        self._validator = DockerfileValidator()

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        project_context: Dict[str, Any],
        corrector_feedback: Optional[Dict[str, Any]] = None,
    ) -> ArtifactGenerationResult:
        """
        Run the full structured Dockerfile generation pipeline.

        Args:
            project_context:   Output of InfrastructureContextMapper.map().
                               Must contain 'main_service', 'runtime', etc.
            corrector_feedback: Optional structured feedback from CorrectorAgent.
                               Shape: {
                                 "issues": ["global issue 1", ...],
                                 "section_errors": {
                                   "section_id": ["issue 1", ...]
                                 }
                               }

        Returns:
            ArtifactGenerationResult with:
              .artifact         — the final Dockerfile string
              .blueprint_used   — blueprint ID for traceability
              .sections         — per-section generation traces
              .validation       — section-mapped validation result
              .rag_sources      — RAG provenance per section
              .generation_metadata — timing, fallback counts, observability
        """
        pipeline_start = time.monotonic()

        # ── Step 1: Select blueprint ──────────────────────────────────────────
        try:
            blueprint = self._selector.select(project_context)
        except Exception as exc:
            logger.error("[StructuredDockerfileGenerator] Blueprint selection failed: %s", exc)
            return _error_result(f"Blueprint selection failed: {exc}")

        logger.info(
            "[StructuredDockerfileGenerator] Blueprint selected: %s "
            "(framework=%s language=%s sections=%d)",
            blueprint.blueprint_id,
            blueprint.metadata.framework,
            blueprint.metadata.language,
            len(blueprint.sections),
        )

        # ── Step 2 + 3: Section generation (RAG + LLM batch) ─────────────────
        gen_start = time.monotonic()
        section_results: Dict[str, SectionGenerationResult] = (
            self._generator.generate_all_sections(
                blueprint=blueprint,
                project_context=project_context,
                corrector_feedback=corrector_feedback,
            )
        )
        gen_ms = round((time.monotonic() - gen_start) * 1000, 2)

        # ── Step 4: Assemble ──────────────────────────────────────────────────
        artifact = self._assembler.assemble(blueprint, section_results)

        # ── Step 5: Validate ──────────────────────────────────────────────────
        validation = self._validator.validate(
            content=artifact,
            blueprint=blueprint,
            section_results=section_results,
        )

        # ── Build result ──────────────────────────────────────────────────────
        total_ms = round((time.monotonic() - pipeline_start) * 1000, 2)
        fallback_count = sum(1 for r in section_results.values() if r.used_fallback)
        rag_hits = sum(1 for r in section_results.values() if r.rag_sources)

        rag_sources: List[Dict[str, Any]] = [
            {"section_id": r.section_id, "source": src}
            for r in section_results.values()
            for src in r.rag_sources
        ]

        logger.info(
            "[StructuredDockerfileGenerator] Pipeline complete — "
            "valid=%s chars=%d sections=%d fallbacks=%d rag_hits=%d time=%.1fms",
            validation.valid,
            len(artifact),
            len(section_results),
            fallback_count,
            rag_hits,
            total_ms,
        )

        return ArtifactGenerationResult(
            artifact_type="dockerfile",
            blueprint_used=blueprint.blueprint_id,
            sections=section_results,
            validation=validation.to_dict(),
            artifact=artifact,
            rag_sources=rag_sources,
            generation_metadata={
                "blueprint_id": blueprint.blueprint_id,
                "framework": blueprint.metadata.framework,
                "language": blueprint.metadata.language,
                "strategy": blueprint.metadata.strategy,
                "total_sections": len(blueprint.sections),
                "static_sections": len(blueprint.static_sections()),
                "dynamic_sections": len(blueprint.dynamic_sections()),
                "generated_sections": len(section_results),
                "fallback_sections": fallback_count,
                "rag_hits": rag_hits,
                "generation_time_ms": gen_ms,
                "total_time_ms": total_ms,
                "corrector_feedback_applied": corrector_feedback is not None,
            },
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _error_result(message: str) -> ArtifactGenerationResult:
    return ArtifactGenerationResult(
        artifact_type="dockerfile",
        blueprint_used="none",
        artifact="",
        validation={
            "valid": False,
            "errors": [{"section_id": None, "rule": "pipeline_error", "message": message, "severity": "error"}],
            "warnings": [],
            "recommendations": [],
        },
        generation_metadata={"error": message},
    )
