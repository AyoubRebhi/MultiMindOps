"""
SelfCritiqueLoop — GPT-powered Dockerfile self-review and auto-correction.

After structured generation + assembly, this loop calls GPT-5.4-mini to act
as a senior DevOps architect and review the generated Dockerfile. If it finds
issues, it emits structured patches that are applied deterministically before
the artifact is returned to the caller.

Design:
  • LLM is constrained to a strict JSON schema — no free-form output.
  • Only applies patches it is confident about (confidence ≥ 0.80).
  • Falls back gracefully: if the LLM call fails or returns nothing useful,
    the original artifact is returned unchanged.
  • Never introduces new lines — only replaces existing ones.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Critique schema ───────────────────────────────────────────────────────────

@dataclass
class CritiquePatch:
    """One targeted line-level fix."""
    target_line: str      # Exact line to replace (or prepend_before)
    replacement: str      # Replacement text (may be empty to delete)
    reason: str
    confidence: float
    operation: str = "replace"   # "replace" | "prepend_before" | "append_after" | "delete"


@dataclass
class CritiqueResult:
    patches_applied: List[CritiquePatch] = field(default_factory=list)
    issues_found: List[str] = field(default_factory=list)
    corrected_artifact: str = ""
    llm_called: bool = False
    llm_success: bool = False


# ── System prompt ─────────────────────────────────────────────────────────────

_CRITIQUE_SYSTEM = """\
You are a senior DevOps architect and Docker expert reviewing a generated Dockerfile.
Your task: find execution-breaking issues and return structured patches.

ONLY flag issues that will cause a BUILD FAILURE or RUNTIME FAILURE:
  1. Invalid JSON exec form (single quotes in ENTRYPOINT/CMD arrays)
  2. Alpine commands (addgroup -S, adduser -S) on Debian images
  3. Debian commands (groupadd, useradd) on Alpine images
  4. apt-get on Alpine or apk on Debian
  5. curl/wget in HEALTHCHECK but not installed anywhere
  6. Deprecated base images (openjdk:17-jre-slim → eclipse-temurin:17-jre)
  7. COPY --from=<stage> referencing an undefined AS alias
  8. RUN with JSON exec form (RUN only supports shell form)
  9. HEALTHCHECK --interval with wrong format (must be like 30s, not 30)
 10. useradd missing -m (Debian) or adduser missing -h /home/<user> (Alpine) —
     the home directory must exist; otherwise PermissionError on $HOME at runtime
 11. COPY . . (or any runtime-stage COPY) without --chown=<user>:<group> when
     the Dockerfile drops to a non-root USER — root-owned /app breaks
     runtime mkdir/write with PermissionError: [Errno 13]
 12. USER <non-root> directive without a preceding "mkdir -p .../<writable> && chown -R"
     for runtime-writable paths the framework needs (workspace, logs, tmp)

Return ONLY this JSON — no text, no markdown, no code fences:
{
  "issues": ["short description of each issue found"],
  "patches": [
    {
      "target_line": "<exact line from Dockerfile to replace>",
      "replacement": "<corrected line(s) — use \\n for multi-line>",
      "reason": "<one sentence>",
      "confidence": 0.95,
      "operation": "replace"
    }
  ]
}

Rules:
- If no issues found, return: {"issues": [], "patches": []}
- confidence must be 0.0–1.0 — only include patches with confidence ≥ 0.80
- target_line must be an EXACT match to a line in the Dockerfile
- replacement is the corrected version of that exact line
- operation is always "replace" unless you need "prepend_before" (insert line before target)
- Do NOT invent issues that aren't present. Do NOT change correct lines.\
"""

_CRITIQUE_USER_TEMPLATE = """\
Review this Dockerfile as a senior DevOps architect:

=== Dockerfile ===
{dockerfile}
=== End Dockerfile ===

Runtime context:
  Base image (runtime stage): {runtime_image}
  Detected distro family: {distro_family}
  Framework: {framework}
  Language: {language}

Find execution-breaking issues only. Return the JSON schema above.\
"""


class SelfCritiqueLoop:
    """
    Uses a GPT provider to self-review and auto-correct a generated Dockerfile.

    Usage:
        loop = SelfCritiqueLoop(provider_factory)
        result = loop.critique(dockerfile, context)
        final_artifact = result.corrected_artifact
    """

    # Only apply patches with this minimum confidence
    _MIN_CONFIDENCE = 0.80

    def __init__(self, provider: Any) -> None:
        """
        Args:
            provider: Any object with a .chat_json(system, user, temp, max_tokens) method.
                      Typically a ProviderFactory or LLMService instance.
        """
        self._provider = provider

    def critique(
        self,
        dockerfile: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CritiqueResult:
        """
        Review the Dockerfile, apply confident patches, return corrected artifact.

        Args:
            dockerfile: The assembled Dockerfile string.
            context:    Optional dict with keys: runtime_image, distro_family,
                        framework, language.

        Returns:
            CritiqueResult with corrected_artifact and applied patches.
        """
        result = CritiqueResult(corrected_artifact=dockerfile)

        if not dockerfile or not dockerfile.strip():
            return result

        ctx = context or {}

        user_prompt = _CRITIQUE_USER_TEMPLATE.format(
            dockerfile=dockerfile,
            runtime_image=ctx.get("runtime_image") or "unknown",
            distro_family=ctx.get("distro_family") or "unknown",
            framework=ctx.get("framework") or "unknown",
            language=ctx.get("language") or "unknown",
        )

        try:
            raw = self._provider.chat_json(
                _CRITIQUE_SYSTEM,
                user_prompt,
                0.05,   # Near-zero temperature: deterministic fact-finding
                1200,
            )
            result.llm_called = True

            if not isinstance(raw, dict):
                logger.warning("[SelfCritique] LLM returned non-dict: %s", type(raw))
                return result

            result.llm_success = True
            result.issues_found = [
                str(i) for i in (raw.get("issues") or [])
            ]

            raw_patches = raw.get("patches") or []
            if not raw_patches:
                logger.info("[SelfCritique] No patches needed — Dockerfile is clean")
                return result

            patches = _parse_patches(raw_patches, self._MIN_CONFIDENCE)
            corrected, applied = _apply_patches(dockerfile, patches)

            result.patches_applied = applied
            result.corrected_artifact = corrected

            logger.info(
                "[SelfCritique] issues=%d patches_proposed=%d patches_applied=%d",
                len(result.issues_found),
                len(raw_patches),
                len(applied),
            )

        except Exception as exc:
            logger.warning(
                "[SelfCritique] LLM call failed — original artifact kept: %s", exc
            )

        return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_patches(
    raw: list,
    min_confidence: float,
) -> List[CritiquePatch]:
    patches: List[CritiquePatch] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        target = (item.get("target_line") or "").strip()
        replacement = (item.get("replacement") or "").strip()
        reason = (item.get("reason") or "").strip()
        confidence = float(item.get("confidence") or 0.0)
        operation = (item.get("operation") or "replace").strip()

        if not target or not reason:
            continue
        if confidence < min_confidence:
            logger.debug(
                "[SelfCritique] Skipping low-confidence patch (%.2f): %s",
                confidence, target[:60],
            )
            continue

        patches.append(CritiquePatch(
            target_line=target,
            replacement=replacement,
            reason=reason,
            confidence=confidence,
            operation=operation,
        ))
    return patches


def _apply_patches(
    dockerfile: str,
    patches: List[CritiquePatch],
) -> Tuple[str, List[CritiquePatch]]:
    """
    Apply patches to the Dockerfile.

    Returns the corrected artifact and the list of patches actually applied
    (target_line must match at least one line for the patch to be applied).
    """
    lines = dockerfile.splitlines()
    applied: List[CritiquePatch] = []

    for patch in patches:
        target = patch.target_line
        matched = False

        new_lines: List[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped == target.strip() or line.strip() == target:
                matched = True
                if patch.operation == "delete":
                    pass  # Skip the line
                elif patch.operation == "prepend_before":
                    new_lines.append(patch.replacement)
                    new_lines.append(line)
                elif patch.operation == "append_after":
                    new_lines.append(line)
                    new_lines.append(patch.replacement)
                else:  # replace (default)
                    # Preserve indentation of original line
                    indent = len(line) - len(line.lstrip())
                    for rep_line in patch.replacement.splitlines():
                        new_lines.append(" " * indent + rep_line.strip())
            else:
                new_lines.append(line)

        if matched:
            lines = new_lines
            applied.append(patch)
            logger.debug(
                "[SelfCritique] Applied patch (%.2f): %s → %s",
                patch.confidence,
                target[:50],
                patch.replacement[:50],
            )
        else:
            logger.debug(
                "[SelfCritique] Patch target not found in Dockerfile: %s",
                target[:60],
            )

    return "\n".join(lines), applied
