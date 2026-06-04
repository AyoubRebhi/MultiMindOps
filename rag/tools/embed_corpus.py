#!/usr/bin/env python3
"""Phase 2 - Embedding generation for the chunked corpus (OpenAI text-embedding-3-small).

    rag/corpus_chunked/  --(this script)-->  rag/corpus_embedded/embeddings.jsonl

What it does
------------
Reads every ``*.chunked.json`` produced by Phase 1, embeds each chunk's text
with ``text-embedding-3-small`` (1536-dim), and writes one JSONL record per
chunk. Embeddings are produced in batches for cost/throughput efficiency.

Each JSONL record:

    {
      "id": "<chunk_id>",
      "embedding": [ ... 1536 floats ... ],
      "text": "<chunk content>",
      "metadata": {
        "domain", "service", "category", "resource_type", "importance",
        "source",            # source corpus file path
        "chunk_id", "parent_id", "title", "cloud_provider", "tags",
        "chunk_index", "chunk_hint"
      }
    }

The required minimal metadata keys (domain/service/resource_type/importance/
source) are always present; the extra keys are carried through so Phase 3 can
build a rich Qdrant payload without re-reading the chunked files.

Idempotency
-----------
The output is keyed by ``id`` with a stored text hash. On re-run only new or
changed chunks are embedded; everything else is preserved. Use ``--force`` to
re-embed everything from scratch.

Usage
-----
    python rag/tools/embed_corpus.py                 # incremental
    python rag/tools/embed_corpus.py --force         # re-embed all
    python rag/tools/embed_corpus.py --batch-size 64 # tune batch size
    python rag/tools/embed_corpus.py --dry-run       # count work, no API calls
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _rag_common as rc  # noqa: E402

logger = rc.setup_logging("embed_corpus")

DEFAULT_BATCH_SIZE = 128
EMBED_MAX_RETRIES = 5
EMBED_RETRY_BACKOFF = 2.0  # seconds, exponential


# ── Gather chunks ─────────────────────────────────────────────────────────────

def _iter_chunk_files() -> list[Path]:
    return sorted(rc.CORPUS_CHUNKED.rglob("*.chunked.json"))


def _build_record_stub(chunk: dict) -> dict:
    """Make the JSONL record shell (without the embedding vector)."""
    meta = chunk.get("metadata", {}) or {}
    source = (meta.get("source") or {}).get("file", "") or meta.get("source_file", "")
    return {
        "id": chunk["chunk_id"],
        "text": chunk.get("content", ""),
        "metadata": {
            "domain": chunk.get("domain", "") or meta.get("domain", ""),
            "service": chunk.get("service", "") or meta.get("service", ""),
            "category": meta.get("category", ""),
            "resource_type": meta.get("resource_type", ""),
            "importance": meta.get("importance", ""),
            "source": source,
            "chunk_id": chunk["chunk_id"],
            "parent_id": chunk.get("parent_id", ""),
            "title": chunk.get("title", ""),
            "cloud_provider": meta.get("cloud_provider", ""),
            "tags": meta.get("tags", []),
            "chunk_index": chunk.get("chunk_index", 0),
            "chunk_hint": chunk.get("chunk_hint", ""),
        },
    }


def _load_chunks() -> list[dict]:
    """All chunk records (stubs) across every chunked file, de-duplicated by id."""
    seen: set[str] = set()
    records: list[dict] = []
    for path in _iter_chunk_files():
        data = rc.read_json(path)
        for chunk in data.get("chunks", []) or []:
            cid = chunk.get("chunk_id")
            if not cid or cid in seen:
                if cid in seen:
                    logger.warning("Duplicate chunk_id skipped: %s", cid)
                continue
            seen.add(cid)
            records.append(_build_record_stub(chunk))
    return records


# ── Existing embeddings (incremental) ──────────────────────────────────────────

def _load_existing() -> dict[str, dict]:
    existing: dict[str, dict] = {}
    for rec in rc.read_jsonl(rc.EMBEDDINGS_FILE):
        rid = rec.get("id")
        if rid:
            existing[rid] = rec
    return existing


# ── Embedding with retry ────────────────────────────────────────────────────

def _embed_batch(client, model: str, texts: list[str]) -> list[list[float]]:
    last_err: Exception | None = None
    for attempt in range(1, EMBED_MAX_RETRIES + 1):
        try:
            resp = client.embeddings.create(model=model, input=texts)
            # Preserve request order (API returns .index, sort to be safe).
            items = sorted(resp.data, key=lambda d: d.index)
            return [it.embedding for it in items]
        except Exception as exc:
            last_err = exc
            if attempt < EMBED_MAX_RETRIES:
                wait = EMBED_RETRY_BACKOFF ** attempt
                logger.warning("Embed batch attempt %d/%d failed (%s); retry in %.0fs",
                               attempt, EMBED_MAX_RETRIES, exc, wait)
                time.sleep(wait)
    raise RuntimeError(f"Embedding failed after {EMBED_MAX_RETRIES} attempts: {last_err}")


def _batched(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 2 - batch embeddings with text-embedding-3-small",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--model", default=rc.EMBED_MODEL, help="OpenAI embedding model")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="Texts per embedding request")
    parser.add_argument("--out", default=str(rc.EMBEDDINGS_FILE),
                        help="Output JSONL path")
    parser.add_argument("--force", action="store_true",
                        help="Re-embed every chunk (ignore existing output)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be embedded; no API calls, no write")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(__import__("logging").DEBUG)

    out_path = Path(args.out)

    records = _load_chunks()
    if not records:
        logger.error("No chunks found under %s. Run chunk_corpus.py first.",
                     rc.rel_to_repo(rc.CORPUS_CHUNKED))
        return 1

    existing = {} if args.force else _load_existing()

    # Decide which records still need embedding (new id, or changed text).
    to_embed: list[dict] = []
    reused: dict[str, dict] = {}
    for rec in records:
        prev = existing.get(rec["id"])
        if prev and prev.get("text_hash") == rc.sha256(rec["text"]) and prev.get("embedding"):
            reused[rec["id"]] = prev
        else:
            to_embed.append(rec)

    logger.info("Chunks=%d | already embedded=%d | to embed=%d | model=%s | batch=%d",
                len(records), len(reused), len(to_embed), args.model, args.batch_size)

    if args.dry_run:
        logger.info("[dry-run] would embed %d chunks in %d batches; no API calls made.",
                    len(to_embed), (len(to_embed) + args.batch_size - 1) // max(args.batch_size, 1))
        return 0

    if to_embed:
        client = rc.get_openai_client()
        t0 = time.time()
        done = 0
        for batch in _batched(to_embed, args.batch_size):
            vectors = _embed_batch(client, args.model, [r["text"] for r in batch])
            if len(vectors) != len(batch):
                logger.error("Batch size mismatch: got %d vectors for %d inputs",
                             len(vectors), len(batch))
                return 1
            for rec, vec in zip(batch, vectors):
                if len(vec) != rc.EMBED_DIM:
                    logger.error("Unexpected embedding dim %d (expected %d) for %s",
                                 len(vec), rc.EMBED_DIM, rec["id"])
                    return 1
                rec["embedding"] = vec
                rec["text_hash"] = rc.sha256(rec["text"])
            done += len(batch)
            logger.info("Embedded %d/%d", done, len(to_embed))
        logger.info("Embedding API time: %.1fs (%.1f chunks/s)",
                    time.time() - t0, done / max(time.time() - t0, 1e-6))

    # Merge reused + newly embedded, in stable chunk order.
    by_id = dict(reused)
    for rec in to_embed:
        if "embedding" in rec:
            by_id[rec["id"]] = rec
    final = [by_id[r["id"]] for r in records if r["id"] in by_id]

    rc.write_jsonl(out_path, final)
    logger.info("Wrote %d embedding records -> %s", len(final), rc.rel_to_repo(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
