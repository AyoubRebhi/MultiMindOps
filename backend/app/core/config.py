import os
import re
from pathlib import Path

from dotenv import dotenv_values
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file's location so the key loads correctly
# regardless of the working directory when running scripts like ingest_qdrant.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    APP_NAME: str = "DevSecOps AI Platform"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "devsecops_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/devsecops_db"

    GROQ_API_KEY: str = ""
    GROQ_API_KEY_2: str = ""
    GROQ_API_KEY_3: str = ""
    GROQ_API_KEY_4: str = ""
    GROQ_API_KEY_5: str = ""
    GROQ_API_KEY_6: str = ""
    
    GROQ_MODEL: str = "llama3-8b-8192"
    GROQ_FALLBACK_MODEL: str = "llama-3.3-70b-versatile"

    RAG_ENABLED: bool = True
    RAG_QDRANT_URL: str = "http://localhost:6333"
    RAG_COLLECTION_NAME: str = "infra_templates"
    RAG_TOP_K: int = 5
    RAG_CORPUS_PATH: str = "rag/corpus"
    RAG_CHROMA_PATH: str = "rag/chroma"

    # Ollama (embeddings locaux)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text:v1.5"
    # Ollama (semantic chunking local)
    OLLAMA_CHUNK_MODEL: str = "llama3.2:3b"

    # Chunking provider selection (ingestion/offline capable)
    # - "local"    : Ollama semantic chunking (default)
    # - "fallback" : deterministic (no LLM)
    CHUNKING_PROVIDER: str = "local"
    # Markdown-specific chunking policy (orthogonal to CHUNKING_PROVIDER):
    # - "fallback" : deterministic fallback for markdown (default)
    # - "local"    : always try local Ollama for markdown
    # - "auto"     : local only for small/simple markdown, else fallback
    MARKDOWN_CHUNKING_MODE: str = "fallback"
    MARKDOWN_LOCAL_MAX_CHARS: int = 8000
    MARKDOWN_LOCAL_MAX_CODEBLOCKS: int = 12

    # Gemini (legacy chunking — deprecated)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash-lite"

    # GitHub Models — PRIMARY provider for agents (Azure-backed, OpenAI-compatible)
    # Get a token at https://github.com/settings/tokens (no scopes required for public models)
    GITHUB_TOKEN: str = ""
    GITHUB_BASE_URL: str = "https://models.inference.ai.azure.com"
    GITHUB_MODEL: str = "meta/llama-3-70b-instruct"

    # Lightning AI — retained for RAG chunking + LLM-as-judge evaluation only.
    # Not used by agents. Set LIGHTNING_API_KEY to enable the Lightning RAG path.
    LIGHTNING_API_KEY: str = ""
    LIGHTNING_BASE_URL: str = "https://api.lightning.ai/v1"
    LIGHTNING_MODEL: str = "lightning-ai/llama-3.3-70b"
    LIGHTNING_EVAL_MODEL: str = "meta-llama/Meta-Llama-3.1-70B-Instruct"

    # Provider selection for RAG tasks.
    # "lightning" → always use Lightning AI
    # "groq"      → always use Groq
    # "auto"      → Lightning if LIGHTNING_API_KEY is set, else Groq
    LLM_PROVIDER: str = "auto"
    # Agent LLM provider: "github" (primary) | "groq" (direct) | "lightning" (legacy)
    TERRAFORM_LLM_PROVIDER: str = "github"

    # Generic LLM provider (kept for backward-compat; NVIDIA NIM was here)
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    LLM_MODEL: str = "meta/llama3-70b-instruct"

    # MCP Server — dynamic context layer (Terraform schemas, K8s templates, AWS best practices)
    MCP_ENABLED: bool = True
    MCP_SERVER_PATH: str = "mcp/server.py"
    MCP_CACHE_TTL_HOURS: int = 24

    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    @model_validator(mode="after")
    def validate_provider_keys(self) -> "Settings":
        terraform_provider = (self.TERRAFORM_LLM_PROVIDER or "").strip().lower()
        if terraform_provider == "github" and not str(self.GITHUB_TOKEN or "").strip():
            raise ValueError(
                "GITHUB_TOKEN is required when TERRAFORM_LLM_PROVIDER=github. "
                "Get a token at https://github.com/settings/tokens"
            )
        if terraform_provider == "lightning" and not str(self.LIGHTNING_API_KEY or "").strip():
            raise ValueError(
                "LIGHTNING_API_KEY is required when TERRAFORM_LLM_PROVIDER=lightning."
            )
        return self

    def get_groq_api_keys(self) -> list[str]:
        return [item["value"] for item in self.get_groq_key_entries()]

    def get_groq_key_entries(self) -> list[dict[str, str]]:
        """Return Groq API keys from settings, environment, and .env in stable order."""

        collected: dict[str, str] = {}

        for key_name, value in self.model_dump().items():
            if self._is_groq_key_name(key_name) and str(value or "").strip():
                collected[key_name] = str(value).strip()

        for key_name, value in os.environ.items():
            if self._is_groq_key_name(key_name) and str(value or "").strip():
                collected[key_name] = str(value).strip()

        env_file = self.model_config.get("env_file")
        if env_file:
            env_path = Path(env_file)
            if env_path.exists():
                for key_name, value in dotenv_values(env_path).items():
                    if self._is_groq_key_name(key_name) and str(value or "").strip():
                        collected[key_name] = str(value).strip()

        ordered_names = sorted(collected, key=self._groq_key_sort_key)
        return [
            {"name": key_name, "value": collected[key_name]}
            for key_name in ordered_names
        ]

    def _is_groq_key_name(self, key_name: str | None) -> bool:
        return bool(re.fullmatch(r"GROQ_API_KEY(?:_\d+)?", str(key_name or "").strip()))

    def _groq_key_sort_key(self, key_name: str) -> tuple[int, str]:
        if key_name == "GROQ_API_KEY":
            return (0, key_name)
        suffix = key_name.replace("GROQ_API_KEY_", "", 1)
        return (int(suffix) if suffix.isdigit() else 9999, key_name)


settings = Settings()
