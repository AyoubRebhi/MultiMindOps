"""
ArtifactAssembler — combines blueprint section results into a final artifact string.

Responsibilities:
  • Assembles sections in blueprint-defined order.
  • Skips optional sections with empty content.
  • Preserves clean formatting (single blank lines between sections).
  • Detects unfilled template placeholders in required sections.
  • Supports future patch-replacement (section-level regeneration).

This class is intentionally deterministic — no LLM, no randomness.
Given the same section results it always produces the same artifact.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from backend.app.services.artifact_generation.models.blueprint import Blueprint, BlueprintSection
from backend.app.services.artifact_generation.models.generation import SectionGenerationResult

logger = logging.getLogger(__name__)


class ArtifactAssembler:
    """
    Assembles blueprint section results into the final artifact content.

    Usage:
        assembler = ArtifactAssembler()
        dockerfile = assembler.assemble(blueprint, section_results)
    """

    def assemble(
        self,
        blueprint: Blueprint,
        section_results: Dict[str, SectionGenerationResult],
    ) -> str:
        """
        Concatenate rendered section content in blueprint-defined order.

        Args:
            blueprint:       The blueprint that guided generation.
            section_results: Map of section_id → SectionGenerationResult.

        Returns:
            The assembled artifact as a single string, ready for use.
        """
        parts: List[str] = []
        missing_required: List[str] = []
        unfilled_vars: List[str] = []

        for section in blueprint.sections:
            result = section_results.get(section.id)

            if result is None:
                if section.required:
                    missing_required.append(section.id)
                    logger.warning(
                        "[ArtifactAssembler] Required section '%s' has no result",
                        section.id,
                    )
                else:
                    logger.debug(
                        "[ArtifactAssembler] Optional section '%s' skipped (no result)",
                        section.id,
                    )
                continue

            if result.skipped:
                logger.debug(
                    "[ArtifactAssembler] Section '%s' explicitly skipped", section.id
                )
                continue

            content = result.rendered_content.strip()
            if not content:
                if section.required:
                    missing_required.append(section.id)
                    logger.warning(
                        "[ArtifactAssembler] Required section '%s' rendered empty",
                        section.id,
                    )
                continue

            # Detect unfilled placeholders in required sections
            if section.required:
                unfilled = re.findall(r"\{\{\s*\w+\s*\}\}", content)
                for placeholder in unfilled:
                    unfilled_vars.append(f"{section.id}:{placeholder}")

            parts.append(content)

        if missing_required:
            logger.error(
                "[ArtifactAssembler] Missing required sections: %s",
                ", ".join(missing_required),
            )
        if unfilled_vars:
            logger.warning(
                "[ArtifactAssembler] Unfilled placeholders: %s",
                ", ".join(unfilled_vars),
            )

        artifact = "\n\n".join(parts)
        # Normalise: collapse triple+ blank lines to double
        artifact = re.sub(r"\n{3,}", "\n\n", artifact)
        # Ensure single trailing newline
        artifact = artifact.rstrip("\n") + "\n"

        logger.info(
            "[ArtifactAssembler] Assembled %d/%d sections — %d chars "
            "(missing_required=%d unfilled=%d)",
            len(parts),
            len(blueprint.sections),
            len(artifact),
            len(missing_required),
            len(unfilled_vars),
        )

        return artifact

    def patch_section(
        self,
        current_artifact: str,
        section: BlueprintSection,
        new_result: SectionGenerationResult,
    ) -> str:
        """
        Replace a single section's content in an already-assembled artifact.

        This is the foundation for section-level regeneration (Phase 2).
        Currently it performs a best-effort replacement by locating the first
        instruction of the old section's content.

        Args:
            current_artifact: The full artifact string to patch.
            section:          The blueprint section being replaced.
            new_result:       The regenerated section result.

        Returns:
            Patched artifact string, or the original if the section was not found.
        """
        old_content = new_result.rendered_content.strip()
        if not old_content:
            logger.warning(
                "[ArtifactAssembler] Patch for section '%s' has empty content — skipping",
                section.id,
            )
            return current_artifact

        # Extract the first meaningful line of the new content as an anchor
        first_line = old_content.splitlines()[0].strip()
        if not first_line or first_line.startswith("#"):
            return current_artifact

        # Future: implement block-level replacement using section markers
        # For now, return current artifact (section regeneration is Phase 2)
        logger.debug(
            "[ArtifactAssembler] patch_section('%s') — placeholder for Phase 2",
            section.id,
        )
        return current_artifact

    def validate_assembly(
        self,
        blueprint: Blueprint,
        section_results: Dict[str, SectionGenerationResult],
    ) -> List[str]:
        """
        Return a list of assembly issues (missing sections, unfilled vars).

        Does NOT assemble — use assemble() for that. This is a pre-flight check.
        """
        issues: List[str] = []
        for section in blueprint.required_sections():
            result = section_results.get(section.id)
            if not result or not result.rendered_content.strip():
                issues.append(f"Required section '{section.id}' is missing or empty")
                continue
            unfilled = re.findall(r"\{\{\s*(\w+)\s*\}\}", result.rendered_content)
            for var in unfilled:
                if var in section.required_variables:
                    issues.append(
                        f"Section '{section.id}': required variable '{{{{ {var} }}}}' not filled"
                    )
        return issues
