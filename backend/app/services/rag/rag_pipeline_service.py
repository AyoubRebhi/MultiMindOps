"""
Pipeline RAG sémantique complet pour DevSecOps.

Flux :
  requête utilisateur
    → embed_query (Ollama nomic-embed-text:v1.5)
    → hybrid_search (Qdrant cosine + keyword boost)
    → rerank (score × pertinence contextuelle)
    → build_context_prompt (injection dans le prompt LLM)

Intégration dans les agents :
    from backend.app.services.rag.rag_pipeline_service import RAGPipelineService
    rag = RAGPipelineService()
    context_block = rag.retrieve_context(query="dockerfile python fastapi", doc_type="docker")
    # Injecter context_block dans le system prompt du LLM
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.core.rag_config import rag_config
from backend.app.services.rag.embedding_service import EmbeddingService
from backend.app.services.rag.qdrant_service import QdrantService

logger = logging.getLogger(__name__)


class RAGPipelineService:
    """Pipeline RAG production-grade : query → embed → search → context."""

    def __init__(self):
        self._embedder = EmbeddingService(
            ollama_base_url=rag_config.ollama_base_url,
            model=rag_config.ollama_embed_model,
        )
        self._qdrant = QdrantService(
            url=rag_config.qdrant_url,
            collection_name=rag_config.qdrant_collection,
            vector_size=rag_config.qdrant_vector_size,
        )
        self._top_k = rag_config.top_k

    # ── API principale ───────────────────────────────────────────────────────

    def retrieve_context(
        self,
        query: str,
        doc_type: str | None = None,
        chunk_type: str | None = None,
        top_k: int | None = None,
        use_hybrid: bool = True,
        score_threshold: float = 0.28,
    ) -> dict[str, Any]:
        """Récupère le contexte RAG pour une requête.

        Args:
            query:           Requête utilisateur en langage naturel.
            doc_type:        Filtrer par type (docker, k8s, terraform, cicd, security, cloud).
            chunk_type:      Filtrer par type de chunk (code, security_rule…).
            top_k:           Nombre de chunks à retourner (défaut : rag_config.top_k).
            use_hybrid:      True pour activer le boost par mots-clés.
            score_threshold: Score cosinus minimum.

        Returns:
            Dict contenant :
              - available  : bool
              - results    : liste de chunks triés par score
              - context    : bloc texte prêt pour injection LLM
              - query      : requête originale
              - doc_type   : filtre appliqué
        """
        k = top_k or self._top_k

        # 1. Vérifier la disponibilité
        health = self._qdrant.health_check()
        if health.get("status") != "ok":
            logger.warning("Qdrant indisponible : %s", health.get("reason"))
            return self._empty_result(query, doc_type, reason=health.get("reason", "qdrant_down"))

        if not health.get("target_exists"):
            logger.warning("Collection Qdrant '%s' non trouvée.", rag_config.qdrant_collection)
            return self._empty_result(query, doc_type, reason="collection_not_found")

        # 2. Encoder la requête
        try:
            query_vector = self._embedder.embed_query(query)
        except Exception as exc:
            logger.error("Erreur embedding requête : %s", exc)
            return self._empty_result(query, doc_type, reason=f"embedding_error:{exc}")

        # 3. Recherche dans Qdrant
        try:
            if use_hybrid:
                results = self._qdrant.hybrid_search(
                    query_vector=query_vector,
                    keyword=query,
                    top_k=k,
                    doc_type_filter=doc_type,
                    score_threshold=score_threshold,
                )
            else:
                results = self._qdrant.search(
                    query_vector=query_vector,
                    top_k=k,
                    doc_type_filter=doc_type,
                    chunk_type_filter=chunk_type,
                    score_threshold=score_threshold,
                )
        except Exception as exc:
            logger.error("Erreur recherche Qdrant : %s", exc)
            return self._empty_result(query, doc_type, reason=f"search_error:{exc}")

        if not results:
            return self._empty_result(query, doc_type, reason="no_results")

        # 4. Reranking contextuel
        ranked = self._rerank(results, query, doc_type)[:k]

        # 5. Construire le bloc de contexte
        context_block = self._build_context_block(ranked, query, doc_type)

        return {
            "available": True,
            "reason": "ok",
            "query": query,
            "doc_type": doc_type,
            "top_k": k,
            "results_count": len(ranked),
            "results": ranked,
            "context": context_block,
        }

    def retrieve_for_agent(
        self,
        mapped_context: dict[str, Any],
        artifact_keys: list[str],
    ) -> dict[str, Any]:
        """Interface compatible InfrastructureAgent / CICDAgent.

        Construit automatiquement la requête à partir du contexte mappé,
        exécute le pipeline RAG pour chaque artifact_key,
        et retourne un dict structuré équivalent à l'ancien TemplateRetrievalService.
        """
        retrievals: dict[str, Any] = {}
        template_ids: list[str] = []

        for artifact_key in artifact_keys:
            doc_type = _ARTIFACT_TO_DOC_TYPE.get(artifact_key, "general")
            query = self._build_query_from_context(mapped_context, artifact_key, doc_type)

            result = self.retrieve_context(
                query=query,
                doc_type=doc_type,
                top_k=self._top_k,
            )

            if result.get("available") and result.get("results"):
                templates = [
                    {
                        "id": r.get("id", ""),
                        "content": r.get("content", ""),
                        "metadata": {
                            "artifact_type": r.get("doc_type"),
                            "chunk_type": r.get("chunk_type"),
                            "source": r.get("source"),
                            "title": r.get("title"),
                            "keywords": r.get("keywords", []),
                        },
                        "distance": 1.0 - r.get("score", 0),
                        "score": r.get("score", 0),
                    }
                    for r in result["results"]
                ]
                retrievals[artifact_key] = {
                    "artifact_type": doc_type,
                    "query_text": query,
                    "templates": templates,
                    "context": result.get("context", ""),
                }
                template_ids.extend(t["id"] for t in templates)

        return {
            "enabled": True,
            "available": bool(retrievals),
            "reason": "ok" if retrievals else "no_results",
            "top_k": self._top_k,
            "retrievals": retrievals,
            "template_ids": sorted(set(template_ids)),
        }

    def build_llm_prompt_with_context(
        self,
        system_prompt: str,
        user_query: str,
        rag_results: list[dict[str, Any]],
        max_context_chars: int = 3000,
    ) -> tuple[str, str]:
        """Injecte le contexte RAG dans le prompt LLM.

        Returns:
            (system_prompt_enrichi, user_prompt_final)
        """
        if not rag_results:
            return system_prompt, user_query

        context_parts = []
        total_chars = 0
        for result in rag_results:
            content = result.get("content", "").strip()
            if not content:
                continue
            chunk_header = (
                f"[Source: {result.get('source', 'unknown')} | "
                f"Type: {result.get('doc_type', '')} | "
                f"Score: {result.get('score', 0):.2f}]"
            )
            block = f"{chunk_header}\n{content}"
            if total_chars + len(block) > max_context_chars:
                break
            context_parts.append(block)
            total_chars += len(block)

        if not context_parts:
            return system_prompt, user_query

        context_section = "\n\n---\n\n".join(context_parts)
        enriched_system = (
            f"{system_prompt}\n\n"
            "## Contexte RAG — Knowledge Base DevSecOps\n\n"
            "Les extraits suivants proviennent de la knowledge base. "
            "Utilise-les comme référence pour ta réponse. "
            "Adapte toujours le contenu au contexte spécifique du projet.\n\n"
            f"{context_section}"
        )
        return enriched_system, user_query

    # ── Reranking ────────────────────────────────────────────────────────────

    def _rerank(
        self,
        results: list[dict[str, Any]],
        query: str,
        doc_type: str | None,
    ) -> list[dict[str, Any]]:
        """Reranking léger basé sur des heuristiques contextuelles."""
        query_lower = query.lower()
        scored: list[tuple[float, dict[str, Any]]] = []

        for result in results:
            base_score = result.get("score", 0.0)
            bonus = 0.0

            # Bonus si le type de chunk est pertinent pour la requête
            chunk_type = result.get("chunk_type", "")
            if "securit" in query_lower and chunk_type == "security_rule":
                bonus += 0.08
            if any(kw in query_lower for kw in ("dockerfile", "docker")) and chunk_type == "code":
                bonus += 0.06
            if any(kw in query_lower for kw in ("yaml", "k8s", "kubernetes")) and chunk_type == "yaml":
                bonus += 0.06
            if any(kw in query_lower for kw in ("terraform", "iac")) and chunk_type == "config":
                bonus += 0.06

            # Bonus si le doc_type match exactement
            if doc_type and result.get("doc_type") == doc_type:
                bonus += 0.04

            # Bonus si les keywords du chunk couvrent la requête
            keywords = [k.lower() for k in result.get("keywords", [])]
            query_words = set(query_lower.split())
            overlap = len(query_words & set(keywords))
            bonus += overlap * 0.02

            final = min(base_score + bonus, 1.0)
            scored.append((final, {**result, "score": round(final, 4)}))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored]

    # ── Construction du contexte ─────────────────────────────────────────────

    @staticmethod
    def _build_context_block(
        results: list[dict[str, Any]],
        query: str,
        doc_type: str | None,
    ) -> str:
        """Formate les résultats en un bloc texte pour le prompt LLM."""
        if not results:
            return ""

        lines = [
            f"# Contexte RAG — {doc_type or 'DevSecOps'} ({len(results)} chunks)",
            f"# Requête : {query}",
            "",
        ]
        for idx, result in enumerate(results, 1):
            lines.append(
                f"## Chunk {idx} | {result.get('title', 'Sans titre')} "
                f"(score={result.get('score', 0):.2f}, "
                f"type={result.get('chunk_type', '?')}, "
                f"source={result.get('source', '?')})"
            )
            lines.append(result.get("content", ""))
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _build_query_from_context(
        mapped_context: dict[str, Any],
        artifact_key: str,
        doc_type: str,
    ) -> str:
        main_service = mapped_context.get("main_service") or {}
        runtime = mapped_context.get("runtime") or {}
        deps = [d["name"] for d in (mapped_context.get("infrastructure_dependencies") or [])]

        parts = [
            f"{doc_type} {artifact_key}",
            f"language={main_service.get('language') or 'unknown'}",
            f"framework={main_service.get('framework') or ''}",
            f"runtime={' '.join(runtime.get('package_managers') or [])}",
            f"dependencies={' '.join(deps[:5])}",
        ]
        return " ".join(filter(None, parts))

    @staticmethod
    def _empty_result(
        query: str,
        doc_type: str | None,
        reason: str = "unavailable",
    ) -> dict[str, Any]:
        return {
            "available": False,
            "reason": reason,
            "query": query,
            "doc_type": doc_type,
            "top_k": 0,
            "results_count": 0,
            "results": [],
            "context": "",
        }

    def health_check(self) -> dict[str, Any]:
        return {
            "qdrant": self._qdrant.health_check(),
            "ollama": self._embedder.health_check(),
        }


# ── Mapping artifact_key → doc_type ─────────────────────────────────────────
_ARTIFACT_TO_DOC_TYPE: dict[str, str] = {
    "dockerfile": "docker",
    "dockerignore": "docker",
    "docker_compose": "docker",
    "env_example": "general",
    "kubernetes_manifests": "k8s",
    "kubernetes_deployment": "k8s",
    "kubernetes_service": "k8s",
    "kubernetes_configmap": "k8s",
    "terraform_main": "terraform",
    "terraform_variables": "terraform",
    "terraform_outputs": "terraform",
    "security_notes": "security",
    "github_actions": "cicd",
    "ci_cd": "cicd",
}
