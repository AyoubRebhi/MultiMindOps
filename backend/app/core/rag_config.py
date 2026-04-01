from pathlib import Path

from backend.app.core.config import settings


class RAGConfig:
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


rag_config = RAGConfig()
