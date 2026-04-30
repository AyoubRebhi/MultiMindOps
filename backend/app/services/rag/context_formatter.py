"""
Context Formatter — pre-generation chunk structuring for the DevSecOps RAG pipeline.

Transforms raw Qdrant chunks into a well-structured context string before
sending to the LLM. Groups by source type, preserves HCL/YAML code blocks,
and adds metadata headers so the LLM can cite sources precisely.

Usage:
    from backend.app.services.rag.context_formatter import format_context_for_generation
    context_str = format_context_for_generation(chunks, query)
"""

from __future__ import annotations

import re
from typing import Any

# Max chars per chunk before truncation — large enough to keep HCL blocks intact
_CHUNK_MAX_CHARS = 2000

# Source-type display labels (Qdrant payload field → human label)
_SOURCE_LABELS: dict[str, str] = {
    "terraform_hcl": "Terraform HCL",
    "json_kb":       "Knowledge Base",
    "markdown":      "Documentation",
    "yaml":          "YAML Config",
    "json_flat":     "Config (JSON)",
    "general":       "General",
}

# Source types that contain or imply code — get special code-block formatting
_CODE_SOURCE_TYPES = {"terraform_hcl", "yaml"}

# Artifact type → section header order (Terraform first for infra queries)
_ARTIFACT_ORDER = ["terraform", "k8s", "docker", "cicd", "aws", "security", "general"]


def format_context_for_generation(
    chunks: list[dict[str, Any]],
    query: str = "",
    max_total_chars: int = 14_000,
) -> str:
    """
    Format retrieved chunks into a structured context string for LLM generation.

    Strategy:
    1. Deduplicate by content.
    2. Group by artifact_type (terraform → k8s → docker → …).
    3. Within each group: HCL/YAML files first, then prose KB entries.
    4. Add metadata headers so the model can cite: [source_type | title | path].
    5. Wrap HCL/YAML content in fenced code blocks if not already fenced.
    6. Truncate each chunk at _CHUNK_MAX_CHARS without splitting HCL blocks mid-resource.

    Returns a single string ready for prompt injection.
    """
    if not chunks:
        return "(No context retrieved)"

    # ── 1. Deduplicate ────────────────────────────────────────────────────────
    seen_content: set[str] = set()
    unique_chunks: list[dict[str, Any]] = []
    for c in chunks:
        content = (c.get("content") or "").strip()
        if content and content not in seen_content:
            seen_content.add(content)
            unique_chunks.append(c)

    # ── 2. Group by artifact_type ─────────────────────────────────────────────
    groups: dict[str, list[dict[str, Any]]] = {}
    for c in unique_chunks:
        art = (c.get("artifact_type") or c.get("doc_type") or "general").lower()
        groups.setdefault(art, []).append(c)

    # ── 3. Within each group: code sources first ──────────────────────────────
    for art in groups:
        groups[art].sort(
            key=lambda c: (
                0 if c.get("source_type") in _CODE_SOURCE_TYPES else 1,
                -(c.get("score") or 0.0),
            )
        )

    # ── 4. Render sections in artifact order ──────────────────────────────────
    sections: list[str] = []
    ordered_arts = sorted(groups.keys(), key=lambda a: (
        _ARTIFACT_ORDER.index(a) if a in _ARTIFACT_ORDER else len(_ARTIFACT_ORDER)
    ))

    for art in ordered_arts:
        art_chunks = groups[art]
        art_label = art.upper()
        section_lines: list[str] = [f"{'─' * 60}", f"  [{art_label}]", f"{'─' * 60}"]

        for i, c in enumerate(art_chunks):
            source_type = c.get("source_type") or "general"
            label       = _SOURCE_LABELS.get(source_type, source_type)
            title       = c.get("title") or c.get("concept") or c.get("id") or ""
            path        = c.get("path") or ""
            score       = c.get("rerank_score") or c.get("score") or 0.0

            # Metadata header
            meta_parts = [f"type={label}"]
            if title:
                meta_parts.append(f"title={title}")
            if path:
                meta_parts.append(f"src={path.split('/')[-1]}")
            meta_parts.append(f"score={score:.3f}")
            header = "# " + " | ".join(meta_parts)

            # Content — smart truncate at HCL block boundary
            content = _truncate_at_block_boundary(
                (c.get("content") or "").strip(),
                _CHUNK_MAX_CHARS,
            )

            # Wrap raw HCL/YAML in fences if not already fenced
            if source_type in _CODE_SOURCE_TYPES and not content.startswith("```"):
                lang = "hcl" if source_type == "terraform_hcl" else "yaml"
                content = f"```{lang}\n{content}\n```"

            section_lines.append(header)
            section_lines.append(content)
            if i < len(art_chunks) - 1:
                section_lines.append("")  # blank line between chunks in same group

        sections.append("\n".join(section_lines))

    full_context = "\n\n".join(sections)

    # ── 5. Global truncation ──────────────────────────────────────────────────
    if len(full_context) > max_total_chars:
        full_context = full_context[:max_total_chars] + "\n\n[...context truncated...]"

    return full_context


def _truncate_at_block_boundary(text: str, max_chars: int) -> str:
    """
    Truncate text to max_chars, but prefer to cut at an HCL resource block
    boundary (closing `}`) rather than mid-line.

    This preserves syntactic validity of HCL examples in the context.
    """
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]

    # Try to find the last closing brace of an HCL block within the truncated text
    last_brace = truncated.rfind("\n}")
    if last_brace > max_chars * 0.5:  # only if we're keeping at least half the content
        return truncated[: last_brace + 2] + "\n# [...truncated]"

    # Fallback: cut at last newline
    last_newline = truncated.rfind("\n")
    if last_newline > max_chars * 0.5:
        return truncated[:last_newline] + "\n# [...truncated]"

    return truncated + "\n# [...truncated]"


def extract_code_blocks(text: str) -> list[dict[str, str]]:
    """
    Extract all fenced code blocks from a chunk's content.

    Returns a list of dicts: {"lang": str, "code": str}
    Useful for chunking strategy: separate code from prose.
    """
    pattern = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
    blocks = []
    for match in pattern.finditer(text):
        blocks.append({
            "lang": match.group(1) or "text",
            "code": match.group(2).strip(),
        })
    return blocks


def split_prose_and_code(text: str) -> tuple[str, list[str]]:
    """
    Split a chunk into prose text and code blocks.

    Returns: (prose_text, [code_block_1, code_block_2, ...])
    Used by the HCL-aware chunking strategy to keep blocks atomic.
    """
    code_pattern = re.compile(r"```\w*\n.*?```", re.DOTALL)
    code_blocks = [m.group() for m in code_pattern.finditer(text)]
    prose = code_pattern.sub("", text).strip()
    return prose, code_blocks
