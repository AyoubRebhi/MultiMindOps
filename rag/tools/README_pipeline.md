# DevSecOps RAG Ingestion Pipeline (`rag/tools/`)

Production ingestion pipeline that turns the **cleaned** knowledge corpus into a
queryable Qdrant collection.

```
rag/corpus_cleaned/                     (input — already cleaned/normalized/deduped)
        │
        ▼  chunk_corpus.py   ── OpenAI gpt-4.1-mini (semantic refinement only)
rag/corpus_chunked/*.chunked.json
        │
        ▼  embed_corpus.py   ── OpenAI text-embedding-3-small (1536-dim, batched)
rag/corpus_embedded/embeddings.jsonl
        │
        ▼  index_qdrant.py   ── Qdrant upsert (idempotent UUID5 point ids)
Qdrant collection: devsecops_kb
```

> This is a clean-room replacement for the legacy `rag/scripts/` ingester
> (`ingest_qdrant.py`, `ingest_templates.py`, `terraform_scraper.py`), which used
> Ollama embeddings and raw-file scraping. **Do not mix the two.** The new
> pipeline reads only `rag/corpus_cleaned/` and uses OpenAI models.

## Prerequisites

```bash
pip install openai qdrant-client python-dotenv   # tqdm/tiktoken optional
```

- `OPENAI_API_KEY` — required for Phase 1 (chunking) and Phase 2 (embedding).
  Read from the environment or the repo-root `.env`. Never hardcoded.
- A running Qdrant for Phase 3: `docker run -p 6333:6333 qdrant/qdrant`
  (override the URL with `--url` or the `QDRANT_URL` env var).
- `tiktoken` is optional; if absent, token counts use a ~4-chars/token estimate.

## Phase 1 — `chunk_corpus.py` (semantic chunking)

Refines each cleaned entry into 1..N retrieval-sized chunks. It does **not**
re-clean or rewrite content.

- Entries below `--min-split-tokens` (default **512**) are kept whole with **no
  API call** — the corpus was authored as coherent ~400–600 token units, so only
  genuinely long, multi-topic entries are sent to the model.
- Longer entries go to **gpt-4.1-mini** (temperature 0, JSON mode) which splits on
  natural boundaries while preserving every technical fact verbatim.
- Every split is **validated** (chunk count + character-preservation band). If the
  model drops or invents text, the split is discarded and the original entry is
  emitted unchanged — **technical accuracy is never traded for chunking**.
- A content-hash cache (`corpus_chunked/.chunk_cache.json`) makes re-runs cheap
  and idempotent. Only LLM decisions are cached, so a `--no-llm` run never
  suppresses a later real run.

```bash
python rag/tools/chunk_corpus.py            # full run (uses cache)
python rag/tools/chunk_corpus.py --no-llm   # deterministic 1:1, zero API cost
python rag/tools/chunk_corpus.py --force    # ignore cache, re-chunk everything
python rag/tools/chunk_corpus.py --limit 3 --dry-run -v
```

Output: one `*.chunked.json` per source file (mirrors the folder layout) +
`CHUNKING_MANIFEST.json`. Each chunk carries `chunk_id`, `parent_id`, `title`,
`domain`, `service`, `content`, full original fields under `metadata`,
`chunk_index`, and `chunk_hint`.

## Phase 2 — `embed_corpus.py` (embeddings)

Embeds every chunk with **text-embedding-3-small** in batches.

- **Incremental / idempotent**: keyed by `id` + text hash. Re-runs embed only new
  or changed chunks; `--force` re-embeds all.
- Validates that every vector is exactly **1536** dims before writing.

```bash
python rag/tools/embed_corpus.py                  # incremental
python rag/tools/embed_corpus.py --batch-size 64  # tune batching
python rag/tools/embed_corpus.py --force
python rag/tools/embed_corpus.py --dry-run        # count work, no API calls
```

Output: `rag/corpus_embedded/embeddings.jsonl` — one record per chunk:
`{ id, embedding, text, metadata{ domain, service, category, resource_type,
importance, source, chunk_id, parent_id, title, cloud_provider, tags,
chunk_index, chunk_hint } }`.

## Phase 3 — `index_qdrant.py` (Qdrant indexing)

Upserts the embeddings into the **`devsecops_kb`** collection (1536-dim, Cosine).

- **Idempotent**: point ids are `uuid5(chunk_id)`, so re-running overwrites the
  same points instead of duplicating.
- Creates keyword payload indexes for `domain`, `service`, `category`,
  `resource_type`, `importance`, `cloud_provider` for fast filtered search.
- Payload includes those fields plus `source`, `chunk_id`, `parent_id`, `title`,
  `tags`, `chunk_index`, `chunk_hint`, and the chunk `text`.

```bash
python rag/tools/index_qdrant.py                 # upsert
python rag/tools/index_qdrant.py --recreate      # drop + recreate, then upsert
python rag/tools/index_qdrant.py --url http://localhost:6333
python rag/tools/index_qdrant.py --dry-run       # validate input only
```

## End-to-end

```bash
python rag/tools/chunk_corpus.py
python rag/tools/embed_corpus.py
python rag/tools/index_qdrant.py --recreate
```

Every stage is re-runnable. Re-run from Phase 1 whenever `rag/corpus_cleaned/`
changes; the caches/hashes ensure only what actually changed is recomputed.

## Design notes

- **Separation of concerns**: each phase reads the previous phase's on-disk
  artifact, so stages can be run, inspected, and re-run independently.
- **Shared helpers** live in `_rag_common.py` (paths, OpenAI client, hashing,
  token estimate, JSON/JSONL IO). No imports from `rag/scripts/` or `backend/`.
- **`evaluation_queries.json`** in `corpus_cleaned/` is intentionally **not**
  ingested — it is the recall@k eval set, not knowledge content.
