"""Shared utilities for the DevSecOps RAG ingestion pipeline (rag/tools/).

This module is the common foundation for the three pipeline stages:

    chunk_corpus.py   (Phase 1 - GPT-4.1-mini semantic chunking)
    embed_corpus.py   (Phase 2 - text-embedding-3-small embeddings)
    index_qdrant.py   (Phase 3 - Qdrant indexing)

Design rules (intentional, do not regress):
  * Standalone. Does NOT import the legacy ``rag/scripts/`` ingestion pipeline
    nor the FastAPI ``backend/`` services. The new corpus structure
    (``rag/corpus_cleaned/``) is the single source of truth.
  * OpenAI access is always via the ``OPENAI_API_KEY`` environment variable.
  * Deterministic where possible (stable ids, sorted file iteration) so every
    stage is re-runnable / idempotent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Iterator

# ── Paths ───────────────────────────────────────────────────────────────────
# rag/tools/_rag_common.py -> parents[0]=tools, [1]=rag, [2]=repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_CLEANED = REPO_ROOT / "rag" / "corpus_cleaned"
CORPUS_CHUNKED = REPO_ROOT / "rag" / "corpus_chunked"
CORPUS_EMBEDDED = REPO_ROOT / "rag" / "corpus_embedded"
EMBEDDINGS_FILE = CORPUS_EMBEDDED / "embeddings.jsonl"
CHUNK_CACHE_FILE = CORPUS_CHUNKED / ".chunk_cache.json"

# Files inside corpus_cleaned/ that are NOT embeddable knowledge content.
NON_CORPUS_FILES = {"MANIFEST.json", "evaluation_queries.json"}

# ── Model / collection constants ──────────────────────────────────────────────
CHUNK_MODEL = "gpt-4.1-mini"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
QDRANT_COLLECTION = "devsecops_kb"
DEFAULT_QDRANT_URL = "http://localhost:6333"

# Logging format kept ASCII-only on purpose: the Windows console renders this
# repo's data em-dashes (U+2014) as mojibake, so we keep log lines plain.
_LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)s - %(message)s"
_LOG_DATEFMT = "%H:%M:%S"


def setup_logging(name: str, verbose: bool = False) -> logging.Logger:
    """Configure root logging once and return a named logger."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format=_LOG_FORMAT,
        datefmt=_LOG_DATEFMT,
    )
    return logging.getLogger(name)


# ── Environment / OpenAI ──────────────────────────────────────────────────────

def load_env() -> None:
    """Load ``.env`` from the repo root (best-effort) without reading secrets here.

    Uses python-dotenv when available; if it is not installed we silently rely
    on the ambient environment so the scripts still work in CI / containers.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


def get_openai_client() -> Any:
    """Return an authenticated OpenAI client or raise a clear error.

    The key is read from ``OPENAI_API_KEY`` (never hardcoded). ``load_env`` is
    called first so a repo-root ``.env`` is honoured.
    """
    load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Export it or add it to the repo-root .env "
            "before running the embedding / chunking phases."
        )
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "The 'openai' package is required. Install it: pip install openai"
        ) from exc
    return OpenAI(api_key=api_key)


# ── Text helpers ───────────────────────────────────────────────────────────────

_ENCODER = None
_ENCODER_TRIED = False


def estimate_tokens(text: str) -> int:
    """Estimate token count.

    Uses ``tiktoken`` when importable (accurate for OpenAI models); otherwise
    falls back to the standard ~4-characters-per-token heuristic. tiktoken is
    optional so the pipeline does not hard-depend on it.
    """
    global _ENCODER, _ENCODER_TRIED
    if not text:
        return 0
    if not _ENCODER_TRIED:
        _ENCODER_TRIED = True
        try:
            import tiktoken  # type: ignore

            try:
                _ENCODER = tiktoken.encoding_for_model(EMBED_MODEL)
            except Exception:
                _ENCODER = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENCODER = None
    if _ENCODER is not None:
        try:
            return len(_ENCODER.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)


def sha256(text: str) -> str:
    """Stable content hash used for cache keys and change detection."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rel_to_repo(path: Path) -> str:
    """Forward-slash path relative to the repo root (cross-platform stable)."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


# ── JSON / JSONL IO ─────────────────────────────────────────────────────────────

def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, obj: Any) -> None:
    """Atomic UTF-8 JSON write (ensure_ascii=False to preserve em-dashes etc.)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Atomic UTF-8 JSONL write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False))
            fh.write("\n")
    tmp.replace(path)


def read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


# ── Corpus iteration ────────────────────────────────────────────────────────────

def iter_cleaned_files(root: Path = CORPUS_CLEANED) -> list[Path]:
    """Return every cleaned-corpus knowledge file, sorted, excluding manifests.

    Knowledge files are the ``*.cleaned.json`` payloads; ``MANIFEST.json`` and
    ``evaluation_queries.json`` are pipeline metadata, not embeddable content.
    """
    files: list[Path] = []
    for path in sorted(root.rglob("*.json")):
        if path.name in NON_CORPUS_FILES:
            continue
        if not path.name.endswith(".cleaned.json"):
            continue
        files.append(path)
    return files


def iter_cleaned_entries(path: Path) -> tuple[dict, list[dict]]:
    """Load a cleaned file, returning ``(file_header, entries)``.

    ``file_header`` is the file-level object minus the entry list; ``entries``
    is ``cleaned_entries`` (possibly empty, e.g. the index file).
    """
    data = read_json(path)
    entries = data.get("cleaned_entries", []) or []
    header = {k: v for k, v in data.items() if k != "cleaned_entries"}
    return header, entries
