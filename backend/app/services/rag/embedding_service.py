"""
Service d'embeddings locaux via Ollama.

Modèle utilisé : nomic-embed-text:v1.5
  - Dimension : 768
  - Optimisé pour la recherche sémantique en anglais et multilingue
  - Support du prefixe "search_document:" / "search_query:" pour améliorer la qualité

Usage :
    service = EmbeddingService()
    vectors = service.embed_texts(["docker security best practices"])
    query_vec = service.embed_query("how to secure a Dockerfile")
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Dimension du modèle nomic-embed-text:v1.5
NOMIC_EMBED_DIM = 768
_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_MODEL = "nomic-embed-text:v1.5"
_BATCH_SIZE = 16          # chunks par requête HTTP
_REQUEST_TIMEOUT = 60.0   # secondes
_RETRY_DELAY = 2.0        # secondes entre les retry


class EmbeddingService:
    """Génère des embeddings denses via l'API Ollama."""

    def __init__(
        self,
        ollama_base_url: str = _DEFAULT_OLLAMA_URL,
        model: str = _DEFAULT_MODEL,
        batch_size: int = _BATCH_SIZE,
    ):
        self._base_url = ollama_base_url.rstrip("/")
        self._model = model
        self._batch_size = batch_size
        self._embed_endpoint = f"{self._base_url}/api/embed"

    # ── API publique ─────────────────────────────────────────────────────────

    def embed_query(self, query: str) -> list[float]:
        """Embedding d'une requête utilisateur.

        Utilise le préfixe ``search_query:`` recommandé par nomic-embed-text.
        """
        prefixed = f"search_query: {query}"
        results = self._call_ollama([prefixed])
        return results[0] if results else [0.0] * NOMIC_EMBED_DIM

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embedding de documents (knowledge base).

        Utilise le préfixe ``search_document:`` recommandé par nomic-embed-text.
        """
        if not texts:
            return []
        prefixed = [f"search_document: {t}" for t in texts]
        return self._batch_embed(prefixed)

    def embed_chunks(
        self,
        chunks: list[dict[str, Any]],
        content_key: str = "content",
    ) -> list[dict[str, Any]]:
        """Enrichit chaque chunk avec son vecteur d'embedding.

        Args:
            chunks:      Liste de dicts produits par GeminiChunkingService.
            content_key: Clé du champ texte dans chaque chunk.

        Returns:
            Les mêmes dicts avec la clé ``embedding`` ajoutée.
        """
        texts = [chunk.get(content_key, "") for chunk in chunks]
        vectors = self.embed_texts(texts)

        enriched = []
        for chunk, vector in zip(chunks, vectors):
            enriched.append({**chunk, "embedding": vector})
        return enriched

    def health_check(self) -> dict[str, Any]:
        """Vérifie la disponibilité d'Ollama."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._base_url}/api/tags")
                models = [m["name"] for m in resp.json().get("models", [])]
                available = any(self._model.split(":")[0] in m for m in models)
                return {
                    "status": "ok" if available else "model_missing",
                    "model": self._model,
                    "available_models": models,
                    "ollama_url": self._base_url,
                }
        except Exception as exc:
            return {
                "status": "error",
                "model": self._model,
                "error": str(exc),
                "ollama_url": self._base_url,
            }

    # ── Logique interne ──────────────────────────────────────────────────────

    def _batch_embed(self, texts: list[str]) -> list[list[float]]:
        """Traitement par lots pour éviter les timeouts sur de grands corpus."""
        all_vectors: list[list[float]] = []
        total = len(texts)

        for start in range(0, total, self._batch_size):
            batch = texts[start : start + self._batch_size]
            logger.debug(
                "Embedding batch %d–%d / %d",
                start + 1,
                min(start + self._batch_size, total),
                total,
            )
            vectors = self._call_ollama(batch)
            all_vectors.extend(vectors)

        return all_vectors

    def _call_ollama(
        self,
        texts: list[str],
        retries: int = 2,
    ) -> list[list[float]]:
        """Appel HTTP vers l'API Ollama /api/embed avec retry."""
        payload = {"model": self._model, "input": texts}

        for attempt in range(retries + 1):
            try:
                with httpx.Client(timeout=_REQUEST_TIMEOUT) as client:
                    resp = client.post(self._embed_endpoint, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    embeddings = data.get("embeddings", [])
                    if embeddings:
                        return embeddings
                    # Format alternatif : {"embedding": [...]}
                    if "embedding" in data:
                        return [data["embedding"]]
                    logger.warning("Réponse Ollama sans embeddings : %s", data)
                    return [[0.0] * NOMIC_EMBED_DIM for _ in texts]

            except httpx.HTTPStatusError as exc:
                logger.error("Ollama HTTP %s : %s", exc.response.status_code, exc)
                if attempt < retries:
                    time.sleep(_RETRY_DELAY)
            except httpx.RequestError as exc:
                logger.error("Ollama connexion échouée : %s", exc)
                if attempt < retries:
                    time.sleep(_RETRY_DELAY)

        # Fallback : vecteurs nuls
        return [[0.0] * NOMIC_EMBED_DIM for _ in texts]
