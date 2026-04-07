import os
import re
from pathlib import Path

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    GROQ_MODEL: str = "llama3-8b-8192"

    RAG_ENABLED: bool = False
    RAG_QDRANT_URL: str = "http://localhost:6333"
    RAG_COLLECTION_NAME: str = "infra_templates"
    RAG_TOP_K: int = 5
    RAG_CORPUS_PATH: str = "rag/corpus"
    RAG_CHROMA_PATH: str = "rag/chroma"

    # Ollama (embeddings locaux)
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_EMBED_MODEL: str = "nomic-embed-text:v1.5"

    # Gemini (chunking sémantique)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-1.5-flash"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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
