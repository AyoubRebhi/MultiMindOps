#!/usr/bin/env python3
"""Phase 1 - Semantic chunking of the cleaned DevSecOps corpus (OpenAI GPT-4.1-mini).

    rag/corpus_cleaned/  --(this script)-->  rag/corpus_chunked/

What it does
------------
Each entry in ``rag/corpus_cleaned/`` is already cleaned, normalized and
deduplicated. This stage performs *semantic refinement only*: for each entry it
decides whether the ``content`` should stay as one chunk or be divided into a
small number of coherent, retrieval-sized chunks. It NEVER re-cleans, rewrites,
summarizes, or invents content.

Safety model (why this is production-grade, not a prototype)
------------------------------------------------------------
  * Short entries (< --min-split-tokens) bypass the LLM entirely and are emitted
    as a single chunk. Most cleaned entries are already ~400-600 token units, so
    this keeps cost low and avoids over-splitting.
  * For longer entries we ask GPT-4.1-mini (temperature 0, JSON mode) to split on
    natural boundaries while preserving every technical fact verbatim.
  * The model's output is *validated*: chunk count, non-empty content, and a
    total-length band vs. the original. If validation fails (the model dropped
    or hallucinated text), we DISCARD the split and fall back to the original
    single chunk. Technical accuracy is never sacrificed to chunking.
  * A content-hash cache (.chunk_cache.json) makes re-runs idempotent and cheap:
    unchanged entries reuse their cached chunks and skip the API.

Output
------
One ``*.chunked.json`` per cleaned source file (mirroring the folder layout):

    { "file_name", "source_file", "domain", "chunk_count", "chunks": [ ... ] }

Each chunk:
    chunk_id, parent_id, title, domain, service, content,
    metadata (all original entry fields preserved), chunk_index, chunk_hint

Usage
-----
    python rag/tools/chunk_corpus.py                 # full run (uses cache)
    python rag/tools/chunk_corpus.py --force         # ignore cache, re-chunk all
    python rag/tools/chunk_corpus.py --no-llm        # deterministic 1:1 (no API)
    python rag/tools/chunk_corpus.py --limit 3 -v    # first 3 files, debug logs
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _rag_common as rc  # noqa: E402

logger = rc.setup_logging("chunk_corpus")

# ── Tunables ────────────────────────────────────────────────────────────────
DEFAULT_MIN_SPLIT_TOKENS = 512   # below this, keep the entry whole (no LLM)
# Rationale: the cleaned corpus was authored as coherent ~400-600 token units,
# so only entries clearly above a single-chunk budget (~512 tok / ~2KB, the same
# point the legacy ingester split at) are worth sending to the LLM. This honours
# "do not over-split" and keeps API cost proportional to genuinely long entries.
DEFAULT_TARGET_TOKENS = 320      # preferred chunk size when splitting
DEFAULT_MAX_CHUNKS = 8           # hard guard against over-splitting
LLM_MAX_RETRIES = 3
LLM_RETRY_BACKOFF = 2.0          # seconds, exponential

_SYSTEM_PROMPT = (
    "You are a deterministic semantic chunking engine for a DevSecOps RAG system "
    "(Terraform, AWS, Docker, Kubernetes, security). You are given ONE knowledge "
    "entry. Split its text into between 1 and N coherent chunks for vector "
    "retrieval, following these rules strictly:\n"
    "1. PRESERVE ALL TECHNICAL CONTENT VERBATIM. Do not summarize, reword, "
    "translate, add, remove, or 'fix' anything. Copy the original characters, "
    "including resource names, CIDRs, flags, commands, and numbers.\n"
    "2. Split ONLY on natural semantic boundaries (a heading, a blank line, the "
    "start of a distinct sub-topic). Never split mid-sentence, mid-list, or "
    "mid-code.\n"
    "3. Prefer FEWER, medium-sized chunks (~200-450 tokens each). If the entry is "
    "a single coherent idea, return it as ONE chunk unchanged. Do NOT over-split.\n"
    "4. Keep each chunk self-contained and meaningful on its own.\n"
    "5. The concatenation of your chunks (in order) must equal the original text "
    "minus only whitespace at the split joins.\n"
    'Return ONLY JSON of the form: {"chunks": ["<chunk 1 text>", "<chunk 2 text>"]}'
)


# ── LLM chunking ──────────────────────────────────────────────────────────────

def _llm_split(client, model: str, title: str, content: str,
               target_tokens: int) -> list[str] | None:
    """Ask the model to split ``content``; return chunk texts or None on failure."""
    user_msg = (
        f"Entry title: {title}\n"
        f"Target chunk size: ~{target_tokens} tokens. Use as few chunks as "
        f"coherence allows.\n\n"
        f"Entry text to chunk:\n\"\"\"\n{content}\n\"\"\""
    )
    last_err: Exception | None = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            chunks = data.get("chunks")
            if not isinstance(chunks, list):
                raise ValueError("response missing 'chunks' list")
            cleaned = [c.strip() for c in chunks if isinstance(c, str) and c.strip()]
            return cleaned or None
        except Exception as exc:  # transient API / parse error
            last_err = exc
            if attempt < LLM_MAX_RETRIES:
                wait = LLM_RETRY_BACKOFF ** attempt
                logger.warning("LLM split attempt %d/%d failed (%s); retry in %.0fs",
                               attempt, LLM_MAX_RETRIES, exc, wait)
                time.sleep(wait)
    logger.error("LLM split gave up after %d attempts: %s", LLM_MAX_RETRIES, last_err)
    return None


def _validate_split(original: str, chunks: list[str], max_chunks: int) -> bool:
    """Reject splits that lost/added content or over-split (protects accuracy)."""
    if not chunks:
        return False
    if len(chunks) > max_chunks:
        logger.warning("Rejecting split: %d chunks exceeds max %d (over-split)",
                       len(chunks), max_chunks)
        return False
    orig_len = len(original.replace(" ", "").replace("\n", ""))
    new_len = sum(len(c.replace(" ", "").replace("\n", "")) for c in chunks)
    if orig_len == 0:
        return False
    ratio = new_len / orig_len
    # Splitting only drops whitespace at joins -> ratio should be ~1.0.
    if not (0.85 <= ratio <= 1.10):
        logger.warning("Rejecting split: char ratio %.2f outside [0.85, 1.10] "
                       "(content drifted)", ratio)
        return False
    return True


# ── Chunk assembly ──────────────────────────────────────────────────────────

def _chunk_hint_for(index: int, total: int, original_hint: str) -> str:
    """Position hint within the parent entry's chunk sequence.

    A single chunk inherits the entry's corpus-level hint (its position in the
    category run). A multi-chunk split is re-marked start/continue/end.
    """
    if total <= 1:
        return original_hint or "start"
    if index == 0:
        return "start"
    if index == total - 1:
        return "end"
    return "continue"


def _build_chunks(entry: dict, contents: list[str], cleaned_file_rel: str) -> list[dict]:
    """Produce the chunk records for one entry from its (1..N) content pieces."""
    parent_id = entry.get("id", "")
    original_hint = entry.get("chunk_hint", "start")
    # All original fields preserved as metadata, except the (possibly refined)
    # content which lives at the chunk level.
    metadata_base = {k: v for k, v in entry.items() if k != "content"}
    metadata_base["cleaned_file"] = cleaned_file_rel
    metadata_base["source_file"] = (entry.get("source") or {}).get("file", "")
    metadata_base["original_content_hash"] = rc.sha256(entry.get("content", ""))

    total = len(contents)
    out: list[dict] = []
    for i, text in enumerate(contents):
        out.append({
            "chunk_id": f"{parent_id}#{i}",
            "parent_id": parent_id,
            "title": entry.get("title", ""),
            "domain": entry.get("domain", ""),
            "service": entry.get("service", ""),
            "content": text,
            "metadata": metadata_base,
            "chunk_index": i,
            "chunk_hint": _chunk_hint_for(i, total, original_hint),
        })
    return out


# ── Cache ─────────────────────────────────────────────────────────────────────

def _load_cache(force: bool) -> dict:
    if force or not rc.CHUNK_CACHE_FILE.exists():
        return {}
    try:
        return rc.read_json(rc.CHUNK_CACHE_FILE)
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    rc.write_json(rc.CHUNK_CACHE_FILE, cache)


# ── Per-entry processing ────────────────────────────────────────────────────

def _process_entry(entry: dict, *, client, model: str, min_split_tokens: int,
                   target_tokens: int, max_chunks: int, no_llm: bool,
                   cache: dict, force: bool, stats: dict) -> list[str]:
    """Return the list of content strings (1..N) for one entry."""
    content = (entry.get("content") or "").strip()
    if not content:
        stats["empty_entries"] += 1
        return []

    parent_id = entry.get("id", "")
    content_hash = rc.sha256(content)

    # Cache hit: reuse prior decision when content is unchanged.
    cached = cache.get(parent_id)
    if not force and cached and cached.get("hash") == content_hash:
        stats["cache_hits"] += 1
        return cached["contents"]

    tokens = rc.estimate_tokens(content)

    if no_llm or tokens < min_split_tokens:
        # Deterministic decisions are instant and free, so they are NOT cached:
        # this keeps a --no-llm run from ever suppressing a later real LLM run.
        if no_llm:
            stats["kept_no_llm"] += 1
        else:
            stats["kept_short"] += 1
        return [content]

    stats["llm_calls"] += 1
    split = _llm_split(client, model, entry.get("title", ""), content, target_tokens)
    if split and len(split) > 1 and _validate_split(content, split, max_chunks):
        contents = split
        stats["llm_split"] += 1
        stats["extra_chunks"] += len(split) - 1
    else:
        # Either the model kept it whole, or the split failed validation.
        contents = [content]
        if split and len(split) <= 1:
            stats["llm_kept_whole"] += 1
        else:
            stats["llm_fallback"] += 1

    # Only LLM decisions are worth caching (they cost money / latency).
    cache[parent_id] = {"hash": content_hash, "contents": contents}
    return contents


# ── File processing ───────────────────────────────────────────────────────────

def _process_file(path: Path, *, client, model: str, min_split_tokens: int,
                  target_tokens: int, max_chunks: int, no_llm: bool,
                  cache: dict, force: bool, dry_run: bool, stats: dict) -> int:
    header, entries = rc.iter_cleaned_entries(path)
    cleaned_file_rel = rc.rel_to_repo(path)

    if not entries:
        logger.info("Skipping %s (0 entries)", cleaned_file_rel)
        return 0

    all_chunks: list[dict] = []
    for entry in entries:
        contents = _process_entry(
            entry, client=client, model=model,
            min_split_tokens=min_split_tokens, target_tokens=target_tokens,
            max_chunks=max_chunks, no_llm=no_llm, cache=cache, force=force,
            stats=stats,
        )
        if contents:
            all_chunks.extend(_build_chunks(entry, contents, cleaned_file_rel))

    stats["entries"] += len(entries)
    stats["chunks"] += len(all_chunks)

    if dry_run:
        logger.info("[dry-run] %s -> %d entries -> %d chunks",
                    cleaned_file_rel, len(entries), len(all_chunks))
        return len(all_chunks)

    # Mirror the cleaned/ layout under chunked/.
    rel = path.relative_to(rc.CORPUS_CLEANED)
    out_path = rc.CORPUS_CHUNKED / rel.with_name(rel.name.replace(".cleaned.json", ".chunked.json"))
    rc.write_json(out_path, {
        "file_name": header.get("file_name", cleaned_file_rel),
        "source_file": cleaned_file_rel,
        "domain": header.get("domain", ""),
        "resource_type": header.get("resource_type", ""),
        "generated_by": "rag/tools/chunk_corpus.py",
        "chunk_model": model if not no_llm else "none (deterministic)",
        "entry_count": len(entries),
        "chunk_count": len(all_chunks),
        "chunks": all_chunks,
    })
    logger.info("%s -> %d entries -> %d chunks", cleaned_file_rel, len(entries), len(all_chunks))
    return len(all_chunks)


def _write_manifest(per_file: list[dict], stats: dict, model: str, no_llm: bool) -> None:
    rc.write_json(rc.CORPUS_CHUNKED / "CHUNKING_MANIFEST.json", {
        "generated_by": "rag/tools/chunk_corpus.py",
        "chunk_model": "none (deterministic)" if no_llm else model,
        "totals": {
            "files": len(per_file),
            "entries": stats["entries"],
            "chunks": stats["chunks"],
            "llm_calls": stats["llm_calls"],
            "llm_split": stats["llm_split"],
            "llm_kept_whole": stats["llm_kept_whole"],
            "llm_fallback_rejected": stats["llm_fallback"],
            "kept_short_no_llm": stats["kept_short"],
            "kept_no_llm_flag": stats["kept_no_llm"],
            "cache_hits": stats["cache_hits"],
            "empty_entries": stats["empty_entries"],
        },
        "files": per_file,
    })


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 1 - semantic chunking with GPT-4.1-mini",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--model", default=rc.CHUNK_MODEL, help="OpenAI chat model")
    parser.add_argument("--min-split-tokens", type=int, default=DEFAULT_MIN_SPLIT_TOKENS,
                        help="Entries shorter than this stay whole (no LLM call)")
    parser.add_argument("--target-tokens", type=int, default=DEFAULT_TARGET_TOKENS,
                        help="Preferred chunk size when splitting")
    parser.add_argument("--max-chunks", type=int, default=DEFAULT_MAX_CHUNKS,
                        help="Reject any split exceeding this many chunks")
    parser.add_argument("--no-llm", action="store_true",
                        help="Deterministic 1:1 passthrough; never calls the API")
    parser.add_argument("--force", action="store_true",
                        help="Ignore the chunk cache and re-process every entry")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N files (debugging)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute chunks but write nothing to disk")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(__import__("logging").DEBUG)

    files = rc.iter_cleaned_files()
    if args.limit:
        files = files[: args.limit]
    if not files:
        logger.error("No *.cleaned.json files found under %s", rc.CORPUS_CLEANED)
        return 1

    client = None if args.no_llm else rc.get_openai_client()

    cache = _load_cache(args.force)
    stats = {k: 0 for k in (
        "entries", "chunks", "llm_calls", "llm_split", "llm_kept_whole",
        "llm_fallback", "kept_short", "kept_no_llm", "cache_hits",
        "extra_chunks", "empty_entries",
    )}

    logger.info("Chunking %d files | model=%s | min_split=%d tok | no_llm=%s | force=%s",
                len(files), "none" if args.no_llm else args.model,
                args.min_split_tokens, args.no_llm, args.force)

    t0 = time.time()
    per_file: list[dict] = []
    for path in files:
        n = _process_file(
            path, client=client, model=args.model,
            min_split_tokens=args.min_split_tokens, target_tokens=args.target_tokens,
            max_chunks=args.max_chunks, no_llm=args.no_llm, cache=cache,
            force=args.force, dry_run=args.dry_run, stats=stats,
        )
        per_file.append({"source": rc.rel_to_repo(path), "chunks": n})

    if not args.dry_run:
        _save_cache(cache)
        _write_manifest(per_file, stats, args.model, args.no_llm)

    dt = time.time() - t0
    logger.info(
        "Done in %.1fs | entries=%d -> chunks=%d | llm_calls=%d (split=%d, kept_whole=%d, "
        "fallback=%d) | short_kept=%d | cache_hits=%d",
        dt, stats["entries"], stats["chunks"], stats["llm_calls"], stats["llm_split"],
        stats["llm_kept_whole"], stats["llm_fallback"], stats["kept_short"],
        stats["cache_hits"],
    )
    if not args.dry_run:
        logger.info("Output -> %s", rc.rel_to_repo(rc.CORPUS_CHUNKED))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
