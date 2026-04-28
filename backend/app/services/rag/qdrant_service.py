"""
Service Qdrant pour la knowledge base DevSecOps.

Collection schema :
  - Vector size    : 768 (nomic-embed-text:v1.5)
  - Distance       : Cosine
  - Payload fields :
      content      (str)   : texte du chunk
      source       (str)   : fichier source
      doc_type     (str)   : docker | k8s | terraform | cicd | security | cloud
      chunk_type   (str)   : code | config | yaml | security_rule | prose
      context_tag  (str)   : tag de contexte fin-grain
      title        (str)   : titre court du chunk
      keywords     (list)  : mots-clés extraits
      chunk_index  (int)   : position dans le document source
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_VECTOR_SIZE = 768
_DEFAULT_URL = "http://localhost:6333"
_DEFAULT_COLLECTION = "devsecops_knowledge"


class QdrantService:
    """Abstraction haut-niveau sur le client Qdrant."""

    def __init__(
        self,
        url: str = _DEFAULT_URL,
        collection_name: str = _DEFAULT_COLLECTION,
        vector_size: int = _VECTOR_SIZE,
    ):
        self._url = url
        self._collection = collection_name
        self._vector_size = vector_size
        self._client = self._build_client()

    # ── Initialisation ───────────────────────────────────────────────────────

    def _build_client(self):
        try:
            from qdrant_client import QdrantClient  # type: ignore
            return QdrantClient(url=self._url)
        except Exception as exc:
            logger.error("Impossible d'initialiser le client Qdrant : %s", exc)
            return None

    # ── Gestion de la collection ─────────────────────────────────────────────

    def create_collection(self, recreate: bool = False) -> bool:
        """Crée la collection Qdrant si elle n'existe pas.

        Args:
            recreate: Si True, supprime et recrée la collection.

        Returns:
            True si la collection est prête, False en cas d'erreur.
        """
        if self._client is None:
            return False
        try:
            from qdrant_client.models import (  # type: ignore
                Distance,
                VectorParams,
                HnswConfigDiff,
                OptimizersConfigDiff,
            )

            if recreate:
                try:
                    self._client.delete_collection(self._collection)
                    logger.info("Collection '%s' supprimée.", self._collection)
                except Exception:
                    pass

            existing = [c.name for c in self._client.get_collections().collections]
            if self._collection in existing and not recreate:
                logger.info("Collection '%s' déjà existante.", self._collection)
                return True

            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(
                    size=self._vector_size,
                    distance=Distance.COSINE,
                ),
                hnsw_config=HnswConfigDiff(
                    m=16,
                    ef_construct=200,
                ),
                optimizers_config=OptimizersConfigDiff(
                    default_segment_number=4,
                ),
            )
            self._ensure_payload_indexes()
            logger.info(
                "Collection '%s' créée (dim=%d, distance=Cosine).",
                self._collection,
                self._vector_size,
            )
            return True

        except Exception as exc:
            logger.error("Erreur création collection : %s", exc)
            return False

    def _ensure_payload_indexes(self) -> None:
        """Create keyword payload indexes on filterable fields for fast metadata filtering."""
        if self._client is None:
            return
        try:
            from qdrant_client.models import PayloadSchemaType  # type: ignore
        except ImportError:
            return

        indexed_fields = [
            "doc_type", "chunk_type", "framework", "artifact_type",
            "complexity", "cloud_provider", "use_case", "chunking_source",
        ]
        for field in indexed_fields:
            try:
                self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass  # index already exists or unsupported — non-fatal

    def collection_info(self) -> dict[str, Any]:
        """Retourne les informations sur la collection."""
        if self._client is None:
            return {"error": "client_unavailable"}
        try:
            info = self._client.get_collection(self._collection)
            return {
                "name": self._collection,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
                "status": str(info.status),
            }
        except Exception as exc:
            return {"error": str(exc)}

    # ── Ingestion ────────────────────────────────────────────────────────────

    def upsert_documents(
        self,
        chunks: list[dict[str, Any]],
        batch_size: int = 64,
    ) -> int:
        """Insère ou met à jour des chunks dans Qdrant.

        Args:
            chunks:     Chunks enrichis avec la clé ``embedding``.
            batch_size: Nombre de points par batch upsert.

        Returns:
            Nombre de points insérés.
        """
        if self._client is None:
            return 0

        try:
            from qdrant_client.models import PointStruct  # type: ignore
        except ImportError as exc:
            logger.error("qdrant_client manquant : %s", exc)
            return 0

        total = 0
        points_buffer: list[Any] = []

        for chunk in chunks:
            embedding = chunk.get("embedding")
            if not embedding or len(embedding) != self._vector_size:
                logger.warning(
                    "Chunk ignoré (embedding invalide) : %s", chunk.get("source")
                )
                continue

            point_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{chunk.get('source', '')}::{chunk.get('chunk_index', 0)}",
            ))
            payload = self._build_payload(chunk)
            points_buffer.append(
                PointStruct(id=point_id, vector=embedding, payload=payload)
            )

            if len(points_buffer) >= batch_size:
                self._flush(points_buffer)
                total += len(points_buffer)
                points_buffer = []

        if points_buffer:
            self._flush(points_buffer)
            total += len(points_buffer)

        logger.info("%d points upsertés dans '%s'.", total, self._collection)
        return total

    def _flush(self, points: list[Any]) -> None:
        try:
            self._client.upsert(collection_name=self._collection, points=points)
        except Exception as exc:
            logger.error("Erreur upsert Qdrant : %s", exc)

    # ── Recherche ────────────────────────────────────────────────────────────

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        doc_type_filter: str | None = None,
        chunk_type_filter: str | None = None,
        framework_filter: str | None = None,
        complexity_filter: str | None = None,
        use_case_filter: str | None = None,
        score_threshold: float = 0.35,
    ) -> list[dict[str, Any]]:
        """Semantic search in Qdrant with optional metadata filtering.

        Args:
            query_vector:      Query embedding vector.
            top_k:             Maximum number of results to return.
            doc_type_filter:   Filter by doc_type (docker, k8s, terraform…).
            chunk_type_filter: Filter by chunk_type (code, security_rule…).
            framework_filter:  Filter by framework (kubernetes, terraform…).
            complexity_filter: Filter by complexity (low, medium, high).
            use_case_filter:   Filter by use_case (security, deployment…).
            score_threshold:   Minimum cosine similarity to retain a result.

        Returns:
            List of dicts with ``content``, ``score``, and all payload metadata.
        """
        if self._client is None:
            return []

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue  # type: ignore

            conditions = []
            filter_map = {
                "doc_type": doc_type_filter,
                "chunk_type": chunk_type_filter,
                "framework": framework_filter,
                "complexity": complexity_filter,
                "use_case": use_case_filter,
            }
            for key, value in filter_map.items():
                if value:
                    conditions.append(
                        FieldCondition(key=key, match=MatchValue(value=value))
                    )

            query_filter = Filter(must=conditions) if conditions else None

            # qdrant-client >= 1.7 : query_points remplace search()
            response = self._client.query_points(
                collection_name=self._collection,
                query=query_vector,
                limit=top_k,
                query_filter=query_filter,
                score_threshold=score_threshold,
                with_payload=True,
            )
            hits = response.points

            return [
                {
                    "id": str(hit.id),
                    "score": round(hit.score, 4),
                    **(hit.payload or {}),
                }
                for hit in hits
            ]

        except Exception as exc:
            logger.error("Erreur recherche Qdrant : %s", exc)
            return []

    def hybrid_search(
        self,
        query_vector: list[float],
        keyword: str,
        top_k: int = 5,
        doc_type_filter: str | None = None,
        framework_filter: str | None = None,
        use_case_filter: str | None = None,
        score_threshold: float = 0.30,
    ) -> list[dict[str, Any]]:
        """Recherche hybride : sémantique + filtrage par mot-clé dans le payload.

        La recherche sémantique est effectuée en premier, puis les résultats
        sont re-scorés si le mot-clé apparaît dans le contenu ou les keywords.
        """
        # 1. Fetch wider semantic candidate pool then re-rank
        candidates = self.search(
            query_vector=query_vector,
            top_k=top_k * 3,
            doc_type_filter=doc_type_filter,
            framework_filter=framework_filter,
            use_case_filter=use_case_filter,
            score_threshold=score_threshold,
        )

        if not keyword.strip():
            return candidates[:top_k]

        kw_lower = keyword.lower()

        # 2. Booster le score si le mot-clé est présent
        boosted: list[tuple[float, dict[str, Any]]] = []
        for result in candidates:
            boost = 0.0
            content = (result.get("content") or "").lower()
            keywords = [k.lower() for k in (result.get("keywords") or [])]
            title = (result.get("title") or "").lower()

            if kw_lower in content:
                boost += 0.15
            if any(kw_lower in kw for kw in keywords):
                boost += 0.10
            if kw_lower in title:
                boost += 0.05

            final_score = min(result["score"] + boost, 1.0)
            boosted.append((final_score, {**result, "score": round(final_score, 4)}))

        boosted.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in boosted[:top_k]]

    def rerank_results(
        self,
        results: list[dict[str, Any]],
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Domain-aware heuristic reranker applied after vector retrieval.

        Scoring bonuses applied on top of the base cosine similarity score:
          +0.10  exact query term in chunk title
          +0.08  security_rule chunk for security/iam/cve queries
          +0.07  code/config chunk for dockerfile/terraform/hcl queries
          +0.06  yaml chunk for k8s/helm/kubernetes queries
          +0.06  config chunk for terraform/hcl queries
          +0.05  doc_type matches the inferred query domain
          +0.03  per query term found in chunk keywords (max 5 terms)
          +0.02  per query term found in chunk content (max 5 terms)

        After reranking the list is truncated to `top_k`.
        Each result gains a ``rerank_score`` field and ``rerank_delta`` showing
        the bonus applied, which is useful for validation logging.
        """
        if not results:
            return results

        query_lower = query.lower()
        query_terms = [t for t in re.split(r"\W+", query_lower) if len(t) > 2]

        # Domain signals inferred from query text
        is_security  = any(t in query_lower for t in ("security", "cve", "iam", "owasp", "secret", "vuln", "hardening"))
        is_docker    = any(t in query_lower for t in ("docker", "dockerfile", "container", "image"))
        is_k8s       = any(t in query_lower for t in ("kubernetes", "k8s", "helm", "kubectl", "pod", "ingress"))
        is_terraform = any(t in query_lower for t in ("terraform", "hcl", "resource", "provider", "module"))
        is_cicd      = any(t in query_lower for t in ("pipeline", "cicd", "ci/cd", "github actions", "jenkins", "workflow"))
        is_aws       = any(t in query_lower for t in ("aws", "ec2", "s3", "vpc", "lambda", "eks", "rds"))

        _DOMAIN_DOC_TYPES = {
            "is_docker":    {"docker"},
            "is_k8s":       {"k8s", "kubernetes"},
            "is_terraform": {"terraform"},
            "is_cicd":      {"cicd"},
            "is_aws":       {"cloud", "aws"},
            "is_security":  {"security"},
        }

        scored: list[dict[str, Any]] = []
        for result in results:
            base   = result.get("score", 0.0)
            bonus  = 0.0
            ct     = (result.get("chunk_type") or "").lower()
            dt     = (result.get("doc_type") or "").lower()
            title  = (result.get("title") or "").lower()
            kws    = [k.lower() for k in (result.get("keywords") or [])]
            content = (result.get("content") or "").lower()

            # Title match bonus (strongest signal for exact intent)
            if any(t in title for t in query_terms):
                bonus += 0.10

            # Chunk-type × query-domain bonuses
            if is_security and ct == "security_rule":
                bonus += 0.08
            if (is_docker or is_terraform) and ct in ("code", "config"):
                bonus += 0.07
            if is_k8s and ct == "yaml":
                bonus += 0.06
            if is_terraform and ct == "config":
                bonus += 0.06
            if is_cicd and ct in ("code", "config"):
                bonus += 0.05

            # doc_type domain match
            for flag, types in _DOMAIN_DOC_TYPES.items():
                if locals().get(flag) and any(t in dt for t in types):
                    bonus += 0.05
                    break

            # Keyword overlap (up to 5 terms × 0.03)
            kw_hits = sum(1 for t in query_terms[:5] if any(t in kw for kw in kws))
            bonus += kw_hits * 0.03

            # Content term overlap (up to 5 terms × 0.02, cheaper than keywords)
            content_hits = sum(1 for t in query_terms[:5] if t in content)
            bonus += content_hits * 0.02

            rerank_score = round(min(base + bonus, 1.0), 4)
            scored.append({
                **result,
                "rerank_score": rerank_score,
                "rerank_delta": round(bonus, 4),
            })

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_k]

    def search_with_rerank(
        self,
        query_vector: list[float],
        query: str,
        top_k: int = 5,
        candidate_multiplier: int = 4,
        doc_type_filter: str | None = None,
        framework_filter: str | None = None,
        use_case_filter: str | None = None,
        score_threshold: float = 0.30,
    ) -> list[dict[str, Any]]:
        """
        Two-stage retrieval: wide hybrid search → domain-aware heuristic reranking.

        Stage 1 — hybrid search with ``top_k × candidate_multiplier`` candidates.
        Stage 2 — ``rerank_results()`` collapses the pool to ``top_k``.

        This pattern gives the reranker a rich candidate pool (default: 20 for top_k=5)
        and consistently improves nDCG / MRR versus one-shot top-k retrieval.
        """
        import time as _time
        t0 = _time.monotonic()

        candidates = self.hybrid_search(
            query_vector=query_vector,
            keyword=query,
            top_k=top_k * candidate_multiplier,
            doc_type_filter=doc_type_filter,
            framework_filter=framework_filter,
            use_case_filter=use_case_filter,
            score_threshold=score_threshold,
        )

        reranked = self.rerank_results(candidates, query, top_k=top_k)
        latency_ms = round((_time.monotonic() - t0) * 1000)

        logger.debug(
            "search_with_rerank: query=%r candidates=%d → reranked=%d | latency=%dms",
            query[:60], len(candidates), len(reranked), latency_ms,
        )
        return reranked

    def delete_by_source(self, source: str) -> bool:
        """Supprime tous les points d'une source donnée."""
        if self._client is None:
            return False
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue, FilterSelector  # type: ignore

            self._client.delete(
                collection_name=self._collection,
                points_selector=FilterSelector(
                    filter=Filter(
                        must=[FieldCondition(key="source", match=MatchValue(value=source))]
                    )
                ),
            )
            return True
        except Exception as exc:
            logger.error("Erreur delete_by_source : %s", exc)
            return False

    # ── Utilitaires ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_payload(chunk: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "content": chunk.get("content", ""),
            "source": chunk.get("source", ""),
            "doc_type": chunk.get("doc_type", "general"),
            "chunk_type": chunk.get("chunk_type", "prose"),
            "context_tag": chunk.get("context_tag", ""),
            "title": chunk.get("title", ""),
            "keywords": chunk.get("keywords", []),
            "chunk_index": int(chunk.get("chunk_index", 0)),
        }
        # Enriched metadata added by the semantic chunking service (absent in legacy chunks → skipped)
        for field in (
            "artifact_type", "cloud_provider", "section_title",
            "framework", "complexity", "use_case", "chunking_source",
        ):
            value = chunk.get(field)
            if value is not None:
                payload[field] = value
        return payload

    def health_check(self) -> dict[str, Any]:
        """Vérifie la connectivité avec Qdrant."""
        if self._client is None:
            return {"status": "error", "reason": "client_not_initialized"}
        try:
            collections = [c.name for c in self._client.get_collections().collections]
            return {
                "status": "ok",
                "url": self._url,
                "collections": collections,
                "target_collection": self._collection,
                "target_exists": self._collection in collections,
            }
        except Exception as exc:
            return {"status": "error", "reason": str(exc), "url": self._url}
