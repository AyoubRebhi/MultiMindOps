"""
StructuredDockerfileGenerator — the main pipeline coordinator for Phase 1.

Pipeline:
  1. BlueprintSelector        — choose the best blueprint for the project
  2. SectionAwareRetriever    — retrieve RAG context per section (inside SectionGenerator)
  3. ArtifactSectionGenerator — one batched LLM call fills all section variables
  4. ArtifactAssembler        — render sections in order into the final Dockerfile
  5. DockerfileValidator       — section-mapped structural correctness check
  6. RuntimeSemanticValidator  — execution-aware: distro, exec-form, healthcheck deps
  7. SelfCritiqueLoop          — GPT reviews and auto-corrects before returning
  8. Return ArtifactGenerationResult (carries full provenance for CorrectorAgent)

Design principles:
  • The LLM never generates the full Dockerfile — only fills structured variable slots.
  • Every section has a deterministic fallback, guaranteeing an artifact on LLM failure.
  • All errors are section-mapped so the CorrectorAgent can target regeneration (Phase 2).
  • RuntimeSemanticValidator catches distro-mismatch issues before they reach CI.
  • SelfCritiqueLoop acts as the final quality gate — GPT reviews its own output.
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
from backend.app.services.artifact_generation.generators.self_critique_loop import SelfCritiqueLoop
from backend.app.services.artifact_generation.models.generation import ArtifactGenerationResult, SectionGenerationResult
from backend.app.services.artifact_generation.rag.section_retriever import SectionAwareRetriever
from backend.app.services.artifact_generation.validators.dockerfile_validator import DockerfileValidator
from backend.app.services.artifact_generation.validators.runtime_semantic_validator import (
    RuntimeSemanticValidator,
)
from backend.app.services.core.llm_service import LLMService
from backend.app.services.rag.rag_pipeline_service import RAGPipelineService

logger = logging.getLogger(__name__)


class StructuredDockerfileGenerator:
    """
    Generates Dockerfiles using blueprint-driven, section-level synthesis.

    This is the Phase 1 implementation of the Structured Constrained Generation
    System. It replaces free-form LLM generation with:

      Blueprint → Section Variables (LLM constrained) → Template Rendering → Assembly
        → Structural Validation → Runtime Semantic Validation → Self-Critique

    The generator is designed to be called from InfrastructureAgent as an
    alternative to the monolithic ReAct loop. It produces the same Dockerfile
    string but with significantly more structure, predictability, and observability.
    """

    def __init__(
        self,
        llm: LLMService,
        rag_pipeline: Optional[RAGPipelineService] = None,
        enable_self_critique: bool = True,
    ):
        loader = BlueprintLoader()
        retriever = SectionAwareRetriever(rag_pipeline)
        self._selector = BlueprintSelector(loader)
        self._generator = ArtifactSectionGenerator(llm, retriever)
        self._assembler = ArtifactAssembler()
        self._validator = DockerfileValidator()
        self._runtime_validator = RuntimeSemanticValidator()
        self._critique_loop: Optional[SelfCritiqueLoop] = (
            SelfCritiqueLoop(llm) if enable_self_critique else None
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        project_context: Dict[str, Any],
        corrector_feedback: Optional[Dict[str, Any]] = None,
    ) -> ArtifactGenerationResult:
        """
        Run the full structured Dockerfile generation pipeline.

        Args:
            project_context:   Output of InfrastructureContextAssembler.assemble().
                               Must contain 'main_service', 'runtime', etc.
                               May also carry 'compose_topology', 'build_context_report',
                               'runtime_mode', and 'topology_summary' from the assembler.
            corrector_feedback: Optional structured feedback from CorrectorAgent.
                               Shape: {
                                 "issues": ["global issue 1", ...],
                                 "section_errors": {
                                   "section_id": ["issue 1", ...]
                                 }
                               }

        Returns:
            ArtifactGenerationResult with:
              .artifact         — the final Dockerfile string (post self-critique)
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

        # ── Step 5: Structural validation ─────────────────────────────────────
        validation = self._validator.validate(
            content=artifact,
            blueprint=blueprint,
            section_results=section_results,
        )

        # ── Step 6: Runtime semantic validation (topology-aware) ─────────────
        compose_topology = project_context.get("compose_topology")
        build_context_report = project_context.get("build_context_report")
        runtime_result = self._runtime_validator.validate(
            artifact,
            compose_topology=compose_topology,
            build_context_report=build_context_report,
        )
        runtime_issues_added = 0

        if runtime_result.issues:
            runtime_issues_added = len(runtime_result.issues)
            logger.info(
                "[StructuredDockerfileGenerator] Runtime validation: %d errors, %d warnings",
                len(runtime_result.errors),
                len(runtime_result.warnings),
            )
            # Merge runtime errors into structural validation result
            for issue in runtime_result.errors:
                validation.errors.append(
                    _runtime_issue_to_section_issue(issue)
                )
            for issue in runtime_result.warnings:
                validation.warnings.append(
                    _runtime_issue_to_section_issue(issue)
                )
            # Recommendations for deprecated images
            for img in runtime_result.deprecated_images:
                validation.recommendations.append(
                    f"Deprecated image '{img}' — replace with a current equivalent."
                )
            # Re-evaluate validity after merging runtime errors
            if runtime_result.errors:
                validation.valid = False

        # ── Step 7: Self-critique + auto-correction ────────────────────────────
        self_critique_meta: Dict[str, Any] = {"enabled": False}
        if self._critique_loop is not None:
            critique_ctx = {
                "runtime_image": _extract_runtime_image(artifact),
                "distro_family": runtime_result.detected_family or "unknown",
                "framework": blueprint.metadata.framework,
                "language": blueprint.metadata.language,
            }
            try:
                critique = self._critique_loop.critique(artifact, critique_ctx)
                self_critique_meta = {
                    "enabled": True,
                    "llm_called": critique.llm_called,
                    "llm_success": critique.llm_success,
                    "issues_found": critique.issues_found,
                    "patches_applied": len(critique.patches_applied),
                }
                if critique.patches_applied:
                    artifact = critique.corrected_artifact
                    logger.info(
                        "[StructuredDockerfileGenerator] Self-critique applied %d patches",
                        len(critique.patches_applied),
                    )
                    # Re-validate the corrected artifact
                    validation = self._validator.validate(
                        content=artifact,
                        blueprint=blueprint,
                        section_results=section_results,
                    )
            except Exception as exc:
                logger.warning("[StructuredDockerfileGenerator] Self-critique failed: %s", exc)
                self_critique_meta = {"enabled": True, "error": str(exc)}

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
            "valid=%s chars=%d sections=%d fallbacks=%d rag_hits=%d "
            "runtime_issues=%d critique_patches=%d time=%.1fms",
            validation.valid,
            len(artifact),
            len(section_results),
            fallback_count,
            rag_hits,
            runtime_issues_added,
            self_critique_meta.get("patches_applied", 0),
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
                "runtime_validation": runtime_result.to_dict(),
                "self_critique": self_critique_meta,
                "topology_summary": project_context.get("topology_summary"),
                "runtime_mode": project_context.get("runtime_mode", "production"),
                "compose_topology_present": compose_topology is not None,
                "build_context_report_present": build_context_report is not None,
            },
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _runtime_issue_to_section_issue(issue: Any) -> Any:
    """Convert a RuntimeIssue to a SectionValidationIssue for merged reporting."""
    from backend.app.services.artifact_generation.models.validation import SectionValidationIssue
    return SectionValidationIssue(
        section_id=None,
        rule=issue.rule,
        message=f"{issue.message} — Fix: {issue.suggestion}",
        severity=issue.severity,
    )


def _extract_runtime_image(dockerfile: str) -> str:
    """Extract the last FROM image (runtime stage) from the assembled Dockerfile."""
    import re
    matches = re.findall(r"(?im)^FROM\s+(\S+?)(?:\s+AS\s+\S+)?$", dockerfile)
    return matches[-1] if matches else "unknown"


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
