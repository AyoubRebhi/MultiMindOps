"""
RAG Evaluation Framework for the DevSecOps Knowledge Base.

Metrics
-------
Retrieval : Precision@k, Recall@k, Hit Rate@k
Generation: Faithfulness, Relevance, Correctness  (LLM-scored, 0–1)
Context   : Coverage, Redundancy
Global    : Weighted RAG score  (0–1)

LLM judge
---------
Primary:  Lightning AI (LIGHTNING_API_KEY) — 70B model for reasoning quality
Fallback: Groq                             — explicit WARNING log on switch
Neither:  Heuristic token-overlap scoring  — WARNING log when used

Usage
-----
    evaluator = RAGEvaluator(qdrant, embedder)
    result    = evaluator.evaluate("terraform aws vpc")
    report    = evaluator.run_benchmark()
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Benchmark dataset ─────────────────────────────────────────────────────────

BENCHMARK_QUERIES: list[dict[str, Any]] = [
    {
        "query": "terraform aws vpc",
        "expected_keywords": ["vpc", "terraform", "subnet", "cidr", "aws"],
        "expected_doc_types": ["terraform", "cloud"],
    },
    {
        "query": "kubernetes deployment example",
        "expected_keywords": ["deployment", "kubernetes", "replicas", "container", "pod"],
        "expected_doc_types": ["k8s", "kubernetes"],
    },
    {
        "query": "docker security best practices",
        "expected_keywords": ["docker", "security", "image", "container", "vulnerability"],
        "expected_doc_types": ["docker", "security"],
    },
    {
        "query": "cicd pipeline security scanning",
        "expected_keywords": ["pipeline", "ci", "cd", "scan", "security", "sast", "dast"],
        "expected_doc_types": ["cicd", "security"],
    },
    {
        "query": "aws iam roles and policies",
        "expected_keywords": ["iam", "role", "policy", "permission", "aws"],
        "expected_doc_types": ["cloud", "terraform", "security"],
    },
    {
        "query": "kubernetes ingress nginx configuration",
        "expected_keywords": ["ingress", "nginx", "kubernetes", "service", "tls"],
        "expected_doc_types": ["k8s", "kubernetes"],
    },
    {
        "query": "terraform state management backend",
        "expected_keywords": ["state", "backend", "terraform", "s3", "remote"],
        "expected_doc_types": ["terraform"],
    },
]

# ── Scoring weights ───────────────────────────────────────────────────────────

_WEIGHTS = {
    "precision_at_k":   0.10,
    "recall_at_k":      0.10,
    "hit_rate":         0.10,
    "faithfulness":     0.20,
    "relevance":        0.20,
    "correctness":      0.15,
    "coverage":         0.10,
    "redundancy_inv":   0.05,  # 1 – redundancy (lower redundancy is better)
}

# ── LLM evaluation prompt ─────────────────────────────────────────────────────

_EVAL_SYSTEM_PROMPT = (
    "You are a strict RAG evaluation assistant for a DevSecOps knowledge base.\n"
    "Score each metric between 0.0 and 1.0.\n"
    "Respond ONLY with a JSON object — no markdown, no explanation.\n\n"
    "Scoring guidance:\n"
    "- faithfulness: Is every factual claim in the answer traceable to the context? "
    "For HCL/code answers, check that resource types, argument names, and key values "
    "appear in the context (even as prose descriptions, not just literal code). "
    "A correct HCL block synthesized from contextual attribute names is faithful.\n"
    "- relevance: Does the answer directly address what the query asked?\n"
    "- correctness: Is the answer technically accurate for the DevSecOps/Terraform domain "
    "given what the context says? Reward complete HCL examples over vague prose."
)

_EVAL_USER_TEMPLATE = """\
Query: {query}

Retrieved context (source of truth):
{context}

Generated answer:
{answer}

Scoring rules:
- faithfulness: 1.0 if every claim/argument in the answer is grounded in the context above; \
0.0 only if the answer introduces facts completely absent from context. \
HCL code blocks synthesized from context attribute names count as faithful.
- relevance: 1.0 if the answer fully addresses the query; partial credit for partial coverage.
- correctness: 1.0 if the answer is technically accurate per the context.

Return ONLY this JSON (no other text):
{{
  "faithfulness": <float 0-1>,
  "relevance": <float 0-1>,
  "correctness": <float 0-1>
}}"""

# ── RAG generation prompts ────────────────────────────────────────────────────

_GEN_SYSTEM_PROMPT = (
    "You are a senior DevSecOps architect and Terraform/IaC expert.\n"
    "Your job is to answer infrastructure and security questions using ONLY the provided context.\n\n"
    "Rules:\n"
    "1. Base every claim on a specific piece of the context. Cite chunk numbers when useful.\n"
    "2. If the question asks for Terraform/HCL code, produce a complete, syntactically valid HCL block "
    "derived from patterns, attributes, and resource types mentioned in the context.\n"
    "3. If the context contains partial HCL, complete it into a runnable example using only attributes "
    "and values explicitly mentioned in the context.\n"
    "4. Structure your answer: first a brief explanation, then a ```hcl code block``` if applicable, "
    "then key security/best-practice notes.\n"
    "5. If the context is truly insufficient, say: 'Context insufficient — no HCL example available.' "
    "Do NOT hallucinate resource arguments not mentioned in context."
)

_GEN_USER_TEMPLATE = """\
CONTEXT (use ONLY this to answer):
{context}

QUESTION: {query}

INSTRUCTIONS:
- Read every context chunk before answering.
- If the question involves Terraform resources (vpc, subnet, backend, iam, etc.):
  * Extract resource type names, argument names, and values from the context.
  * Produce a working HCL example using those exact names/values.
  * Wrap HCL in ```hcl fences.
- If the question involves best practices or security:
  * List the specific rules/anti-patterns from the context as bullet points.
- Keep your answer grounded: every sentence must trace back to a specific chunk.

ANSWER:"""

# Domain classifier: returns True if query is Terraform-focused
def _is_terraform_query(query: str) -> bool:
    tf_signals = {"terraform", "hcl", ".tf", "backend", "provider", "module", "tfstate",
                  "aws_vpc", "aws_iam", "aws_s3", "resource \"", "variable \""}
    q = query.lower()
    return any(sig in q for sig in tf_signals)

# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class EvalResult:
    query: str
    retrieval: dict[str, float] = field(default_factory=dict)
    generation: dict[str, float] = field(default_factory=dict)
    context: dict[str, float] = field(default_factory=dict)
    rag_score: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "query": self.query,
            "retrieval": self.retrieval,
            "generation": self.generation,
            "context": self.context,
            "rag_score": round(self.rag_score, 4),
        }
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class BenchmarkReport:
    results: list[EvalResult] = field(default_factory=list)
    averages: dict[str, float] = field(default_factory=dict)
    overall_rag_score: float = 0.0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_rag_score": round(self.overall_rag_score, 4),
            "averages": {k: round(v, 4) for k, v in self.averages.items()},
            "duration_seconds": round(self.duration_seconds, 2),
            "per_query": [r.to_dict() for r in self.results],
        }


# ── Core evaluator ────────────────────────────────────────────────────────────

class RAGEvaluator:
    """Full evaluation framework for the DevSecOps RAG pipeline."""

    def __init__(
        self,
        qdrant_service: Any,
        embedding_service: Any,
        # Legacy params kept for backward-compat (ignored when Lightning/Groq keys present)
        llm_api_key: str = "",
        llm_base_url: str = "https://integrate.api.nvidia.com/v1",
        llm_model: str = "meta/llama3-70b-instruct",
        top_k: int = 5,
        score_threshold: float = 0.25,
        llm_timeout: float = 30.0,
        # Explicit Lightning / Groq keys (override legacy params)
        lightning_api_key: str = "",
        lightning_base_url: str = "https://api.lightning.ai/v1",
        lightning_eval_model: str = "meta-llama/Meta-Llama-3.1-70B-Instruct",
        groq_api_key: str = "",
        groq_model: str = "llama-3.3-70b-versatile",
    ):
        self._qdrant          = qdrant_service
        self._embedder        = embedding_service
        self._top_k           = top_k
        self._score_threshold = score_threshold
        self._llm_timeout     = llm_timeout

        # Prefer explicit Lightning/Groq keys; fall back to legacy LLM_API_KEY
        self._lightning_key          = lightning_api_key.strip()
        self._lightning_base_url     = lightning_base_url.rstrip("/")
        self._lightning_eval_model   = lightning_eval_model
        self._groq_key               = groq_api_key.strip()
        self._groq_model             = groq_model
        # Legacy fallback — treated as NVIDIA/generic if set
        self._legacy_llm_api_key  = llm_api_key.strip()
        self._legacy_llm_base_url = llm_base_url.rstrip("/")
        self._legacy_llm_model    = llm_model

        if self._lightning_key:
            logger.info(
                "[RAGEval] LLM judge: Lightning AI | model=%s | key=%s",
                lightning_eval_model,
                (self._lightning_key[:6] + "…" + self._lightning_key[-4:]),
            )
        elif self._groq_key:
            logger.info("[RAGEval] LLM judge: Groq (no Lightning key) | model=%s", groq_model)
        elif self._legacy_llm_api_key:
            logger.info("[RAGEval] LLM judge: legacy provider | model=%s", llm_model)
        else:
            logger.warning(
                "[RAGEval] No LLM key set — generation metrics will use heuristic scoring. "
                "Set LIGHTNING_API_KEY for LLM-as-judge evaluation."
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        query: str,
        retrieved_chunks: list[dict[str, Any]] | None = None,
        generated_answer: str | None = None,
        expected_keywords: list[str] | None = None,
        expected_doc_types: list[str] | None = None,
    ) -> EvalResult:
        """Evaluate a single query end-to-end.

        If ``retrieved_chunks`` is None, the evaluator runs the retrieval itself.
        """
        result = EvalResult(query=query)

        try:
            # 1. Retrieve if not provided
            if retrieved_chunks is None:
                retrieved_chunks = self._retrieve(query)

            # 2. Retrieval metrics
            result.retrieval = self._retrieval_metrics(
                retrieved_chunks,
                expected_keywords or [],
                expected_doc_types or [],
            )

            # 3. Context quality
            result.context = self._context_metrics(retrieved_chunks)

            # 4. Generation metrics (LLM-scored when any key is available)
            has_llm = bool(
                self._lightning_key
                or self._groq_key
                or self._legacy_llm_api_key
            )
            if generated_answer and has_llm:
                result.generation = self._generation_metrics_llm(
                    query, retrieved_chunks, generated_answer
                )
            else:
                result.generation = self._generation_metrics_heuristic(
                    query, retrieved_chunks, generated_answer
                )

            # 5. Global RAG score
            result.rag_score = self._global_score(result)

        except Exception as exc:
            logger.error("Evaluation failed for query '%s': %s", query, exc)
            result.error = str(exc)

        return result

    def run_benchmark(self, debug: bool = False) -> BenchmarkReport:
        """Run the full benchmark suite and return aggregated metrics.

        For each query:
          1. Retrieve top-k chunks from Qdrant
          2. Generate a grounded answer via LLM (Lightning → Groq → heuristic fallback)
          3. Score retrieval + generation + context quality
        """
        t0 = time.time()
        results: list[EvalResult] = []

        for item in BENCHMARK_QUERIES:
            query = item["query"]
            logger.info("[Benchmark] Evaluating: %s", query)

            # ── Step 1: retrieve ──────────────────────────────────────────────
            retrieved_chunks = self._retrieve(query)

            if debug:
                print(f"\n[DEBUG] ── Query: {query!r} ──")
                print(f"[DEBUG] Retrieved {len(retrieved_chunks)} chunks:")
                for i, c in enumerate(retrieved_chunks[:3]):
                    print(
                        f"  [{i+1}] {c.get('title','?'):40s}  score={c.get('score', 0):.3f}"
                    )
                    print(f"       {(c.get('content') or '')[:150].strip()!r}…")

            # ── Step 2: generate answer ───────────────────────────────────────
            generated_answer = self._generate_answer(query, retrieved_chunks)

            if debug:
                print(f"[DEBUG] Generated answer preview:\n  {generated_answer[:300]!r}")

            # ── Step 3: evaluate ──────────────────────────────────────────────
            result = self.evaluate(
                query=query,
                retrieved_chunks=retrieved_chunks,
                generated_answer=generated_answer,
                expected_keywords=item.get("expected_keywords", []),
                expected_doc_types=item.get("expected_doc_types", []),
            )
            results.append(result)

        report = BenchmarkReport(
            results=results,
            duration_seconds=time.time() - t0,
        )
        report.averages = self._aggregate_averages(results)
        report.overall_rag_score = sum(r.rag_score for r in results) / max(len(results), 1)
        return report

    # ── LLM answer generation ─────────────────────────────────────────────────

    def _generate_answer(self, query: str, chunks: list[dict[str, Any]]) -> str:
        """Call Lightning/Groq to produce a RAG-grounded answer from retrieved chunks.

        Tries Lightning first, then Groq, then legacy provider.
        Returns a safe fallback string when all providers are unavailable.
        """
        if not chunks:
            logger.warning("[Generation] No chunks available for query '%s'", query)
            return "Relevant information found but answer generation failed."

        # Deduplicate and format context — group by source_type for better grounding
        seen: set[str] = set()
        context_parts: list[str] = []
        for i, c in enumerate(chunks[:5]):
            content = (c.get("content") or "").strip()
            if not content or content in seen:
                continue
            seen.add(content)
            source_type = c.get("source_type") or c.get("doc_type") or "general"
            title = c.get("title") or c.get("concept") or ""
            header = f"[CHUNK {i + 1} | type={source_type}" + (f" | {title}" if title else "") + "]"
            # Use up to 1800 chars per chunk so HCL blocks aren't truncated mid-block
            context_parts.append(f"{header}\n{content[:1800]}")

        context = "\n\n".join(context_parts)
        if len(context) > 14_000:
            context = context[:14_000]

        user_msg = _GEN_USER_TEMPLATE.format(query=query, context=context)

        t0 = time.time()

        providers = [
            ("lightning", self._lightning_base_url, self._lightning_key, self._lightning_eval_model),
            ("groq",      "https://api.groq.com/openai/v1", self._groq_key, self._groq_model),
            ("legacy",    self._legacy_llm_base_url, self._legacy_llm_api_key, self._legacy_llm_model),
        ]

        for label, base_url, api_key, model in providers:
            if not api_key:
                continue
            try:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _GEN_SYSTEM_PROMPT},
                        {"role": "user",   "content": user_msg},
                    ],
                    "temperature": 0.1,
                    "max_tokens":  2048,
                }
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                }
                with httpx.Client(timeout=self._llm_timeout) as client:
                    resp = client.post(
                        f"{base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    resp.raise_for_status()

                data   = resp.json()
                answer = data["choices"][0]["message"]["content"].strip()
                usage  = data.get("usage", {})
                latency_ms = int((time.time() - t0) * 1000)

                logger.info(
                    "[Generation] provider=%s model=%s tokens_in=%s tokens_out=%s latency=%dms",
                    label, model,
                    usage.get("prompt_tokens",     "?"),
                    usage.get("completion_tokens",  "?"),
                    latency_ms,
                )

                if not answer:
                    logger.warning("[Generation] %s returned empty response — trying next provider", label)
                    continue

                logger.debug("[Generation] query=%r answer_preview=%r", query, answer[:200])
                return answer

            except Exception as exc:
                logger.warning("[Generation] %s failed (%s) — trying next provider", label, exc)

        logger.warning("[Generation] All providers failed for query '%s' — returning fallback", query)
        return "Relevant information found but answer generation failed."

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def _retrieve(self, query: str) -> list[dict[str, Any]]:
        vec = self._embedder.embed_query(query)
        # Use hybrid search + reranking (same path as validation) for best chunk quality
        if hasattr(self._qdrant, "search_with_rerank"):
            results = self._qdrant.search_with_rerank(
                query_vector=vec,
                query=query,
                top_k=self._top_k,
                candidate_multiplier=4,
                score_threshold=self._score_threshold,
            )
            if results:
                return results
        # Fallback to basic search when reranker not available
        return self._qdrant.search(
            query_vector=vec,
            top_k=self._top_k,
            score_threshold=self._score_threshold,
        )

    # ── Retrieval metrics ─────────────────────────────────────────────────────

    def _retrieval_metrics(
        self,
        chunks: list[dict[str, Any]],
        expected_keywords: list[str],
        expected_doc_types: list[str],
    ) -> dict[str, float]:
        """Keyword-based relevance judgements (no human labels required).

        Metrics computed:
          precision@k  — fraction of top-k results that are relevant
          recall@k     — proxy: relevant_retrieved / expected_keywords_count
          hit_rate     — 1.0 if any relevant result exists in top-k, else 0.0
          mrr          — Mean Reciprocal Rank: 1/rank of the first relevant hit
        """
        k = min(self._top_k, len(chunks)) if chunks else 0

        if not chunks:
            return {
                "precision_at_k": 0.0,
                "recall_at_k":    0.0,
                "hit_rate":       0.0,
                "mrr":            0.0,
                "k":              k,
            }

        top_k = chunks[:k]
        kw_lower = [kw.lower() for kw in expected_keywords]
        dt_lower = [dt.lower() for dt in expected_doc_types]

        def is_relevant(chunk: dict[str, Any]) -> bool:
            content  = (chunk.get("content")  or "").lower()
            title    = (chunk.get("title")     or "").lower()
            doc_type = (chunk.get("doc_type")  or "").lower()
            kws      = [w.lower() for w in (chunk.get("keywords") or [])]

            keyword_hit = any(
                kw in content or kw in title or any(kw in kk for kk in kws)
                for kw in kw_lower
            )
            doctype_hit = any(dt in doc_type for dt in dt_lower)
            return keyword_hit or doctype_hit

        relevant_flags = [is_relevant(c) for c in top_k]
        relevant_count = sum(relevant_flags)

        precision = relevant_count / k
        expected_total = max(len(expected_keywords), 1)
        recall   = min(relevant_count / expected_total, 1.0)
        hit_rate = 1.0 if any(relevant_flags) else 0.0

        # MRR: reciprocal rank of the FIRST relevant result (1-indexed)
        mrr = 0.0
        for rank, flag in enumerate(relevant_flags, start=1):
            if flag:
                mrr = 1.0 / rank
                break

        return {
            "precision_at_k": round(precision, 4),
            "recall_at_k":    round(recall, 4),
            "hit_rate":       round(hit_rate, 4),
            "mrr":            round(mrr, 4),
            "k":              k,
        }

    # ── Context quality metrics ───────────────────────────────────────────────

    def _context_metrics(self, chunks: list[dict[str, Any]]) -> dict[str, float]:
        if not chunks:
            return {"coverage": 0.0, "redundancy": 0.0}

        # Coverage: mean similarity score of retrieved chunks (proxy for relevance density)
        scores = [c.get("score", 0.0) for c in chunks]
        coverage = sum(scores) / len(scores) if scores else 0.0

        # Redundancy: mean pairwise Jaccard token overlap between chunk contents
        redundancy = self._pairwise_redundancy(chunks)

        return {
            "coverage": round(coverage, 4),
            "redundancy": round(redundancy, 4),
        }

    @staticmethod
    def _pairwise_redundancy(chunks: list[dict[str, Any]]) -> float:
        """Mean Jaccard similarity over all unique chunk pairs."""
        contents = [
            set((c.get("content") or "").lower().split())
            for c in chunks
        ]
        if len(contents) < 2:
            return 0.0

        total, pairs = 0.0, 0
        for i in range(len(contents)):
            for j in range(i + 1, len(contents)):
                a, b = contents[i], contents[j]
                union = len(a | b)
                if union == 0:
                    continue
                total += len(a & b) / union
                pairs += 1

        return total / pairs if pairs else 0.0

    # ── Generation metrics — LLM (Lightning → Groq failover) ─────────────────

    def _generation_metrics_llm(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        answer: str,
    ) -> dict[str, float]:
        # 1200 chars per chunk so the judge sees complete HCL blocks, not truncated halves
        context_text = "\n\n---\n\n".join(
            f"[chunk {i+1} | {c.get('source_type', 'general')}]\n{c.get('content', '')[:1200]}"
            for i, c in enumerate(chunks[:5])
        )
        user_msg = _EVAL_USER_TEMPLATE.format(
            query=query, context=context_text, answer=answer,
        )

        # ── Primary: Lightning AI (70B — better reasoning for judge role) ──────
        if self._lightning_key:
            try:
                scores = self._call_judge(
                    base_url=self._lightning_base_url,
                    api_key=self._lightning_key,
                    model=self._lightning_eval_model,
                    user_msg=user_msg,
                    label="lightning",
                )
                return {**scores, "scored_by": "lightning"}
            except Exception as exc:
                _reason = _classify_eval_error(exc)
                logger.warning(
                    "[RAGEval] Lightning judge failed (%s) → switching to Groq", _reason
                )

        # ── Fallback: Groq ────────────────────────────────────────────────────
        if self._groq_key:
            try:
                scores = self._call_judge(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=self._groq_key,
                    model=self._groq_model,
                    user_msg=user_msg,
                    label="groq",
                    max_tokens=256,
                )
                return {**scores, "scored_by": "groq"}
            except Exception as exc:
                logger.warning("[RAGEval] Groq judge failed: %s → heuristic", exc)

        # ── Legacy NVIDIA/generic provider ────────────────────────────────────
        if self._legacy_llm_api_key:
            try:
                scores = self._call_judge(
                    base_url=self._legacy_llm_base_url,
                    api_key=self._legacy_llm_api_key,
                    model=self._legacy_llm_model,
                    user_msg=user_msg,
                    label="legacy",
                )
                return {**scores, "scored_by": "llm"}
            except Exception as exc:
                logger.warning("[RAGEval] Legacy LLM judge failed: %s → heuristic", exc)

        return self._generation_metrics_heuristic(query, chunks, answer)

    def _call_judge(
        self,
        base_url: str,
        api_key: str,
        model: str,
        user_msg: str,
        label: str,
        max_tokens: int = 256,
    ) -> dict[str, float]:
        """Call an OpenAI-compatible endpoint and parse the JSON scores."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _EVAL_SYSTEM_PROMPT},
                {"role": "user",   "content": user_msg},
            ],
            "temperature": 0.0,
            "max_tokens":  max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }
        with httpx.Client(timeout=self._llm_timeout) as client:
            resp = client.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
        raw    = resp.json()["choices"][0]["message"]["content"].strip()
        scores = self._parse_json_scores(raw)
        logger.debug(
            "[RAGEval] %s judge | model=%s | scores=%s",
            label, model, scores,
        )
        return {
            "faithfulness": round(float(scores.get("faithfulness", 0.5)), 4),
            "relevance":    round(float(scores.get("relevance",    0.5)), 4),
            "correctness":  round(float(scores.get("correctness",  0.5)), 4),
        }

    @staticmethod
    def _parse_json_scores(raw: str) -> dict[str, Any]:
        """Extract JSON from LLM output, even when wrapped in markdown fences."""
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        # Find first { ... }
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {}

    # ── Generation metrics — heuristic fallback ───────────────────────────────

    def _generation_metrics_heuristic(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        answer: str | None,
    ) -> dict[str, float]:
        """Token-overlap heuristic when no LLM key is configured."""
        if not answer or not chunks:
            return {"faithfulness": 0.0, "relevance": 0.0, "correctness": 0.0, "scored_by": "heuristic"}

        answer_tokens = set(answer.lower().split())
        query_tokens = set(query.lower().split())
        context_tokens = set(
            " ".join(c.get("content", "") for c in chunks).lower().split()
        )

        # Faithfulness: fraction of answer tokens found in context
        if answer_tokens:
            faithfulness = len(answer_tokens & context_tokens) / len(answer_tokens)
        else:
            faithfulness = 0.0

        # Relevance: fraction of query tokens found in answer
        if query_tokens:
            relevance = len(query_tokens & answer_tokens) / len(query_tokens)
        else:
            relevance = 0.0

        # Correctness proxy: average retrieval score
        scores = [c.get("score", 0.0) for c in chunks]
        correctness = sum(scores) / len(scores) if scores else 0.0

        return {
            "faithfulness": round(min(faithfulness, 1.0), 4),
            "relevance":    round(min(relevance, 1.0), 4),
            "correctness":  round(min(correctness, 1.0), 4),
            "scored_by":    "heuristic",
        }

    # ── Global score ──────────────────────────────────────────────────────────

    @staticmethod
    def _global_score(result: EvalResult) -> float:
        r = result.retrieval
        g = result.generation
        c = result.context

        score = (
            _WEIGHTS["precision_at_k"] * r.get("precision_at_k", 0.0)
            + _WEIGHTS["recall_at_k"]  * r.get("recall_at_k", 0.0)
            + _WEIGHTS["hit_rate"]     * r.get("hit_rate", 0.0)
            + _WEIGHTS["faithfulness"] * g.get("faithfulness", 0.0)
            + _WEIGHTS["relevance"]    * g.get("relevance", 0.0)
            + _WEIGHTS["correctness"]  * g.get("correctness", 0.0)
            + _WEIGHTS["coverage"]     * c.get("coverage", 0.0)
            + _WEIGHTS["redundancy_inv"] * (1.0 - c.get("redundancy", 0.0))
        )
        return round(min(max(score, 0.0), 1.0), 4)

    # ── Aggregation ───────────────────────────────────────────────────────────

    @staticmethod
    def _aggregate_averages(results: list[EvalResult]) -> dict[str, float]:
        keys = {
            "retrieval": ["precision_at_k", "recall_at_k", "hit_rate", "mrr"],
            "generation": ["faithfulness", "relevance", "correctness"],
            "context": ["coverage", "redundancy"],
        }
        averages: dict[str, float] = {}
        n = max(len(results), 1)

        for section, metric_keys in keys.items():
            for key in metric_keys:
                total = sum(getattr(r, section).get(key, 0.0) for r in results)
                averages[key] = round(total / n, 4)

        return averages


# ── Error classification ──────────────────────────────────────────────────────

def _classify_eval_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "401" in msg or "invalid" in msg or "auth" in msg: return "401 invalid key"
    if "403" in msg or "forbidden" in msg:                return "403 forbidden"
    if "429" in msg or "rate" in msg:                     return "429 rate-limited"
    if "timeout" in msg:                                  return "timeout"
    if "connect" in msg:                                  return "connection error"
    return str(exc)[:80]


# ── Pretty printing ───────────────────────────────────────────────────────────

def print_eval_result(result: EvalResult) -> None:
    d = result.to_dict()
    print(f"\n  Query: {d['query']}")
    r = d["retrieval"]
    print(
        f"  Retrieval  | precision@{r.get('k','?')}={r.get('precision_at_k', 0):.3f}"
        f"  recall={r.get('recall_at_k', 0):.3f}"
        f"  hit_rate={r.get('hit_rate', 0):.3f}"
        f"  mrr={r.get('mrr', 0):.3f}"
    )
    g = d["generation"]
    print(
        f"  Generation | faithfulness={g.get('faithfulness', 0):.3f}"
        f"  relevance={g.get('relevance', 0):.3f}"
        f"  correctness={g.get('correctness', 0):.3f}"
        f"  [{g.get('scored_by', '?')}]"
    )
    c = d["context"]
    print(
        f"  Context    | coverage={c.get('coverage', 0):.3f}"
        f"  redundancy={c.get('redundancy', 0):.3f}"
    )
    print(f"  RAG Score  | {d['rag_score']:.4f}")
    if d.get("error"):
        print(f"  ERROR      | {d['error']}")


def print_benchmark_report(report: BenchmarkReport) -> None:
    d = report.to_dict()
    width = 68
    print("\n" + "=" * width)
    print("  RAG EVALUATION BENCHMARK REPORT")
    print("=" * width)

    for result in report.results:
        print_eval_result(result)

    avgs = d["averages"]
    print("\n" + "─" * width)
    print("  AVERAGES")
    print(
        f"  Retrieval  | precision={avgs.get('precision_at_k',0):.3f}"
        f"  recall={avgs.get('recall_at_k',0):.3f}"
        f"  hit_rate={avgs.get('hit_rate',0):.3f}"
        f"  mrr={avgs.get('mrr',0):.3f}"
    )
    print(
        f"  Generation | faithfulness={avgs.get('faithfulness',0):.3f}"
        f"  relevance={avgs.get('relevance',0):.3f}"
        f"  correctness={avgs.get('correctness',0):.3f}"
    )
    print(
        f"  Context    | coverage={avgs.get('coverage',0):.3f}"
        f"  redundancy={avgs.get('redundancy',0):.3f}"
    )
    print("─" * width)
    print(f"  OVERALL RAG SCORE : {d['overall_rag_score']:.4f}  ({d['duration_seconds']:.1f}s)")
    print("=" * width + "\n")
