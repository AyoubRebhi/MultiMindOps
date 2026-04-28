"""
Local semantic chunking via Ollama (fully offline-capable).

Ollama endpoints:
  - POST /api/generate : produce strict JSON chunk plan
  - GET  /api/tags     : health check + ensure required model exists

Public API (drop-in for ingest_qdrant.py):
  - test_connection() -> dict
  - chunk_document(content, source, doc_type, force_fallback=False) -> list[dict]
  - make_json_kb_chunk(doc) -> list[dict]
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import textwrap
import time
from collections import OrderedDict
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
_DEFAULT_MODEL = "llama3.2:3b"

_REQUEST_TIMEOUT_S = 60.0
_MAX_RETRIES = 2  # per doc (in addition to the first attempt)
_MAX_CONTENT_CHARS = 70_000  # cost/latency safeguard

_ARTIFACT_TYPES = frozenset({"terraform", "k8s", "docker", "cicd", "aws"})

_ARTIFACT_KEYWORDS: dict[str, list[str]] = {
    "terraform": ["terraform", "resource", "provider", "hcl", "module", ".tf"],
    "k8s": ["apiversion", "kubectl", "helm", "namespace", "deployment", "kind:"],
    "docker": ["dockerfile", "docker-compose", "container", "image", "from "],
    "cicd": ["pipeline", "workflow", "github actions", "jenkins", "gitlab", ".github/workflows"],
    "aws": ["aws_", "ec2", "s3", "iam", "vpc", "lambda", "cloudformation", "eks", "rds"],
}

_FRAMEWORK_KEYWORDS: dict[str, list[str]] = {
    "terraform": ["terraform", 'resource "', 'provider "', 'module "', "variable \"", ".tf "],
    "kubernetes": ["apiversion:", "kind:", "kubectl", "helm", "namespace:", "deployment:", "configmap:"],
    "docker": ["dockerfile", "docker-compose", "from ", "entrypoint ", "docker"],
    "cicd": ["pipeline:", "workflow:", ".github/workflows", "jenkins", "gitlab-ci", "circleci"],
}

_CHUNK_SYSTEM_PROMPT = textwrap.dedent(
    """\
    You are a DevSecOps expert. Your task is to semantically chunk a technical document
    for a RAG (Retrieval-Augmented Generation) knowledge base.

    INPUT:
    - Raw markdown, YAML, config files, or plain text.

    OUTPUT:
    - STRICT JSON only, exactly one object, no markdown fences, no commentary.
    - Schema MUST be:
      {
        "chunks": [
          { "text": "...", "type": "..." }
        ]
      }

    CHUNKING RULES (CRITICAL):
    1. Preserve code blocks (```...```) as atomic units — NEVER split inside them.
    2. Preserve YAML / HCL / config blocks as atomic units — avoid splitting in the middle.
    3. Split by semantic sections (headers, topics, resource blocks, function boundaries).
    4. Target chunk size: ~300–500 tokens. Hard max: ~800 tokens.
    5. If the document is longer than 400 characters, you MUST output at least 2 chunks.
    6. Do not duplicate large content across chunks.

    TYPE values (pick the closest):
      - "code"          : programming/shell code blocks
      - "config"        : Terraform HCL, Dockerfile, .env, INI/TOML, general config
      - "yaml"          : Kubernetes manifests, YAML configs
      - "security_rule" : policies, CIS rules, CVEs, guardrails
      - "prose"         : explanatory text, architecture, best practices

    JSON VALIDITY RULES:
    - Output ONLY JSON. First char must be '{' and last char must be '}'.
    - Escape newlines as \\n and quotes as \\" inside strings.
    - Ensure the JSON parses with Python json.loads().
    """
)


class _LRUCache:
    def __init__(self, max_items: int = 256):
        self._max = max(0, int(max_items))
        self._data: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()

    def get(self, key: str) -> list[dict[str, Any]] | None:
        if not self._max:
            return None
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: str, value: list[dict[str, Any]]) -> None:
        if not self._max:
            return
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)


class LocalChunkingService:
    """
    Semantic chunking via local Ollama → deterministic fallback.

    - Zero external API dependency for chunking.
    - Retries Ollama up to 2 times per document.
    - On invalid JSON / parse failure, falls back deterministically.
    """

    def __init__(
        self,
        ollama_base_url: str = _DEFAULT_OLLAMA_BASE_URL,
        model: str = _DEFAULT_MODEL,
        timeout_s: float = _REQUEST_TIMEOUT_S,
        max_retries: int = _MAX_RETRIES,
        enable_cache: bool = True,
        cache_max_items: int = 256,
        force_fallback: bool = False,
    ):
        self._base_url = (ollama_base_url or _DEFAULT_OLLAMA_BASE_URL).rstrip("/")
        self._model = (model or _DEFAULT_MODEL).strip()
        self._timeout_s = float(timeout_s)
        self._max_retries = max(0, int(max_retries))
        self._force_fallback = bool(force_fallback)
        self._cache = _LRUCache(cache_max_items) if enable_cache else _LRUCache(0)

        if self._force_fallback:
            logger.warning("[Chunking] forced fallback mode (deterministic chunking)")
        else:
            logger.info("[Chunking] LocalChunkingService ready | model=%s | url=%s", self._model, self._base_url)

    # ── Health check ─────────────────────────────────────────────────────────

    def test_connection(self) -> dict[str, Any]:
        """
        Calls GET /api/tags and verifies that `self._model` exists locally.
        Returns: {ok, provider, model, latency_ms, error}
        """
        if self._force_fallback:
            print("  [Chunking] [X] force_fallback=True -- no Ollama connectivity test")
            return {"ok": False, "provider": "none", "error": "force_fallback=True"}

        t0 = time.monotonic()
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{self._base_url}/api/tags")
            latency_ms = round((time.monotonic() - t0) * 1000)
            resp.raise_for_status()
            data = resp.json()
            models = {m.get("name", "") for m in (data.get("models") or []) if isinstance(m, dict)}
            ok = self._model in models
            if ok:
                print(f"  [Chunking] [OK] ollama OK | model={self._model} | {latency_ms}ms")
                return {"ok": True, "provider": "local", "model": self._model, "latency_ms": latency_ms}
            print(f"  [Chunking] [FAIL] ollama model missing: {self._model} | {latency_ms}ms")
            return {
                "ok": False,
                "provider": "local",
                "model": self._model,
                "latency_ms": latency_ms,
                "error": f"Model '{self._model}' not found in /api/tags",
            }
        except Exception as exc:
            latency_ms = round((time.monotonic() - t0) * 1000)
            print(f"  [Chunking] [X] ollama ERROR: {exc}")
            return {"ok": False, "provider": "local", "model": self._model, "latency_ms": latency_ms, "error": str(exc)}

    # ── Public API ───────────────────────────────────────────────────────────

    def chunk_document(
        self,
        content: str,
        source: str,
        doc_type: str,
        force_fallback: bool = False,
    ) -> list[dict[str, Any]]:
        content = (content or "").strip()
        if not content:
            return []

        if len(content) > _MAX_CONTENT_CHARS:
            logger.warning("[Chunking] '%s' truncated from %d to %d chars (safeguard)", source, len(content), _MAX_CONTENT_CHARS)
            content = content[:_MAX_CONTENT_CHARS]

        t0 = time.monotonic()
        cache_key = self._hash_doc(content, source, doc_type)
        cached = self._cache.get(cache_key)
        if cached is not None:
            latency_ms = round((time.monotonic() - t0) * 1000)
            logger.info("[Chunking] local | model=%s | chunks=%d | time=%d ms | cache=hit | source=%s", self._model, len(cached), latency_ms, source)
            return self._enrich_chunks(cached, source, doc_type, content, chunking_source="local")

        chunks, chunking_source = self._local_chunk_with_fallback(
            content,
            source,
            doc_type,
            force_fallback=force_fallback,
        )
        self._cache.put(cache_key, chunks)

        latency_ms = round((time.monotonic() - t0) * 1000)
        logger.info("[Chunking] local | model=%s | chunks=%d | time=%d ms | source=%s", self._model, len(chunks), latency_ms, source)
        if len(chunks) == 1 and len(content) > 400:
            logger.warning("[Chunking] suspicious single chunk for large doc | source=%s | len=%d", source, len(content))

        return self._enrich_chunks(chunks, source, doc_type, content, chunking_source=chunking_source)

    def make_json_kb_chunk(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        """Create one pre-built chunk from a JSON KB entry (bypasses LLM)."""
        content = (doc.get("content") or "").strip()
        if not content:
            return []

        meta = doc.get("metadata", {}) or {}
        source = doc.get("path", "unknown")
        doc_type = doc.get("doc_type", "general")
        artifact = (
            meta.get("artifact_type")
            or doc.get("artifact_type")
            or self._infer_artifact_type(content, doc_type)
        )
        cloud = meta.get("cloud_provider") or self._infer_cloud_provider(content, doc_type)
        framework = self._infer_framework(content, doc_type)
        concept = meta.get("concept", "")
        title = (
            concept
            or meta.get("entry_id", "")
            or doc.get("id", "")
            or f"{source} — KB entry"
        )

        return [{
            "content": content,
            "title": title,
            "section_title": title,
            "chunk_type": "prose",
            "keywords": self._extract_keywords(content),
            "context_tag": doc_type,
            "use_case": self._infer_use_case(content, "prose", doc_type),
            "complexity": self._infer_complexity(content, "prose"),
            "source": source,
            "doc_type": doc_type,
            "artifact_type": artifact,
            "cloud_provider": cloud,
            "framework": framework,
            "chunk_index": 0,
            "chunking_source": "json_kb",
            "source_type": "json_kb",
            "kb_section": meta.get("kb_section", doc.get("kb_section", doc_type)),
            "hierarchy_path": meta.get("hierarchy_path", ""),
            "entry_id": meta.get("entry_id", doc.get("id", "")),
        }]

    # ── Ollama chunking + fallback ────────────────────────────────────────────

    def _local_chunk_with_fallback(
        self,
        content: str,
        source: str,
        doc_type: str,
        force_fallback: bool = False,
    ) -> tuple[list[dict[str, Any]], str]:
        if self._force_fallback or force_fallback:
            return self._fallback_chunk(content, source, doc_type), "fallback"

        user_prompt = (
            f"Document source: {source}\n"
            f"Document type: {doc_type}\n\n"
            f"--- DOCUMENT ---\n{content}\n--- END DOCUMENT ---\n\n"
            "Chunk this document following the rules.\n"
            "REMINDER: Output ONLY a raw JSON object. First char '{', last char '}'."
        )

        last_raw: str | None = None
        last_exc: Exception | None = None

        for attempt in range(0, self._max_retries + 1):
            try:
                raw = self._call_ollama(system=_CHUNK_SYSTEM_PROMPT, prompt=user_prompt)
                last_raw = raw
                chunks = self._parse_response(raw, source, doc_type)
                if chunks:
                    return chunks, "local"
                logger.warning("[Chunking] invalid/empty JSON from ollama | attempt=%d/%d | source=%s", attempt + 1, self._max_retries + 1, source)
            except Exception as exc:
                last_exc = exc
                logger.warning("[Chunking] ollama call failed | attempt=%d/%d | source=%s | err=%s", attempt + 1, self._max_retries + 1, source, exc)

            # brief backoff
            if attempt < self._max_retries:
                time.sleep(2.0 * (attempt + 1))

        preview = (last_raw or "").strip().replace("\n", "\\n")[:600]
        logger.error("[Chunking] falling back to deterministic chunking | source=%s | err=%s | preview=%s", source, last_exc, preview)
        return self._fallback_chunk(content, source, doc_type), "fallback"

    def _call_ollama(self, system: str, prompt: str) -> str:
        payload = {
            "model": self._model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
            },
        }
        t0 = time.monotonic()
        with httpx.Client(timeout=self._timeout_s) as client:
            resp = client.post(f"{self._base_url}/api/generate", json=payload)
        latency_ms = round((time.monotonic() - t0) * 1000)
        if resp.status_code != 200:
            body = resp.text[:800]
            raise RuntimeError(f"Ollama /api/generate failed (HTTP {resp.status_code}) in {latency_ms}ms: {body}")
        data = resp.json()
        return (data.get("response") or "").strip()

    # ── Parsing / normalization ──────────────────────────────────────────────

    def _parse_response(self, raw: str, source: str, doc_type: str) -> list[dict[str, Any]]:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned, flags=re.MULTILINE).strip()

        try:
            data = json.loads(cleaned)
            chunks = self._validate_and_normalize(data, source, doc_type)
            if chunks:
                return chunks
        except json.JSONDecodeError as exc:
            logger.warning("[Chunking] invalid JSON for '%s': %s", source, exc)

        # salvage if model wrapped JSON in stray text
        try:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group())
                chunks = self._validate_and_normalize(data, source, doc_type)
                if chunks:
                    return chunks
        except Exception:
            pass

        return []

    def _validate_and_normalize(self, data: Any, source: str, doc_type: str) -> list[dict[str, Any]]:
        if not isinstance(data, dict):
            return []
        raw_chunks = data.get("chunks")
        if not isinstance(raw_chunks, list) or not raw_chunks:
            return []

        valid_types = {"code", "config", "yaml", "security_rule", "prose"}
        normalized: list[dict[str, Any]] = []

        for item in raw_chunks:
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("content") or ""
            if not str(text).strip():
                continue

            t = (item.get("type") or item.get("chunk_type") or "").strip()
            chunk_type = t if t in valid_types else self._detect_chunk_type(str(text))
            title = (item.get("section") or item.get("title") or "").strip() or f"{source} — section"
            normalized.append({
                "content": str(text).strip(),
                "title": title,
                "keywords": item.get("keywords") or [],
                "chunk_type": chunk_type,
                "use_case": (item.get("use_case") or "").strip(),
                "context_tag": doc_type,
            })

        return normalized

    # ── Enrichment (keeps pipeline compatibility) ────────────────────────────

    def _enrich_chunks(
        self,
        chunks: list[dict[str, Any]],
        source: str,
        doc_type: str,
        original_content: str,
        chunking_source: str,
    ) -> list[dict[str, Any]]:
        artifact = self._infer_artifact_type(original_content, doc_type)
        framework = self._infer_framework(original_content, doc_type)
        cloud = self._infer_cloud_provider(original_content, doc_type)

        for idx, chunk in enumerate(chunks):
            chunk["source"] = source
            chunk["doc_type"] = doc_type
            chunk["artifact_type"] = artifact
            chunk["cloud_provider"] = cloud
            chunk["framework"] = framework
            chunk["chunk_index"] = idx
            chunk["chunking_source"] = chunking_source

            section = chunk.get("title") or f"{source} — chunk {idx + 1}"
            chunk["section_title"] = section
            chunk.setdefault("title", section)
            chunk.setdefault("chunk_type", self._detect_chunk_type(chunk.get("content", "")))
            chunk.setdefault("context_tag", doc_type)
            chunk.setdefault("keywords", [])
            chunk.setdefault("use_case", self._infer_use_case(
                chunk.get("content", ""), chunk.get("chunk_type", "prose"), doc_type
            ))
            chunk["complexity"] = self._infer_complexity(
                chunk.get("content", ""), chunk.get("chunk_type", "prose")
            )

        return chunks

    # ── Deterministic fallback chunker ───────────────────────────────────────

    def _fallback_chunk(
        self,
        content: str,
        source: str,
        doc_type: str,
        max_chars: int = 1600,
        overlap_ratio: float = 0.15,
    ) -> list[dict[str, Any]]:
        logger.info("[Chunking] deterministic fallback | source='%s'", source)
        chunks: list[dict[str, Any]] = []

        prose_parts: list[tuple[str, str]] = []
        code_pattern = re.compile(r"(```[\w]*\n?)(.*?)(```)", re.DOTALL)
        last_end = 0
        for m in code_pattern.finditer(content):
            prose_before = content[last_end:m.start()].strip()
            code_text = m.group(0).strip()
            prose_parts.append((prose_before, code_text))
            last_end = m.end()
        trailing_prose = content[last_end:].strip()

        def _add(text: str, title: str) -> None:
            text = text.strip()
            if not text:
                return
            chunks.append({
                "content": text,
                "title": title or f"{source} — extract",
                "chunk_type": self._detect_chunk_type(text),
                "keywords": self._extract_keywords(text),
                "context_tag": doc_type,
            })

        if prose_parts:
            for prose_before, code_text in prose_parts:
                if prose_before:
                    for st, sb in self._split_by_markdown_sections(prose_before):
                        for block in self._split_with_overlap(sb, max_chars, overlap_ratio):
                            _add(block, st or f"{source} — prose")
                _add(code_text, f"{source} — code block")
            if trailing_prose:
                for st, sb in self._split_by_markdown_sections(trailing_prose):
                    for block in self._split_with_overlap(sb, max_chars, overlap_ratio):
                        _add(block, st or f"{source} — prose")
        else:
            for st, sb in self._split_by_markdown_sections(content):
                for block in self._split_with_overlap(sb, max_chars, overlap_ratio):
                    _add(block, st or f"{source} — extract")

        if len(chunks) == 1 and len(content) > 400:
            single = chunks[0]["content"]
            mid = len(single) // 2
            split_at = single.rfind("\n", 0, mid) or mid
            overlap = int(max_chars * overlap_ratio)
            first = single[:split_at + overlap].strip()
            second = single[max(0, split_at - overlap):].strip()
            if first and second:
                chunks = []
                _add(first, f"{source} — part 1")
                _add(second, f"{source} — part 2")

        return chunks

    # ── Utilities ────────────────────────────────────────────────────────────

    @staticmethod
    def _hash_doc(content: str, source: str, doc_type: str) -> str:
        h = hashlib.sha256()
        h.update(doc_type.encode("utf-8", errors="ignore"))
        h.update(b"\0")
        h.update(source.encode("utf-8", errors="ignore"))
        h.update(b"\0")
        h.update(content.encode("utf-8", errors="ignore"))
        return h.hexdigest()

    @staticmethod
    def _infer_artifact_type(content: str, doc_type: str) -> str:
        doc_lower = (doc_type or "").lower()
        for artifact in ("terraform", "k8s", "docker", "cicd", "aws"):
            if artifact in doc_lower:
                return artifact
        sample = (content or "")[:2000].lower()
        for artifact, keywords in _ARTIFACT_KEYWORDS.items():
            if any(kw in sample for kw in keywords):
                return artifact
        return doc_type if doc_type in _ARTIFACT_TYPES else "general"

    @staticmethod
    def _split_by_markdown_sections(content: str) -> list[tuple[str, str]]:
        lines = (content or "").splitlines(keepends=True)
        sections: list[tuple[str, str]] = []
        current_title = ""
        current_body: list[str] = []
        for line in lines:
            if re.match(r"^#{1,3}\s+", line):
                if current_body:
                    sections.append((current_title, "".join(current_body)))
                current_title = line.strip("# \n")
                current_body = []
            else:
                current_body.append(line)
        if current_body:
            sections.append((current_title, "".join(current_body)))
        return sections if sections else [("", content)]

    @staticmethod
    def _split_with_overlap(text: str, max_chars: int, overlap_ratio: float = 0.15) -> list[str]:
        if len(text) <= max_chars:
            return [text] if text.strip() else []
        overlap_chars = max(0, int(max_chars * overlap_ratio))
        blocks: list[str] = []
        start = 0
        while start < len(text):
            end = start + max_chars
            if end < len(text):
                nl = text.rfind("\n", start, end)
                if nl > start:
                    end = nl + 1
            block = text[start:end].strip()
            if block:
                blocks.append(block)
            next_start = max(end - overlap_chars, start + 1)
            start = next_start
        return blocks

    @staticmethod
    def _infer_framework(content: str, doc_type: str) -> str:
        dl = (doc_type or "").lower()
        if "terraform" in dl:
            return "terraform"
        if any(x in dl for x in ("k8s", "kubernetes")):
            return "kubernetes"
        if "docker" in dl:
            return "docker"
        if any(x in dl for x in ("cicd", "pipeline", "ci")):
            return "cicd"
        sample = (content or "")[:3000].lower()
        scores = {fw: sum(1 for kw in kws if kw in sample) for fw, kws in _FRAMEWORK_KEYWORDS.items()}
        best = max(scores, key=lambda k: scores[k])
        return best if scores[best] > 0 else "general"

    @staticmethod
    def _infer_cloud_provider(content: str, doc_type: str) -> str:
        dl = (doc_type or "").lower()
        if "aws" in dl:
            return "aws"
        if any(x in dl for x in ("gcp", "google")):
            return "gcp"
        if "azure" in dl:
            return "azure"
        sample = (content or "")[:3000].lower()
        aws = sum(1 for kw in ("aws_", "ec2", "s3", "iam", "vpc", "lambda", "cloudformation", "eks", "rds", "dynamodb") if kw in sample)
        gcp = sum(1 for kw in ("gke", "gcs", "pubsub", "bigquery", "gcloud") if kw in sample)
        az = sum(1 for kw in ("azurerm", "aks", "azure", "microsoft") if kw in sample)
        top = max(aws, gcp, az)
        if top == 0:
            return "general"
        if aws == gcp == az and top > 0:
            return "multi-cloud"
        if aws >= gcp and aws >= az:
            return "aws"
        return "gcp" if gcp >= az else "azure"

    @staticmethod
    def _detect_chunk_type(text: str) -> str:
        t = (text or "").lower()
        if "```" in t:
            return "code"
        if any(x in t for x in ("apiversion:", "kind:", "metadata:", "spec:", "---\n")):
            return "yaml"
        if any(x in t for x in ("resource \"", "provider \"", "terraform {", "variable \"", "output \"")):
            return "config"
        if any(x in t for x in ("cis ", "cve-", "policy", "deny", "allow", "baseline", "benchmark")):
            return "security_rule"
        return "prose"

    @staticmethod
    def _infer_use_case(content: str, chunk_type: str, doc_type: str) -> str:
        dl = (doc_type or "").lower()
        c = (content or "").lower()

        if "iam" in dl or any(x in c for x in ("iam", "role", "policy", "permission", "serviceaccount")):
            return "iam"
        if "network" in dl or any(x in c for x in ("vpc", "subnet", "ingress", "egress", "load balancer", "route", "dns")):
            return "networking"
        if "monitor" in dl or any(x in c for x in ("prometheus", "grafana", "logs", "logging", "alert", "metrics", "tracing")):
            return "monitoring"
        if "ci" in dl or "cicd" in dl or any(x in c for x in ("github actions", "jenkins", "gitlab", "workflow", "pipeline")):
            return "ci-cd"
        if "storage" in dl or any(x in c for x in ("s3", "bucket", "volume", "pvc", "pv", "efs", "ebs", "rds", "database")):
            return "storage"
        if chunk_type == "security_rule" or "security" in dl or any(x in c for x in ("hardening", "vulnerability", "scan", "cve-", "compliance")):
            return "security"
        if any(x in dl for x in ("terraform", "k8s", "kubernetes", "docker", "deploy")):
            return "deployment"
        return "infrastructure"

    @staticmethod
    def _infer_complexity(content: str, chunk_type: str) -> str:
        t = (content or "")
        if chunk_type in ("code", "config", "yaml") and len(t) > 1600:
            return "high"
        if len(t) > 1200:
            return "medium"
        return "low"

    @staticmethod
    def _extract_keywords(text: str, max_keywords: int = 8) -> list[str]:
        raw = re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{2,}", text or "")
        stop = {
            "the", "and", "for", "with", "that", "this", "from", "are", "was", "were",
            "into", "your", "you", "not", "can", "will", "have", "has", "had", "its",
            "aws", "kubernetes", "terraform", "docker", "pipeline",
        }
        seen: set[str] = set()
        out: list[str] = []
        for w in raw:
            lw = w.lower()
            if lw in stop:
                continue
            if lw in seen:
                continue
            seen.add(lw)
            out.append(lw)
            if len(out) >= max_keywords:
                break
        return out

