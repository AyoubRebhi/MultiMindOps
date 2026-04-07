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
                    m=16,               # nombre de liens par nœud HNSW
                    ef_construct=200,   # précision à l'indexation
                ),
                optimizers_config=OptimizersConfigDiff(
                    default_segment_number=4,
                ),
            )
            logger.info(
                "Collection '%s' créée (dim=%d, distance=Cosine).",
                self._collection,
                self._vector_size,
            )
            return True

        except Exception as exc:
            logger.error("Erreur création collection : %s", exc)
            return False

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
        score_threshold: float = 0.30,
    ) -> list[dict[str, Any]]:
        """Recherche sémantique dans Qdrant.

        Args:
            query_vector:      Vecteur de la requête.
            top_k:             Nombre maximal de résultats.
            doc_type_filter:   Filtrer par type de document (docker, k8s…).
            chunk_type_filter: Filtrer par type de chunk (code, security_rule…).
            score_threshold:   Score cosinus minimum pour retenir un résultat.

        Returns:
            Liste de dicts avec ``content``, ``score`` et toutes les métadonnées.
        """
        if self._client is None:
            return []

        try:
            from qdrant_client.models import Filter, FieldCondition, MatchValue  # type: ignore

            conditions = []
            if doc_type_filter:
                conditions.append(
                    FieldCondition(key="doc_type", match=MatchValue(value=doc_type_filter))
                )
            if chunk_type_filter:
                conditions.append(
                    FieldCondition(key="chunk_type", match=MatchValue(value=chunk_type_filter))
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
        score_threshold: float = 0.25,
    ) -> list[dict[str, Any]]:
        """Recherche hybride : sémantique + filtrage par mot-clé dans le payload.

        La recherche sémantique est effectuée en premier, puis les résultats
        sont re-scorés si le mot-clé apparaît dans le contenu ou les keywords.
        """
        # 1. Récupérer plus de candidats sémantiques
        candidates = self.search(
            query_vector=query_vector,
            top_k=top_k * 3,
            doc_type_filter=doc_type_filter,
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
        return {
            "content": chunk.get("content", ""),
            "source": chunk.get("source", ""),
            "doc_type": chunk.get("doc_type", "general"),
            "chunk_type": chunk.get("chunk_type", "prose"),
            "context_tag": chunk.get("context_tag", ""),
            "title": chunk.get("title", ""),
            "keywords": chunk.get("keywords", []),
            "chunk_index": int(chunk.get("chunk_index", 0)),
        }

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
