from pathlib import Path

from backend.app.core.config import settings


class RAGConfig:
    # ── ChromaDB (legacy) ────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return bool(settings.RAG_ENABLED)

    @property
    def collection_name(self) -> str:
        return settings.RAG_COLLECTION_NAME

    @property
    def top_k(self) -> int:
        return max(1, int(settings.RAG_TOP_K))

    @property
    def chroma_path(self) -> Path:
        return Path(settings.RAG_CHROMA_PATH)

    @property
    def corpus_path(self) -> Path:
        return Path(settings.RAG_CORPUS_PATH)

    # ── Qdrant ───────────────────────────────────────────────────────────────
    @property
    def qdrant_url(self) -> str:
        return settings.RAG_QDRANT_URL

    @property
    def qdrant_collection(self) -> str:
        """Collection Qdrant principale pour la knowledge base DevSecOps."""
        return "devsecops_knowledge"

    @property
    def qdrant_vector_size(self) -> int:
        """Dimension des vecteurs nomic-embed-text:v1.5."""
        return 768

    # ── Ollama ───────────────────────────────────────────────────────────────
    @property
    def ollama_base_url(self) -> str:
        return settings.OLLAMA_BASE_URL

    @property
    def ollama_embed_model(self) -> str:
        return settings.OLLAMA_EMBED_MODEL

    # ── Gemini ───────────────────────────────────────────────────────────────
    @property
    def gemini_api_key(self) -> str:
        return settings.GEMINI_API_KEY

    @property
    def gemini_model(self) -> str:
        return settings.GEMINI_MODEL


rag_config = RAGConfig()
