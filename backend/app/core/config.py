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
    GROQ_MODEL: str = "llama3-8b-8192"

    RAG_ENABLED: bool = False
    RAG_CHROMA_PATH: str = "rag/chroma"
    RAG_COLLECTION_NAME: str = "infra_templates"
    RAG_TOP_K: int = 3
    RAG_CORPUS_PATH: str = "rag/corpus"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
