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

    @property
    def ollama_chunk_model(self) -> str:
        return getattr(settings, "OLLAMA_CHUNK_MODEL", "llama3.2:3b")

    @property
    def chunking_provider(self) -> str:
        """
        Chunking backend for ingestion:
          - "local" (default): Ollama
          - "fallback": deterministic (no LLM)
        """
        p = str(getattr(settings, "CHUNKING_PROVIDER", "local") or "local").lower().strip()
        return p if p in {"local", "fallback"} else "local"

    @property
    def markdown_chunking_mode(self) -> str:
        """Markdown policy: fallback | local | auto (default fallback)."""
        mode = str(getattr(settings, "MARKDOWN_CHUNKING_MODE", "fallback") or "fallback").lower().strip()
        return mode if mode in {"fallback", "local", "auto"} else "fallback"

    @property
    def markdown_local_max_chars(self) -> int:
        return max(1, int(getattr(settings, "MARKDOWN_LOCAL_MAX_CHARS", 8000)))

    @property
    def markdown_local_max_codeblocks(self) -> int:
        return max(0, int(getattr(settings, "MARKDOWN_LOCAL_MAX_CODEBLOCKS", 12)))

    # ── Lightning AI (primary RAG provider) ─────────────────────────────────
    @property
    def lightning_api_key(self) -> str:
        return settings.LIGHTNING_API_KEY

    @property
    def lightning_base_url(self) -> str:
        return settings.LIGHTNING_BASE_URL

    @property
    def lightning_model(self) -> str:
        """Fast 8B model — semantic chunking (cost-optimised)."""
        return settings.LIGHTNING_MODEL

    @property
    def lightning_eval_model(self) -> str:
        """70B model — LLM-as-judge evaluation (quality-optimised)."""
        return settings.LIGHTNING_EVAL_MODEL

    @property
    def llm_provider(self) -> str:
        """'lightning' | 'groq' | 'auto'."""
        return settings.LLM_PROVIDER

    def effective_provider(self) -> str:
        """Resolve 'auto' to an actual provider name at runtime."""
        p = self.llm_provider.lower()
        if p == "auto":
            return "lightning" if bool(self.lightning_api_key.strip()) else "groq"
        return p

    # ── Groq fallback ────────────────────────────────────────────────────────
    @property
    def groq_api_key(self) -> str:
        return settings.GROQ_API_KEY

    @property
    def groq_api_keys(self) -> list[str]:
        """All available Groq keys (primary + backups), for key rotation."""
        candidates = [
            settings.GROQ_API_KEY,
            settings.GROQ_API_KEY_2,
            settings.GROQ_API_KEY_3,
            settings.GROQ_API_KEY_4,
            settings.GROQ_API_KEY_5,
            settings.GROQ_API_KEY_6,

        ]
        return [k for k in candidates if k.strip()]

    @property
    def groq_model(self) -> str:
        return settings.GROQ_MODEL

    # ── Generic LLM / NVIDIA (backward-compat) ───────────────────────────────
    @property
    def llm_api_key(self) -> str:
        return settings.LLM_API_KEY

    @property
    def llm_base_url(self) -> str:
        return settings.LLM_BASE_URL

    @property
    def llm_model(self) -> str:
        return settings.LLM_MODEL

    # ── Model selection by task ──────────────────────────────────────────────
    def model_for_task(self, task: str) -> tuple[str, str, str]:
        """
        Return (provider_name, base_url, model_id) for the given task.

        Tasks: "chunking" | "evaluation" | "agent"
        """
        provider = self.effective_provider()

        if task == "evaluation":
            # Always use the heavier model for LLM-as-judge
            if provider == "lightning" and self.lightning_api_key:
                return ("lightning", self.lightning_base_url, self.lightning_eval_model)
            return ("groq", "https://api.groq.com/openai/v1", self.groq_model)

        if task == "chunking":
            # Chunking is local-first (offline-capable); no external dependency.
            return ("local", self.ollama_base_url, self.ollama_chunk_model)

        # "agent" or unknown — Groq for fast inference
        return ("groq", "https://api.groq.com/openai/v1", self.groq_model)


rag_config = RAGConfig()
