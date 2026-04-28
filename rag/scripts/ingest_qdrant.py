#!/usr/bin/env python3
"""
Ingest the DevSecOps corpus into Qdrant.

Pipeline:
  1. Connect to Qdrant  (optionally reset collection)
  2. Verify Ollama embedding model
  3. Load Markdown + YAML + JSON KB + Terraform/HCL documents from rag/corpus/
  4. Adaptive chunking policy:
     - JSON KB entries: pre-structured, bypass LLM
     - Markdown: configurable fallback/local/auto policy
     - Other docs: selected chunking provider (local/fallback)
  5. Embedding via Ollama nomic-embed-text:v1.5
  6. Batch upsert into Qdrant
  7. [optional] Post-ingestion validation queries

Usage:
    # Full ingestion (markdown defaults to deterministic fallback)
    python rag/scripts/ingest_qdrant.py

    # Reset collection before ingesting
    python rag/scripts/ingest_qdrant.py --reset

    # Ingest only one document type
    python rag/scripts/ingest_qdrant.py --doc-type terraform

    # Choose chunking provider explicitly
    python rag/scripts/ingest_qdrant.py --chunking-provider local
    python rag/scripts/ingest_qdrant.py --chunking-provider fallback

    # Markdown chunking policy (orthogonal to --chunking-provider)
    python rag/scripts/ingest_qdrant.py --markdown-chunking fallback
    python rag/scripts/ingest_qdrant.py --markdown-chunking auto
    python rag/scripts/ingest_qdrant.py --markdown-chunking local

    # Run validation queries after ingestion
    python rag/scripts/ingest_qdrant.py --validate

    # Full production reset + validate + evaluate
    python rag/scripts/ingest_qdrant.py --reset --validate --evaluate --verbose
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load RAG modules directly to avoid the FastAPI-dependent services/__init__.py chain.
import importlib.util as _ilu

def _load(rel: str):
    path = ROOT / rel
    spec = _ilu.spec_from_file_location(path.stem, path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_cfg_mod    = _load("backend/app/core/rag_config.py")
_chunk_mod  = _load("backend/app/services/rag/local_chunking_service.py")
_embed_mod  = _load("backend/app/services/rag/embedding_service.py")
_qdrant_mod = _load("backend/app/services/rag/qdrant_service.py")
_eval_mod   = _load("backend/app/services/rag/rag_evaluator.py")

rag_config                = _cfg_mod.rag_config
LocalChunkingService      = _chunk_mod.LocalChunkingService
EmbeddingService          = _embed_mod.EmbeddingService
QdrantService             = _qdrant_mod.QdrantService
RAGEvaluator              = _eval_mod.RAGEvaluator
print_benchmark_report    = _eval_mod.print_benchmark_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ingest_qdrant")


def _count_fenced_codeblocks(text: str) -> int:
    """Count fenced markdown code blocks (``` ... ```)."""
    if not text:
        return 0
    return len(re.findall(r"```[\s\S]*?```", text))

# ── Validation queries ────────────────────────────────────────────────────────

_VALIDATION_QUERIES = [
    ("terraform aws vpc", "terraform"),
    ("kubernetes deployment example", "k8s"),
    ("aws architecture best practices", "aws"),
    ("docker security hardening", "docker"),
    ("cicd pipeline security scanning", "cicd"),
]


# ── JSON KB helpers ───────────────────────────────────────────────────────────

def _infer_folder_artifact(folder: str) -> str:
    f = folder.lower()
    if "terraform" in f:
        return "terraform"
    if any(x in f for x in ("k8s", "kubernetes", "eks")):
        return "k8s"
    if "docker" in f:
        return "docker"
    if any(x in f for x in ("cicd", "pipeline", "ci")):
        return "cicd"
    if "aws" in f or "cloud" in f:
        return "aws"
    return "general"


def _infer_folder_cloud(folder: str) -> str:
    f = folder.lower()
    if any(x in f for x in ("aws", "terraform", "cloud", "eks")):
        return "aws"
    if any(x in f for x in ("gcp", "google")):
        return "gcp"
    if "azure" in f:
        return "azure"
    return "general"


def _format_kb_entry(entry: dict) -> list[str]:
    """
    Convert a KB entry dict into 1–2 semantic text chunks.

    Returns a list with 1 element normally, 2 if the entry is very long
    (description + rules in chunk 1; tradeoffs + anti_patterns + alignment in chunk 2).
    """
    concept   = entry.get("concept", "")
    category  = entry.get("category", "")
    desc      = entry.get("description", "")
    rules     = entry.get("decision_rules", [])
    tradeoffs = entry.get("tradeoffs", [])
    anti      = entry.get("anti_patterns", [])
    alignment = entry.get("aws_alignment", [])

    header = "\n".join(filter(None, [
        f"Concept: {concept}" if concept else "",
        f"Category: {category}" if category else "",
    ]))

    def _fmt_list(label: str, items: list) -> str:
        if not items:
            return ""
        return label + "\n" + "\n".join(f"- {i}" for i in items)

    primary_parts = list(filter(None, [
        header,
        desc,
        _fmt_list("Decision Rules:", rules),
    ]))
    primary = "\n\n".join(primary_parts).strip()

    secondary_parts = list(filter(None, [
        f"Concept: {concept} (continued)" if concept else "",
        _fmt_list("Key Tradeoffs:", tradeoffs),
        _fmt_list("Anti-Patterns to Avoid:", anti),
        _fmt_list("AWS Well-Architected Alignment:", alignment),
    ]))
    secondary = "\n\n".join(secondary_parts).strip()

    # Handle extra fields not in the known schema (future-proof)
    _known = {
        "id", "category", "concept", "description",
        "decision_rules", "tradeoffs", "anti_patterns", "aws_alignment",
    }
    extras: list[str] = []
    for key, val in entry.items():
        if key in _known:
            continue
        label = key.replace("_", " ").title()
        if isinstance(val, list) and val:
            extras.append(_fmt_list(f"{label}:", [str(v) for v in val if isinstance(v, str)]))
        elif isinstance(val, str) and val:
            extras.append(f"{label}: {val}")
    if extras:
        secondary = (secondary + "\n\n" + "\n\n".join(extras)).strip()

    # Only split when the combined text is significantly oversized (> 2 000 chars).
    # The KB index states entries average 400-600 tokens — one chunk is usually fine.
    full = (primary + "\n\n" + secondary).strip() if secondary else primary
    if len(full) <= 2000 or not secondary:
        return [full]
    return [primary, secondary]


def _expand_json_kb_entries(
    json_file: Path,
    corpus_root: Path,
) -> list[dict]:
    """
    Parse a JSON knowledge-base file and return one document dict per KB entry.

    Supports:
    - KB-style JSON  → { "metadata": {...}, "entries": [{...}, ...] }
    - Index files    → { "knowledge_base_files": [...] }  (skipped)
    - Flat JSON      → arbitrary key-value structure (one doc, flattened text)
    """
    import json as _json

    try:
        raw_text = json_file.read_text(encoding="utf-8")
        data = _json.loads(raw_text)
    except (_json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse JSON file '%s': %s", json_file, exc)
        return []

    if not isinstance(data, dict):
        logger.debug("Skipping non-object JSON: %s", json_file.name)
        return []

    # Skip index / pointer files — they contain file references, not KB content
    if "knowledge_base_files" in data:
        logger.debug("Skipping index file: %s", json_file.name)
        return []

    relative   = json_file.relative_to(corpus_root)
    folder     = relative.parts[0] if len(relative.parts) > 1 else "general"
    artifact   = _infer_folder_artifact(folder)
    cloud      = _infer_folder_cloud(folder)
    rel_path   = str(json_file.relative_to(ROOT)).replace("\\", "/")

    kb_meta = data.get("metadata", {})
    kb_id   = kb_meta.get("id", json_file.stem)
    entries = data.get("entries")

    # ── KB-style JSON (most important) ───────────────────────────────────────
    if isinstance(entries, list) and entries:
        docs: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id", f"{kb_id}_entry_{len(docs)}")
            concept  = entry.get("concept", entry_id)
            category = entry.get("category", folder)

            for chunk_idx, chunk_text in enumerate(_format_kb_entry(entry)):
                if not chunk_text.strip():
                    continue
                suffix = f"_part{chunk_idx + 1}" if chunk_idx > 0 else ""
                docs.append({
                    "id": f"{entry_id}{suffix}",
                    "path": rel_path,
                    "doc_type": folder,
                    "artifact_type": artifact,
                    "content": chunk_text,
                    "source_type": "json_kb",
                    "kb_section": category,
                    "metadata": {
                        "source_type": "json_kb",
                        "kb_section": category,
                        "hierarchy_path": f"{kb_id}/{entry_id}",
                        "entry_id": entry_id,
                        "concept": concept,
                        "kb_title": kb_meta.get("title", ""),
                        "cloud_provider": cloud,
                        "artifact_type": artifact,
                    },
                })

        logger.info(
            "JSON KB '%s': %d entries → %d documents (folder=%s)",
            json_file.name, len(entries), len(docs), folder,
        )
        return docs

    # ── Flat / unknown JSON ───────────────────────────────────────────────────
    lines: list[str] = []

    def _flatten(obj: object, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _flatten(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _flatten(item, f"{path}[{i}]")
        elif str(obj).strip():
            lines.append(f"{path}: {obj}")

    _flatten(data, "")
    flat_text = "\n".join(lines).strip()

    if not flat_text or len(flat_text) < 50:
        return []

    logger.info("JSON flat '%s': 1 document (folder=%s)", json_file.name, folder)
    return [{
        "id": f"json_{json_file.stem}",
        "path": rel_path,
        "doc_type": folder,
        "artifact_type": artifact,
        "content": flat_text,
        "source_type": "json_flat",
        "kb_section": folder,
        "metadata": {
            "source_type": "json_flat",
            "kb_section": folder,
            "hierarchy_path": json_file.stem,
            "cloud_provider": cloud,
            "artifact_type": artifact,
        },
    }]


# ── Document loading ──────────────────────────────────────────────────────────

def load_corpus(corpus_root: Path, doc_type_filter: str | None = None) -> list[dict]:
    """
    Load all documents from the corpus.

    Supported formats:
    - .md       — Markdown with optional YAML front-matter
    - .yml/.yaml — Raw YAML configs
    - .json     — JSON knowledge-base files (KB-style or flat)
    - .tf/.hcl  — Terraform / HCL infrastructure files
    """
    import yaml

    corpus_root = (
        (ROOT / corpus_root).resolve()
        if not corpus_root.is_absolute()
        else corpus_root.resolve()
    )

    if not corpus_root.exists():
        logger.error("Corpus not found: %s", corpus_root)
        return []

    documents: list[dict] = []

    # ── Markdown ──────────────────────────────────────────────────────────────
    for md_file in sorted(corpus_root.rglob("*.md")):
        if doc_type_filter:
            relative = md_file.relative_to(corpus_root)
            folder = relative.parts[0] if len(relative.parts) > 1 else ""
            if doc_type_filter.lower() not in folder.lower():
                continue

        try:
            raw = md_file.read_text(encoding="utf-8").strip()
            if not raw:
                continue

            metadata: dict = {}
            content = raw

            if raw.startswith("---"):
                parts = raw.split("---", 2)
                if len(parts) >= 3:
                    metadata = yaml.safe_load(parts[1]) or {}
                    content = parts[2].strip()

            relative = md_file.relative_to(corpus_root)
            inferred_type = relative.parts[0] if len(relative.parts) > 1 else "general"

            documents.append({
                "id": metadata.get("id") or md_file.stem,
                "path": str(md_file.relative_to(ROOT)).replace("\\", "/"),
                "doc_type": metadata.get("doc_type") or inferred_type,
                "artifact_type": metadata.get("artifact_type") or inferred_type,
                "content": content,
                "source_type": "markdown",
                "metadata": metadata,
            })
        except Exception as exc:
            logger.warning("Failed to read %s: %s", md_file, exc)

    # ── YAML ──────────────────────────────────────────────────────────────────
    for ext in ("*.yml", "*.yaml"):
        for yaml_file in sorted(corpus_root.rglob(ext)):
            try:
                relative = yaml_file.relative_to(corpus_root)
                folder = relative.parts[0] if len(relative.parts) > 1 else "general"

                if doc_type_filter and doc_type_filter.lower() not in folder.lower():
                    continue

                content = yaml_file.read_text(encoding="utf-8").strip()
                if not content or len(content) < 50:
                    continue

                documents.append({
                    "id": f"yaml_{yaml_file.stem}",
                    "path": str(yaml_file.relative_to(ROOT)).replace("\\", "/"),
                    "doc_type": folder,
                    "artifact_type": folder,
                    "content": content,
                    "source_type": "yaml",
                    "metadata": {},
                })
            except Exception as exc:
                logger.warning("Failed to read YAML %s: %s", yaml_file, exc)

    # ── JSON KB files ─────────────────────────────────────────────────────────
    json_file_count = 0
    json_entry_count = 0

    for json_file in sorted(corpus_root.rglob("*.json")):
        try:
            relative = json_file.relative_to(corpus_root)
            folder = relative.parts[0] if len(relative.parts) > 1 else "general"

            if doc_type_filter and doc_type_filter.lower() not in folder.lower():
                continue

            pre_docs = _expand_json_kb_entries(json_file, corpus_root)
            if pre_docs:
                json_file_count += 1
                json_entry_count += len(pre_docs)
                documents.extend(pre_docs)
        except Exception as exc:
            logger.warning("Failed to process JSON file %s: %s", json_file, exc)

    if json_file_count:
        logger.info(
            "JSON: %d files → %d entries loaded",
            json_file_count, json_entry_count,
        )

    # ── Terraform / HCL ───────────────────────────────────────────────────────
    tf_count = 0
    for ext in ("*.tf", "*.hcl"):
        for tf_file in sorted(corpus_root.rglob(ext)):
            try:
                relative = tf_file.relative_to(corpus_root)
                folder = relative.parts[0] if len(relative.parts) > 1 else "general"

                if doc_type_filter and doc_type_filter.lower() not in folder.lower():
                    continue

                content = tf_file.read_text(encoding="utf-8").strip()
                if not content or len(content) < 20:
                    continue

                documents.append({
                    "id": f"tf_{tf_file.stem}",
                    "path": str(tf_file.relative_to(ROOT)).replace("\\", "/"),
                    "doc_type": "terraform",
                    "artifact_type": "terraform",
                    "content": content,
                    "source_type": "terraform_hcl",
                    "metadata": {
                        "source_type": "terraform_hcl",
                        "artifact_type": "terraform",
                        "cloud_provider": "aws",
                    },
                })
                tf_count += 1
            except Exception as exc:
                logger.warning("Failed to read TF/HCL file %s: %s", tf_file, exc)

    if tf_count:
        logger.info("Terraform/HCL: %d files loaded", tf_count)

    # ── Summary ───────────────────────────────────────────────────────────────
    by_source: dict[str, int] = {}
    for d in documents:
        st = d.get("source_type", "unknown")
        by_source[st] = by_source.get(st, 0) + 1

    logger.info(
        "Loaded %d documents from corpus  (%s)",
        len(documents),
        "  ".join(f"{k}={v}" for k, v in sorted(by_source.items())),
    )
    return documents


# ── Validation ────────────────────────────────────────────────────────────────

def validate_ingestion(qdrant: QdrantService, embedder: EmbeddingService) -> bool:
    """
    Run semantic test queries and report retrieval quality with reranking impact.

    For each query:
      - Runs hybrid search (top-3 without rerank)  — baseline scores
      - Runs search_with_rerank (top-3)            — after heuristic reranking
      - Shows the top result from each stage so the rerank delta is visible
    """
    print("\n" + "─" * 68)
    print("  VALIDATION — test queries (with reranking comparison)")
    print("─" * 68)

    passed = 0
    for query, expected_type in _VALIDATION_QUERIES:
        vec = embedder.embed_query(query)

        # ── Baseline: pure hybrid search ──────────────────────────────────────
        baseline = qdrant.hybrid_search(
            query_vector=vec, keyword=query, top_k=3, score_threshold=0.20,
        )
        # ── Reranked: two-stage retrieval ─────────────────────────────────────
        reranked = qdrant.search_with_rerank(
            query_vector=vec, query=query, top_k=3,
            candidate_multiplier=4, score_threshold=0.20,
        )

        if reranked or baseline:
            results = reranked or baseline
            top = results[0]
            base_score   = baseline[0]["score"]     if baseline else 0.0
            rerank_score = top.get("rerank_score") or top["score"]
            delta_str    = f"+{rerank_score - base_score:.3f}" if reranked and baseline else "n/a"

            print(
                f"  PASS  '{query}'\n"
                f"        hits={len(results)}  "
                f"base_score={base_score:.3f}  rerank_score={rerank_score:.3f}  delta={delta_str}\n"
                f"        doc_type={top.get('doc_type','?')}  framework={top.get('framework','?')}"
                f"  complexity={top.get('complexity','?')}  use_case={top.get('use_case','?')}\n"
                f"        chunking_source={top.get('chunking_source','?')}"
                f"  chunk_type={top.get('chunk_type','?')}\n"
                f"        title={top.get('title', '')[:70]}"
            )
            passed += 1
        else:
            print(f"  FAIL  '{query}' — no results above threshold")

    total = len(_VALIDATION_QUERIES)
    print(f"\n  Result: {passed}/{total} queries returned results")
    print("─" * 68)
    return passed == total


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest the DevSecOps corpus into Qdrant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Delete and recreate the Qdrant collection before ingesting",
    )
    parser.add_argument(
        "--doc-type", metavar="TYPE",
        help="Ingest only this document type (docker, k8s, terraform, cicd, cloud…)",
    )
    parser.add_argument(
        "--chunking-provider",
        choices=["local", "fallback"],
        default=getattr(rag_config, "chunking_provider", "local"),
        help=(
            "Chunking backend: "
            "'local' (Ollama — default), "
            "'fallback' (deterministic, no LLM)."
        ),
    )
    parser.add_argument(
        "--markdown-chunking",
        choices=["fallback", "local", "auto"],
        default=getattr(rag_config, "markdown_chunking_mode", "fallback"),
        help=(
            "Markdown chunking policy: "
            "'fallback' (default, deterministic/no LLM), "
            "'local' (always local Ollama), "
            "'auto' (local only when markdown is small/simple)."
        ),
    )
    parser.add_argument(
        "--md-local-max-chars",
        type=int,
        default=getattr(rag_config, "markdown_local_max_chars", 8000),
        help="For --markdown-chunking=auto: max markdown chars to allow local chunking.",
    )
    parser.add_argument(
        "--md-local-max-codeblocks",
        type=int,
        default=getattr(rag_config, "markdown_local_max_codeblocks", 12),
        help="For --markdown-chunking=auto: max fenced code blocks to allow local chunking.",
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Run semantic test queries after ingestion to verify retrieval quality",
    )
    parser.add_argument(
        "--evaluate", action="store_true",
        help="Run full RAG evaluation benchmark after ingestion",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    t_start = time.time()

    print("\n" + "=" * 60)
    print("  INGEST QDRANT — DevSecOps Knowledge Base")
    print("=" * 60)

    # ── 1. Verify Qdrant ──────────────────────────────────────────────────────
    print("\n[1/6] Connecting to Qdrant…")
    qdrant = QdrantService(
        url=rag_config.qdrant_url,
        collection_name=rag_config.qdrant_collection,
        vector_size=rag_config.qdrant_vector_size,
    )
    health = qdrant.health_check()
    if health.get("status") != "ok":
        print(f"  ERROR — Qdrant unreachable: {health}")
        print("  Make sure Qdrant is running: docker ps | grep qdrant")
        return 1
    print(f"  OK — {rag_config.qdrant_url}")

    # ── 2. Create / recreate collection ───────────────────────────────────────
    print(f"\n[2/6] Collection '{rag_config.qdrant_collection}'…")
    if args.reset:
        print("  --reset: deleting existing collection…")
    if not qdrant.create_collection(recreate=args.reset):
        print("  ERROR — Could not create the collection")
        return 1
    info = qdrant.collection_info()
    existing_points = info.get("points_count", 0)
    print(f"  OK — {existing_points} existing points")

    # ── 3. Verify Ollama ──────────────────────────────────────────────────────
    print("\n[3/6] Checking Ollama…")
    embedder = EmbeddingService(
        ollama_base_url=rag_config.ollama_base_url,
        model=rag_config.ollama_embed_model,
    )
    embed_health = embedder.health_check()
    if embed_health.get("status") == "error":
        print(f"  ERROR — Ollama unreachable: {embed_health.get('error')}")
        print(f"  Configured URL: {rag_config.ollama_base_url}")
        print("  Start Ollama: ollama serve")
        return 1
    if embed_health.get("status") == "model_missing":
        print(f"  WARNING — Model '{rag_config.ollama_embed_model}' not found.")
        print(f"  Install it: ollama pull {rag_config.ollama_embed_model}")
        print(f"  Available: {embed_health.get('available_models')}")
    else:
        print(f"  OK — {rag_config.ollama_embed_model} available")

    # ── 4. Load corpus ────────────────────────────────────────────────────────
    print(f"\n[4/6] Loading corpus from '{rag_config.corpus_path}'…")
    t_load = time.time()
    corpus_path = Path(rag_config.corpus_path)
    documents = load_corpus(corpus_path, doc_type_filter=args.doc_type)
    t_load = time.time() - t_load

    if not documents:
        print(f"  No documents found in {corpus_path}")
        print("  Check RAG_CORPUS_PATH in .env")
        return 1

    doc_type_counts = Counter(d["doc_type"] for d in documents)
    src_type_counts = Counter(d.get("source_type", "unknown") for d in documents)
    print(f"  {len(documents)} documents loaded in {t_load:.1f}s")
    print("  By source_type:")
    for st, cnt in sorted(src_type_counts.items()):
        print(f"    {st:<25} {cnt}")
    print("  By doc_type:")
    for dt, cnt in sorted(doc_type_counts.items()):
        print(f"    {dt:<25} {cnt}")

    # ── 5. Chunking ───────────────────────────────────────────────────────────
    print("\n[5/6] Semantic chunking…")

    cp = args.chunking_provider  # "local" | "fallback"
    md_mode = args.markdown_chunking  # "fallback" | "local" | "auto"
    force_fallback = (cp == "fallback")

    chunker = LocalChunkingService(
        ollama_base_url=getattr(rag_config, "ollama_base_url", "http://localhost:11434"),
        model=getattr(rag_config, "ollama_chunk_model", "llama3.2:3b"),
        force_fallback=force_fallback,
        enable_cache=True,
    )

    # Connectivity pre-flight (skipped for deterministic mode)
    if not force_fallback:
        print("  Testing local Ollama connectivity…")
        conn = chunker.test_connection()
        if conn.get("ok", False):
            print(
                f"  OK — provider=local  model={conn.get('model')}  latency={conn.get('latency_ms')}ms"
            )
            logger.info(
                "[Chunking] Preflight OK | provider=local | model=%s | %dms",
                conn.get("model"), conn.get("latency_ms", 0),
            )
        else:
            err = conn.get("error", "unknown error")
            print(f"  WARNING — Ollama connectivity FAILED: {err}")
            print("  Chunker will use deterministic fallback per-document.")
            logger.warning("[Chunking] Preflight FAILED (%s) — deterministic fallback will be used", err)
    else:
        print("  Provider : fallback (deterministic — no LLM)")
        logger.info("[Chunking] --chunking-provider=fallback selected")

    print(
        "  Markdown policy: mode=%s  md_local_max_chars=%d  md_local_max_codeblocks=%d"
        % (md_mode, args.md_local_max_chars, args.md_local_max_codeblocks)
    )
    logger.info(
        "[Chunking] markdown policy | mode=%s | md_local_max_chars=%d | md_local_max_codeblocks=%d",
        md_mode,
        args.md_local_max_chars,
        args.md_local_max_codeblocks,
    )

    t_chunk = time.time()
    all_chunks: list[dict] = []
    chunks_per_type: dict[str, int] = defaultdict(int)
    zero_chunk_docs: list[str] = []
    md_total = 0
    md_local = 0
    md_fallback = 0

    for idx, doc in enumerate(documents, 1):
        if args.verbose:
            logger.debug("  Chunking [%d/%d]: %s", idx, len(documents), doc["path"])
        try:
            # JSON KB entries are pre-structured — bypass LLM, direct chunk creation
            if doc.get("source_type") == "json_kb":
                chunks = chunker.make_json_kb_chunk(doc)
            else:
                source = doc.get("path", "")
                source_ext = Path(source).suffix.lower()
                source_type = doc.get("source_type", "unknown")

                per_doc_force_fallback = False
                md_reason = None
                md_selected_mode = None

                if source_type == "markdown" or source_ext == ".md":
                    md_total += 1
                    content = doc.get("content", "")
                    content_len = len(content)
                    codeblocks = _count_fenced_codeblocks(content)

                    if force_fallback:
                        per_doc_force_fallback = True
                        md_selected_mode = "fallback"
                        md_reason = "policy=chunking_provider_fallback"
                    elif md_mode == "fallback":
                        per_doc_force_fallback = True
                        md_selected_mode = "fallback"
                        md_reason = "policy=fallback"
                    elif md_mode == "local":
                        md_selected_mode = "local"
                        md_reason = "user_forced_local"
                    else:  # auto
                        if content_len > args.md_local_max_chars:
                            per_doc_force_fallback = True
                            md_selected_mode = "fallback"
                            md_reason = "auto:too_large"
                        elif codeblocks > args.md_local_max_codeblocks:
                            per_doc_force_fallback = True
                            md_selected_mode = "fallback"
                            md_reason = "auto:too_many_codeblocks"
                        else:
                            md_selected_mode = "local"
                            md_reason = "auto:small_simple"

                    if md_selected_mode == "local":
                        md_local += 1
                    else:
                        md_fallback += 1

                    logger.info(
                        "[Chunking] markdown decision | source=%s | source_type=%s | source_ext=%s | selected=%s | reason=%s",
                        source,
                        source_type,
                        source_ext or "(none)",
                        md_selected_mode,
                        md_reason,
                    )

                chunks = chunker.chunk_document(
                    content=doc["content"],
                    source=doc["path"],
                    doc_type=doc["doc_type"],
                    force_fallback=per_doc_force_fallback,
                )
        except Exception as exc:
            logger.error("Chunking failed for '%s': %s", doc["path"], exc)
            chunks = []

        if not chunks:
            zero_chunk_docs.append(doc["path"])
        else:
            chunks_per_type[doc["doc_type"]] += len(chunks)
            all_chunks.extend(chunks)

        if args.verbose:
            logger.debug("  '%s' → %d chunks", doc["path"], len(chunks))

    t_chunk = time.time() - t_chunk
    avg_chunks_per_doc = len(all_chunks) / max(len(documents), 1)

    local_chunks     = sum(1 for c in all_chunks if c.get("chunking_source") == "local")
    fallback_chunks  = sum(1 for c in all_chunks if c.get("chunking_source") == "fallback")
    json_kb_chunks   = sum(1 for c in all_chunks if c.get("chunking_source") == "json_kb")

    # Chunk size diagnostics
    chunk_sizes = [len(c.get("content", "")) for c in all_chunks if c.get("content")]
    avg_chars   = sum(chunk_sizes) / max(len(chunk_sizes), 1)
    min_chars   = min(chunk_sizes) if chunk_sizes else 0
    max_chars   = max(chunk_sizes) if chunk_sizes else 0
    avg_tokens  = avg_chars / 4.0  # rough 4-chars-per-token heuristic

    print(f"  {len(all_chunks)} chunks in {t_chunk:.1f}s (avg {avg_chunks_per_doc:.1f} chunks/doc)")
    print(f"  Chunk size: avg={avg_chars:.0f} chars (~{avg_tokens:.0f} tokens)  min={min_chars}  max={max_chars}")
    print(f"  chunking_source: local={local_chunks}  fallback={fallback_chunks}  json_kb={json_kb_chunks}")
    print(f"  Markdown summary: md_total={md_total}  md_local={md_local}  md_fallback={md_fallback}")
    print("  By doc_type:")
    for dt, cnt in sorted(chunks_per_type.items()):
        print(f"    {dt:<25} {cnt} chunks")
    if zero_chunk_docs:
        print(f"  WARNING — {len(zero_chunk_docs)} docs produced 0 chunks:")
        for path in zero_chunk_docs[:5]:
            print(f"    {path}")

    # ── 6. Embedding + upsert ─────────────────────────────────────────────────
    print("\n[6/6] Embedding + upsert…")
    t_embed = time.time()
    chunks_with_embeddings = embedder.embed_chunks(all_chunks)
    t_embed = time.time() - t_embed

    valid = [c for c in chunks_with_embeddings if c.get("embedding") and any(c["embedding"])]
    skipped = len(chunks_with_embeddings) - len(valid)
    embed_tps = len(valid) / t_embed if t_embed > 0 else 0
    print(f"  {len(valid)} embeddings in {t_embed:.1f}s — throughput {embed_tps:.1f} chunks/s  ({skipped} skipped)")

    if not valid:
        print("  ERROR — No valid embeddings generated")
        return 1

    t_upsert = time.time()
    inserted = qdrant.upsert_documents(valid)
    t_upsert = time.time() - t_upsert
    print(f"  {inserted} points upserted in {t_upsert:.1f}s")

    # ── Summary ───────────────────────────────────────────────────────────────
    info = qdrant.collection_info()
    provider_label = f"local (Ollama {getattr(rag_config, 'ollama_chunk_model', 'llama3.2:3b')})" if not force_fallback else "fallback (deterministic)"
    t_total = time.time() - t_start

    print("\n" + "=" * 60)
    print("  INGESTION COMPLETE")
    print(f"  Chunking    : {provider_label}")
    print(
        "  Markdown    : mode=%s  md_total=%d  md_local=%d  md_fallback=%d"
        % (md_mode, md_total, md_local, md_fallback)
    )
    print(f"  Documents   : {len(documents)}  ({len(zero_chunk_docs)} with 0 chunks)")
    print(f"  Chunks      : {len(all_chunks)}  (local={local_chunks} fallback={fallback_chunks} json_kb={json_kb_chunks})  avg≈{avg_tokens:.0f} tokens")
    print(f"  Embedded    : {len(valid)}  ({skipped} skipped)")
    print(f"  Inserted    : {inserted}")
    print(f"  Collection  : {info.get('points_count', '?')} total points")
    print(f"  Qdrant      : {rag_config.qdrant_url} / {rag_config.qdrant_collection}")
    print(f"  Timing      : load={t_load:.1f}s  chunk={t_chunk:.1f}s  embed={t_embed:.1f}s  upsert={t_upsert:.1f}s  total={t_total:.1f}s")
    print("=" * 60)

    # ── Optional validation ───────────────────────────────────────────────────
    if args.validate:
        validate_ingestion(qdrant, embedder)

    # ── Optional RAG evaluation benchmark ────────────────────────────────────
    if args.evaluate:
        print("\n" + "─" * 60)
        print("  RAG EVALUATION — running benchmark…")
        print("─" * 60)
        evaluator = RAGEvaluator(
            qdrant_service=qdrant,
            embedding_service=embedder,
            lightning_api_key=rag_config.lightning_api_key,
            lightning_base_url=rag_config.lightning_base_url,
            lightning_eval_model=rag_config.lightning_eval_model,
            groq_api_key=rag_config.groq_api_key,
            groq_model=rag_config.groq_model,
            top_k=5,
            score_threshold=0.25,
        )
        report = evaluator.run_benchmark()
        print_benchmark_report(report)

        import json as _json
        report_path = ROOT / "rag" / "eval_report.json"
        report_path.write_text(
            _json.dumps(report.to_dict(), indent=2),
            encoding="utf-8",
        )
        print(f"  Evaluation report saved → {report_path.relative_to(ROOT)}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
