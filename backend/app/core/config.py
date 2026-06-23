import logging
import os
import re
from pathlib import Path

from dotenv import dotenv_values
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_cfg_logger = logging.getLogger(__name__)

# Resolve .env relative to this file's location so the key loads correctly
# regardless of the working directory when running scripts like ingest_qdrant.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    APP_NAME: str = "DevSecOps AI Platform"
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    # Root log level. When unset, defaults to INFO in development and WARNING
    # in production (see backend/app/core/logging_setup.py).
    LOG_LEVEL: str = ""
    # SQLAlchemy engine echo. Default OFF — flip to true only when debugging
    # raw SQL. Enabling this also installs SQLAlchemy's own logging handler
    # which overrides logging_setup's third-party silencing.
    SQL_ECHO: bool = False

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

    # OpenAI — PRIMARY provider for infrastructure agents (GPT-5-mini)
    # Set OPENAI_KEY to enable; if absent the system falls back to Groq silently.
    OPENAI_KEY: str = ""
    # gpt-5-mini is the real catalog model (Responses API, reasoning family).
    # The previous default "gpt-5.4-mini" is NOT a real OpenAI model id — a fresh
    # deployment without the .env override would 404 on every primary call and
    # silently run Groq-only. .env already sets gpt-5-mini; this keeps the
    # code-default in sync so the override is no longer load-bearing.
    OPENAI_MODEL: str = "gpt-5-mini"
    OPENAI_TIMEOUT: float = 120.0
    OPENAI_MAX_RETRIES: int = 2

    # GitHub Actions deploy.yml enrichment (OPTIONAL polish pass).
    # When true, the rendered deployment workflow is handed to GPT-5-mini for
    # conservative, additive improvements (caching/permissions/concurrency/
    # comments/retention) AFTER rendering and BEFORE YAML validation. The
    # template stays the source of truth: any deviation, invalid YAML, or removed
    # job/terraform/Docker/deploy step falls back to the deterministic render.
    # DEFAULT-OFF so generation is fully deterministic unless explicitly enabled.
    ENABLE_GITHUB_ACTIONS_ENRICHMENT: bool = False

    # GitHub Models — retained for legacy LLMRouter usage (Azure-backed, OpenAI-compatible)
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

    # ── Auth / JWT ──────────────────────────────────────────────────────────
    # Secret MUST be overridden via .env in any non-dev deployment — the
    # built-in default is only meant to keep local dev boot working. If the
    # value is left at the default in production, anyone with the source
    # tree can mint valid tokens. ``APP_ENV != 'development'`` triggers a
    # warning in the model validator below.
    JWT_SECRET: str = "dev-insecure-change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "devsecops-ai-platform"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    # Soft-lock an account after this many consecutive failed logins. 0
    # disables lockout entirely.
    AUTH_MAX_FAILED_LOGIN_ATTEMPTS: int = 10
    # When true, ``get_current_user`` falls back to the seeded dev user if
    # no Authorization header is sent. Useful for local dev; MUST be false
    # in any environment that handles real users.
    AUTH_ALLOW_DEV_FALLBACK: bool = False

    # ── Credential encryption (Phase 4) ──────────────────────────────────────
    # Fernet key (or comma-separated list, newest-first, for rotation) used
    # to encrypt per-project credentials at rest. Generate with:
    #   python -c "from backend.app.core.encryption import generate_app_secret_key; print(generate_app_secret_key())"
    # Empty default means the credential subsystem is DISABLED — writes raise
    # 503 and the workflow flow degrades to "no token". MUST be set in any
    # deployment that stores GitHub PATs / AWS credentials. The encryption
    # module reads os.environ first (so a real env var or a test monkeypatch
    # wins), then falls back to this value loaded from .env.
    APP_SECRET_KEY: str = ""

    # ── Durable execution jobs (Phase 3) ─────────────────────────────────────
    # When true, the API process starts an in-process worker in its lifespan
    # so a single container both serves HTTP and drains the job queue. Set
    # false to run a dedicated worker process
    # (``python -m backend.app.workers.execution_worker``) instead.
    EXECUTION_WORKER_ENABLED: bool = True
    # How many jobs one worker runs concurrently. Per-project mutual
    # exclusion is enforced separately at the DB layer, so this is purely a
    # throughput knob across DIFFERENT projects.
    EXECUTION_WORKER_CONCURRENCY: int = 2
    # Poll cadence for the claim loop.
    EXECUTION_JOB_POLL_INTERVAL_SECONDS: float = 2.0
    # How often a running job's heartbeat is refreshed. Also the upper bound on
    # cancel-detection latency: the heartbeat tick is where the worker observes
    # an operator stop, so a short interval keeps Stop responsive.
    EXECUTION_JOB_HEARTBEAT_INTERVAL_SECONDS: float = 5.0
    # A running job whose heartbeat is older than this is considered orphaned
    # and re-queued by the reaper. Must be comfortably larger than the heartbeat
    # interval so a momentarily-slow tick doesn't trigger a false reap, but small
    # enough that a job orphaned by a uvicorn --reload (dev) self-heals in seconds
    # rather than a full minute. 20s = 4 missed 5s ticks before reaping.
    EXECUTION_JOB_HEARTBEAT_TIMEOUT_SECONDS: int = 20

    # Docker Registry — used by DockerExecutor to push built images
    # Type: "dockerhub" | "ghcr" | "generic"
    DOCKER_REGISTRY_TYPE: str = "dockerhub"
    # Registry URL — empty = Docker Hub, "ghcr.io" = GitHub Container Registry
    DOCKER_REGISTRY_URL: str = ""
    DOCKER_REGISTRY_USERNAME: str = ""
    DOCKER_REGISTRY_PASSWORD: str = ""
    # When true, push the image after a successful build
    DOCKER_PUSH_ON_SUCCESS: bool = False

    # ── Docker daemon connectivity (see services/execution/docker_connectivity.py) ──
    # How long the pre-build daemon probe (`docker version`) may take before it is
    # treated as unreachable. Larger than the old hard-coded 10s to tolerate a cold
    # Docker Desktop / WSL2 backend.
    DOCKER_DAEMON_PROBE_TIMEOUT_SECONDS: float = 20.0
    # Optional explicit fallback endpoint used when the OS-default endpoint (the
    # Windows named pipe / unix socket) is unreachable from the backend process —
    # e.g. "tcp://localhost:2375" when Docker Desktop exposes the daemon over TCP.
    # Empty disables the fallback. When the fallback works, it is applied to the
    # process environment so the actual `docker build` connects to it too.
    DOCKER_HOST_FALLBACK: str = ""

    # ── Email / SMTP (invitation delivery) ───────────────────────────────────
    # Outbound transactional email (workspace invitations). Configured for
    # Gmail SMTP in .env. NOTE: Gmail's SMTP AUTH username MUST be the full
    # Gmail address — if SMTP_USERNAME is a human-readable name (e.g. an app
    # label) the EmailService falls back to EMAIL_FROM for the login and uses
    # SMTP_USERNAME only as the From display name. See email_service.py.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    # Envelope/From address shown to recipients (and the Gmail login fallback).
    EMAIL_FROM: str = ""
    # Optional friendly From display name. Defaults to SMTP_USERNAME (when it is
    # not an email) or APP_NAME.
    EMAIL_FROM_NAME: str = ""
    # Master switch — when false, invitation creation still succeeds but no
    # email is dispatched (email_status recorded as 'SKIPPED'). Useful for
    # local/dev/CI runs that must not hit the network.
    EMAIL_ENABLED: bool = True
    # Hard cap on a single SMTP transaction so a slow/unreachable relay cannot
    # hang the admin's "create invitation" request indefinitely.
    SMTP_TIMEOUT_SECONDS: float = 15.0
    # Public base URL of the frontend, used to build the invitation acceptance
    # link ({FRONTEND_URL}/invite/{token}).
    FRONTEND_URL: str = "http://localhost:5173"

    # ── AWS credentials (Terraform plan) ─────────────────────────────────────
    # Long-term IAM user keys (from `aws configure`) the AWS provider uses when
    # Terraform runs init/plan. These are overlaid onto the terraform subprocess
    # environment (see terraform_pipeline.pipeline_service.terraform_subprocess_env).
    # Leave EMPTY to fall back to the shared credentials file (~/.aws/credentials)
    # / instance role chain — so a developer who already ran `aws configure`
    # needs no .env change. AWS_SESSION_TOKEN is only for temporary STS creds.
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_SESSION_TOKEN: str = ""
    AWS_DEFAULT_REGION: str = "us-east-1"

    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    @model_validator(mode="after")
    def validate_provider_keys(self) -> "Settings":
        # NOTE: TerraformAgent / KubernetesAgent now use ProviderFactory (OpenAI+Groq),
        # not LLMRouter, so TERRAFORM_LLM_PROVIDER only affects legacy LLMRouter usage.
        # We downgrade these checks from hard errors to warnings to avoid crashing startup.
        terraform_provider = (self.TERRAFORM_LLM_PROVIDER or "").strip().lower()
        if terraform_provider == "github" and not str(self.GITHUB_TOKEN or "").strip():
            _cfg_logger.warning(
                "TERRAFORM_LLM_PROVIDER=github but GITHUB_TOKEN is not set. "
                "LLMRouter will fall back to Groq. "
                "TerraformAgent/KubernetesAgent are unaffected (they use ProviderFactory)."
            )
        if terraform_provider == "lightning" and not str(self.LIGHTNING_API_KEY or "").strip():
            _cfg_logger.warning(
                "TERRAFORM_LLM_PROVIDER=lightning but LIGHTNING_API_KEY is not set. "
                "LLMRouter will fall back to Groq."
            )

        # ── JWT secret sanity check ────────────────────────────────────────
        # Warn loudly if the default secret is in use outside dev. We do not
        # raise here because some CI/test setups leave APP_ENV at the
        # default — failing startup would break those test runs.
        env = (self.APP_ENV or "").strip().lower()
        secret = (self.JWT_SECRET or "").strip()
        if env != "development" and (not secret or secret == "dev-insecure-change-me"):
            _cfg_logger.warning(
                "JWT_SECRET is unset or left at the insecure default while "
                "APP_ENV=%s. Set JWT_SECRET in .env to a long random string.",
                env or "(empty)",
            )

        # ── Credential-encryption key check (Phase 4) ──────────────────────
        # Outside development, an unset APP_SECRET_KEY means the credential
        # subsystem is silently disabled — operators would discover this only
        # when a credential write 503s. Warn at boot so it's visible in logs.
        # Not a hard raise (same reasoning as JWT_SECRET: CI/test setups leave
        # APP_ENV at the default), and a deployment with no private repos /
        # cloud creds yet can legitimately run without it.
        if env != "development" and not str(
            os.environ.get("APP_SECRET_KEY") or self.APP_SECRET_KEY or ""
        ).strip():
            _cfg_logger.warning(
                "APP_SECRET_KEY is unset while APP_ENV=%s. The credential "
                "subsystem is DISABLED — storing GitHub/AWS credentials will "
                "fail with 503. Generate a key with "
                "`python -c \"from backend.app.core.encryption import "
                "generate_app_secret_key; print(generate_app_secret_key())\"`.",
                env or "(empty)",
            )

        # ── SMTP / email config check ──────────────────────────────────────
        # Validate at startup so a misconfigured relay is visible in the boot
        # log instead of only when the first invitation is sent. We do NOT hard
        # raise (email is non-critical to app boot, and CI/dev can run with
        # EMAIL_ENABLED=false) — but we list exactly which fields are missing.
        if self.EMAIL_ENABLED:
            missing = [
                name
                for name, value in (
                    ("SMTP_HOST", self.SMTP_HOST),
                    ("SMTP_PASSWORD", self.SMTP_PASSWORD),
                    # Login resolves to SMTP_USERNAME (if it's an email) or
                    # EMAIL_FROM — at least one must be present.
                    ("EMAIL_FROM/SMTP_USERNAME", self.EMAIL_FROM or self.SMTP_USERNAME),
                )
                if not str(value or "").strip()
            ]
            if missing:
                _cfg_logger.warning(
                    "EMAIL_ENABLED=true but SMTP is incomplete (missing: %s). "
                    "Invitation emails will be recorded as FAILED until these "
                    "are set in .env, or set EMAIL_ENABLED=false to disable "
                    "outbound email.",
                    ", ".join(missing),
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
