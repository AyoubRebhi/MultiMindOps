from typing import Any

from backend.app.core.rag_config import rag_config
from backend.app.services.template_corpus_service import (
    SimpleHashEmbeddingFunction,
    TemplateCorpusService,
)

try:
    import chromadb
except Exception:  # pragma: no cover - optional dependency
    chromadb = None


class TemplateRetrievalService:
    ARTIFACT_QUERY_KEYS = {
        "dockerfile": "dockerfile",
        "docker_compose": "docker_compose",
        "env_example": "env_example",
        "kubernetes_manifests": "kubernetes",
        "kubernetes_deployment": "kubernetes",
        "kubernetes_service": "kubernetes",
        "kubernetes_configmap": "kubernetes",
        "terraform_main": "terraform",
        "terraform_variables": "terraform",
        "terraform_outputs": "terraform",
        "security_notes": "security",
    }

    def __init__(self):
        self.corpus_service = TemplateCorpusService()
        self.embedding_function = SimpleHashEmbeddingFunction()

    def get_collection_status(self) -> dict[str, Any]:
        if not rag_config.enabled:
            return {"enabled": False, "available": False, "reason": "rag_disabled"}
        if chromadb is None:
            return {
                "enabled": True,
                "available": False,
                "reason": "chromadb_not_installed",
            }

        try:
            client = chromadb.PersistentClient(path=str(rag_config.chroma_path))
            collection = client.get_or_create_collection(
                name=rag_config.collection_name,
                embedding_function=self.embedding_function,
            )
            count = collection.count()
            return {
                "enabled": True,
                "available": count > 0,
                "reason": "ok" if count > 0 else "empty_collection",
                "count": count,
            }
        except Exception as exc:  # pragma: no cover - environment dependent
            return {
                "enabled": True,
                "available": False,
                "reason": f"chroma_error:{type(exc).__name__}",
            }

    def retrieve_for_context(
        self,
        mapped_context: dict[str, Any],
        artifact_keys: list[str],
    ) -> dict[str, Any]:
        status = self.get_collection_status()
        retrievals: dict[str, Any] = {}

        if not status.get("available"):
            return {
                "enabled": status.get("enabled", False),
                "available": False,
                "reason": status.get("reason"),
                "top_k": rag_config.top_k,
                "retrievals": retrievals,
                "template_ids": [],
            }

        collection = chromadb.PersistentClient(path=str(rag_config.chroma_path)).get_or_create_collection(
            name=rag_config.collection_name,
            embedding_function=self.embedding_function,
        )

        template_ids: list[str] = []
        for artifact_key in artifact_keys:
            artifact_type = self.ARTIFACT_QUERY_KEYS.get(artifact_key)
            if not artifact_type:
                continue

            query_text = self._build_query_text(mapped_context, artifact_type)
            where_filter = {"artifact_type": artifact_type}

            result = collection.query(
                query_texts=[query_text],
                n_results=max(rag_config.top_k * 2, rag_config.top_k),
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
            items = self._rank_templates(
                self._normalize_results(result),
                mapped_context,
                artifact_type,
            )[: rag_config.top_k]
            if items:
                retrievals[artifact_key] = {
                    "artifact_type": artifact_type,
                    "query_text": query_text,
                    "templates": items,
                }
                template_ids.extend(item["id"] for item in items)

        return {
            "enabled": True,
            "available": True,
            "reason": "ok",
            "top_k": rag_config.top_k,
            "retrievals": retrievals,
            "template_ids": sorted(set(template_ids)),
        }

    def _build_query_text(
        self,
        mapped_context: dict[str, Any],
        artifact_type: str,
    ) -> str:
        main_service = mapped_context.get("main_service") or {}
        runtime = mapped_context.get("runtime") or {}
        dependency_names = [
            item["name"] for item in mapped_context.get("infrastructure_dependencies") or []
        ]
        service_names = [service["name"] for service in mapped_context.get("services") or []]
        env_names = [item["name"] for item in mapped_context.get("environment_template") or []]

        parts = [
            f"artifact_type={artifact_type}",
            f"project_type={mapped_context.get('project_type', '')}",
            f"language={main_service.get('language') or 'unknown'}",
            f"framework={main_service.get('framework') or ''}",
            f"runtime={' '.join(runtime.get('package_managers') or [])}",
            f"services={' '.join(service_names)}",
            f"dependencies={' '.join(dependency_names)}",
            f"environment_variables={' '.join(env_names)}",
            f"ports={main_service.get('port') or ''}",
            f"command={main_service.get('run_command') or ''}",
        ]
        return "\n".join(parts)

    def _normalize_results(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        items = []
        for idx, template_id in enumerate(ids):
            items.append(
                {
                    "id": template_id,
                    "content": documents[idx] if idx < len(documents) else "",
                    "metadata": metadatas[idx] if idx < len(metadatas) else {},
                    "distance": distances[idx] if idx < len(distances) else None,
                }
            )
        return items

    def _rank_templates(
        self,
        templates: list[dict[str, Any]],
        mapped_context: dict[str, Any],
        artifact_type: str,
    ) -> list[dict[str, Any]]:
        framework = ((mapped_context.get("main_service") or {}).get("framework") or "").lower()
        language = ((mapped_context.get("main_service") or {}).get("language") or "").lower()
        dependencies = {
            item["name"].lower()
            for item in mapped_context.get("infrastructure_dependencies") or []
        }

        scored = []
        for template in templates:
            metadata = template.get("metadata") or {}
            template_framework = str(metadata.get("framework") or "").lower()
            template_language = str(metadata.get("language") or "").lower()
            template_dependencies = {
                item.strip().lower()
                for item in str(metadata.get("dependencies") or "").split(",")
                if item.strip()
            }

            score = 0
            if framework and framework in template_framework:
                score += 4
            elif framework and template_framework not in {"", "generic"}:
                score -= 3

            if language and language in template_language:
                score += 3
            elif language and template_language not in {"", "generic"}:
                score -= 2

            if dependencies:
                overlap = len(dependencies & template_dependencies)
                score += overlap * 2
                if template_dependencies and overlap == 0:
                    score -= 1

            if artifact_type == "security":
                score += 1

            scored.append((score, template))

        scored.sort(key=lambda item: (item[0], -(item[1].get("distance") or 0)), reverse=True)
        filtered = [template for score, template in scored if score >= 0]
        return filtered or [template for _, template in scored[:1]]
