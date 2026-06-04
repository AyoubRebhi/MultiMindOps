#!/usr/bin/env python3
"""Phase 3 - Index the embedded corpus into Qdrant.

    rag/corpus_embedded/embeddings.jsonl  --(this script)-->  Qdrant: devsecops_kb

What it does
------------
Reads the JSONL produced by Phase 2 and upserts every record into a local
Qdrant collection as (vector + payload + chunk text). Point IDs are derived
deterministically from ``chunk_id`` (UUID5), so re-running the script overwrites
the same points instead of duplicating them - the indexing step is idempotent.

Collection
----------
  * name        : devsecops_kb
  * vector size : 1536 (text-embedding-3-small)
  * distance    : Cosine

Payload (per point)
-------------------
  domain, service, category, resource_type, importance,
  source (corpus file), chunk_id, parent_id, title, cloud_provider, tags,
  chunk_index, chunk_hint, text

Keyword payload indexes are created for the common filter fields
(domain, service, category, resource_type, importance, cloud_provider) so
filtered semantic search is fast.

Usage
-----
    python rag/tools/index_qdrant.py                  # upsert into existing collection
    python rag/tools/index_qdrant.py --recreate       # drop + recreate, then upsert
    python rag/tools/index_qdrant.py --url http://localhost:6333
    python rag/tools/index_qdrant.py --dry-run        # validate input, no Qdrant writes
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _rag_common as rc  # noqa: E402

logger = rc.setup_logging("index_qdrant")

DEFAULT_BATCH_SIZE = 256
# Payload fields that benefit from a keyword index for filtered retrieval.
INDEXED_PAYLOAD_FIELDS = (
    "domain", "service", "category", "resource_type", "importance", "cloud_provider",
)
# Deterministic namespace so the same chunk_id always maps to the same point id.
_POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "devsecops_kb/chunk")


def _point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, chunk_id))


def _get_client(url: str):
    try:
        from qdrant_client import QdrantClient  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "The 'qdrant-client' package is required. Install it: pip install qdrant-client"
        ) from exc
    return QdrantClient(url=url)


def _ensure_collection(client, collection: str, recreate: bool) -> None:
    from qdrant_client.models import Distance, VectorParams  # type: ignore

    exists = client.collection_exists(collection)
    if exists and recreate:
        logger.info("--recreate: deleting existing collection '%s'", collection)
        client.delete_collection(collection)
        exists = False

    if not exists:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=rc.EMBED_DIM, distance=Distance.COSINE),
        )
        logger.info("Created collection '%s' (dim=%d, Cosine)", collection, rc.EMBED_DIM)
    else:
        logger.info("Using existing collection '%s'", collection)

    _ensure_payload_indexes(client, collection)


def _ensure_payload_indexes(client, collection: str) -> None:
    from qdrant_client.models import PayloadSchemaType  # type: ignore

    for field in INDEXED_PAYLOAD_FIELDS:
        try:
            client.create_payload_index(
                collection_name=collection,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception as exc:
            # Already-exists is the common, harmless case.
            logger.debug("Payload index '%s' not (re)created: %s", field, exc)


def _build_point(record: dict):
    from qdrant_client.models import PointStruct  # type: ignore

    meta = record.get("metadata", {}) or {}
    chunk_id = record["id"]
    payload = {
        "domain": meta.get("domain", ""),
        "service": meta.get("service", ""),
        "category": meta.get("category", ""),
        "resource_type": meta.get("resource_type", ""),
        "importance": meta.get("importance", ""),
        "cloud_provider": meta.get("cloud_provider", ""),
        "source": meta.get("source", ""),
        "chunk_id": chunk_id,
        "parent_id": meta.get("parent_id", ""),
        "title": meta.get("title", ""),
        "tags": meta.get("tags", []),
        "chunk_index": meta.get("chunk_index", 0),
        "chunk_hint": meta.get("chunk_hint", ""),
        "text": record.get("text", ""),
    }
    return PointStruct(id=_point_id(chunk_id), vector=record["embedding"], payload=payload)


def _batched(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 3 - index embeddings into Qdrant (devsecops_kb)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--url", default=os.environ.get("QDRANT_URL", rc.DEFAULT_QDRANT_URL),
                        help="Qdrant base URL (env QDRANT_URL or http://localhost:6333)")
    parser.add_argument("--collection", default=rc.QDRANT_COLLECTION, help="Collection name")
    parser.add_argument("--embeddings", default=str(rc.EMBEDDINGS_FILE),
                        help="Input embeddings JSONL")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="Points per upsert request")
    parser.add_argument("--recreate", action="store_true",
                        help="Drop and recreate the collection before indexing")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate the input file; do not connect or write")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(__import__("logging").DEBUG)

    emb_path = Path(args.embeddings)
    records = list(rc.read_jsonl(emb_path))
    if not records:
        logger.error("No embeddings found at %s. Run embed_corpus.py first.",
                     rc.rel_to_repo(emb_path))
        return 1

    # Validate vectors before touching Qdrant.
    bad = [r.get("id") for r in records
           if not r.get("embedding") or len(r["embedding"]) != rc.EMBED_DIM]
    if bad:
        logger.error("%d records have missing/wrong-dim embeddings (expected %d). "
                     "Examples: %s", len(bad), rc.EMBED_DIM, bad[:3])
        return 1

    logger.info("Loaded %d embedding records from %s", len(records), rc.rel_to_repo(emb_path))

    if args.dry_run:
        logger.info("[dry-run] would upsert %d points into '%s' at %s (no connection made)",
                    len(records), args.collection, args.url)
        return 0

    client = _get_client(args.url)
    try:
        client.get_collections()  # health probe
    except Exception as exc:
        logger.error("Cannot reach Qdrant at %s: %s", args.url, exc)
        logger.error("Is Qdrant running?  docker run -p 6333:6333 qdrant/qdrant")
        return 1
    logger.info("Connected to Qdrant at %s", args.url)

    _ensure_collection(client, args.collection, args.recreate)

    points = [_build_point(r) for r in records]
    t0 = time.time()
    upserted = 0
    for batch in _batched(points, args.batch_size):
        client.upsert(collection_name=args.collection, points=batch)
        upserted += len(batch)
        logger.info("Upserted %d/%d", upserted, len(points))

    count = client.count(collection_name=args.collection, exact=True).count
    logger.info("Done in %.1fs | upserted=%d | collection '%s' now holds %d points",
                time.time() - t0, upserted, args.collection, count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
