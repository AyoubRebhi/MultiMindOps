"""
ApplicationProfilerService — heuristic + LLM hybrid cloud architecture profiler.

Produces an ``application_profile`` dict consumed by the PlannerAgent to make
informed infrastructure and scaling decisions.

Two-layer approach
------------------
1. **Heuristic layer** (always runs, zero LLM cost)
   Uses the quick_scan structure output to infer application type, architecture
   pattern, statefulness, detected services, scalability, and entrypoints.

2. **LLM refinement layer** (optional, temperature=0.1)
   Refines workload profile, scalability level, application type, and
   statefulness when an architecture summary is available.  Falls back to
   heuristic values silently on any LLM error.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from backend.app.services.core.glm_service import LLMClient, get_glm_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — keyword sets used by the heuristic layer
# ---------------------------------------------------------------------------

_CPU_BOUND_LIBS = {
    "numpy", "scipy", "pandas", "sklearn", "scikit-learn", "tensorflow",
    "torch", "pytorch", "keras", "cv2", "opencv", "pillow", "pil",
    "numba", "celery", "dask", "ray", "ffmpeg",
}
_IO_BOUND_SIGNALS = {
    "fastapi", "flask", "django", "express", "spring", "gin", "aiohttp",
    "httpx", "requests", "sqlalchemy", "prisma", "mongoose", "psycopg2",
    "pymongo", "redis", "celery", "boto3", "aiobotocore",
}
_MEMORY_BOUND_SIGNALS = {
    "pandas", "polars", "dask", "spark", "pyspark", "h5py", "zarr",
    "pyarrow", "vaex",
}

_DB_SIGNALS = {
    "postgres", "postgresql", "mysql", "mariadb", "mongodb", "mongo",
    "sqlite", "mssql", "sqlserver", "cassandra", "dynamodb", "firestore",
    "supabase", "planetscale",
}
_CACHE_SIGNALS = {"redis", "memcached", "valkey"}
_MESSAGING_SIGNALS = {
    "kafka", "rabbitmq", "amqp", "nats", "pulsar", "activemq",
    "sqs", "pubsub", "celery",
}

_MVC_DIRS = {"controllers", "controller", "models", "model", "views", "view", "templates"}
_LAYERED_DIRS = {"service", "services", "repository", "repositories", "controller", "controllers"}
_EVENT_DRIVEN_SIGNALS = {
    "kafka", "rabbitmq", "celery", "nats", "pubsub", "eventbridge",
    "sns", "sqs", "amqp", "event_bus", "event-bus",
}

_SYSTEM_PROMPT = """\
You are a cloud architecture expert analyzing a software repository.
Given a concise repository summary, classify the following attributes.

Return ONLY a strict JSON object — no prose, no markdown, no code fences.

Required JSON keys (all lowercase strings):
{
  "application_type": "<monolith|microservices|serverless|library|cli>",
  "workload_profile": "<cpu_bound|io_bound|memory_bound|mixed>",
  "scalability_level": "<low|medium|high>",
  "statefulness": "<stateless|stateful>"
}

Classification rules:
- application_type: monolith if single entrypoint; microservices if multiple services or docker-compose with 2+ services; serverless if lambda/serverless.yml present.
- workload_profile: cpu_bound for ML/data/image; io_bound for REST APIs, DB calls; memory_bound for large dataset processing; mixed otherwise.
- scalability_level: high if microservices or async queues; medium for standard web; low for small scripts or CLI.
- statefulness: stateful if any database dependency detected; stateless if pure stateless API.
"""


class ApplicationProfilerService:
    """
    Builds an application_profile from quick_scan data and an optional
    architecture summary string.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._client = llm_client  # lazy-initialised on first use

    @property
    def _llm(self) -> LLMClient:
        if self._client is None:
            self._client = get_glm_service()
        return self._client

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def build_profile(
        self,
        quick_scan: Dict[str, Any],
        architecture_summary: str = "",
        repo_summary: Dict[str, Any] | None = None,
        primary_stack: List[str] | None = None,
    ) -> Dict[str, Any]:
        """
        Return an application_profile dict.

        Parameters
        ----------
        quick_scan:
            Output of QuickScannerService.scan().
        architecture_summary:
            Free-text summary produced by TargetedRepositoryParser (may be empty).
        repo_summary:
            Parsed project summary dict (may be None).
        primary_stack:
            Stack list from LLMPriorityEngine (may be None).
        """
        heuristic = self._heuristic_profile(
            quick_scan=quick_scan,
            repo_summary=repo_summary,
            primary_stack=primary_stack or [],
        )

        # Attempt LLM refinement when we have enough context
        context_text = self._build_context_text(
            quick_scan=quick_scan,
            architecture_summary=architecture_summary,
            repo_summary=repo_summary,
            primary_stack=primary_stack or [],
        )

        llm_patch: Dict[str, Any] = {}
        if context_text:
            try:
                raw_patch = self._llm_refine(context_text)
                logger.debug("[ApplicationProfilerService] raw llm_patch: %s", raw_patch)
                if isinstance(raw_patch, dict):
                    llm_patch = raw_patch
                else:
                    logger.warning(
                        "[ApplicationProfilerService] _llm_refine returned %s — ignoring.",
                        type(raw_patch).__name__,
                    )
            except Exception as exc:
                logger.warning(
                    "[ApplicationProfilerService] LLM refinement failed (%s) — using heuristics only.",
                    exc,
                )

        profile = {**heuristic}
        # LLM overrides — applied only for the four classification fields with full type safety
        sanitized_patch: Dict[str, str] = {}
        for key in ("application_type", "workload_profile", "scalability_level", "statefulness"):
            raw_val = llm_patch.get(key)
            if raw_val is None:
                continue
            if not isinstance(raw_val, str):
                logger.warning(
                    "[ApplicationProfilerService] LLM key '%s' is %s (expected str) — skipping.",
                    key,
                    type(raw_val).__name__,
                )
                continue
            stripped = raw_val.strip()
            if stripped:
                sanitized_patch[key] = stripped

        logger.debug("[ApplicationProfilerService] sanitized llm_patch: %s", sanitized_patch)
        profile.update(sanitized_patch)

        # Guarantee every field is present with a sensible default so callers
        # never receive an empty or partially-filled dict.
        _PROFILE_DEFAULTS: Dict[str, Any] = {
            "application_type": "monolith",
            "architecture_pattern": "layered",
            "statefulness": "stateless",
            "workload_profile": "io_bound",
            "scalability_level": "medium",
            "detected_services": [],
            "entrypoints": [],
        }
        for key, default in _PROFILE_DEFAULTS.items():
            if not profile.get(key) and profile.get(key) != 0:
                profile[key] = default

        # Ensure list fields are always lists
        for list_key in ("detected_services", "entrypoints"):
            if not isinstance(profile.get(list_key), list):
                profile[list_key] = []

        logger.info(
            "[ApplicationProfilerService] final profile — application_type=%s workload=%s scalability=%s statefulness=%s",
            profile.get("application_type"),
            profile.get("workload_profile"),
            profile.get("scalability_level"),
            profile.get("statefulness"),
        )
        logger.debug("[ApplicationProfilerService] full profile: %s", profile)

        return profile

    # ------------------------------------------------------------------
    # Heuristic layer
    # ------------------------------------------------------------------

    def _heuristic_profile(
        self,
        quick_scan: Dict[str, Any],
        repo_summary: Dict[str, Any] | None,
        primary_stack: List[str],
    ) -> Dict[str, Any]:
        hints: Dict[str, Any] = quick_scan.get("hints", {})
        signal_files: List[str] = quick_scan.get("signal_files", [])
        top_dirs: List[str] = quick_scan.get("top_level_dirs", [])
        root_files: List[str] = quick_scan.get("root_files", [])
        languages: List[str] = quick_scan.get("languages_hinted", [])
        total_files: int = quick_scan.get("total_files_scanned", 0)

        all_signals_lower = " ".join(
            signal_files + root_files + top_dirs + primary_stack
        ).lower()

        # ── Application type ──────────────────────────────────────────
        application_type = self._detect_application_type(
            hints=hints,
            signal_files=signal_files,
            root_files=root_files,
            top_dirs=top_dirs,
            all_signals_lower=all_signals_lower,
        )

        # ── Architecture pattern ──────────────────────────────────────
        architecture_pattern = self._detect_architecture_pattern(
            top_dirs=top_dirs,
            all_signals_lower=all_signals_lower,
        )

        # ── Statefulness ─────────────────────────────────────────────
        statefulness = self._detect_statefulness(all_signals_lower, repo_summary)

        # ── Detected services ─────────────────────────────────────────
        detected_services = self._detect_services(all_signals_lower, repo_summary)

        # ── Workload profile ─────────────────────────────────────────
        workload_profile = self._detect_workload(all_signals_lower, repo_summary)

        # ── Scalability estimation ────────────────────────────────────
        scalability_level = self._estimate_scalability(
            application_type=application_type,
            hints=hints,
            total_files=total_files,
            all_signals_lower=all_signals_lower,
        )

        # ── Entrypoints ───────────────────────────────────────────────
        entrypoints = self._extract_entrypoints(signal_files, root_files)

        return {
            "application_type": application_type,
            "architecture_pattern": architecture_pattern,
            "workload_profile": workload_profile,
            "statefulness": statefulness,
            "scalability_level": scalability_level,
            "entrypoints": entrypoints,
            "detected_services": detected_services,
        }

    def _detect_application_type(
        self,
        hints: Dict[str, Any],
        signal_files: List[str],
        root_files: List[str],
        top_dirs: List[str],
        all_signals_lower: str,
    ) -> str:
        # Serverless first — specific marker
        if any(
            name in f.lower()
            for f in signal_files + root_files
            for name in ("serverless.yml", "serverless.yaml", "handler.py", "lambda_handler")
        ):
            return "serverless"
        if "serverless" in all_signals_lower and "lambda" in all_signals_lower:
            return "serverless"

        # Microservices — docker-compose with multiple services OR k8s OR is_monorepo with service dirs
        if hints.get("has_kubernetes"):
            return "microservices"
        if hints.get("is_monorepo") and any(
            d in top_dirs for d in ("services", "apps", "packages")
        ):
            return "microservices"
        docker_compose_files = [
            f for f in signal_files
            if "docker-compose" in f.lower()
        ]
        if docker_compose_files:
            # Treat docker-compose presence as a microservices signal only when
            # combined with multiple top-level service dirs or Kubernetes hints.
            if hints.get("has_kubernetes") or len([d for d in top_dirs if d in ("services", "apps", "backend", "frontend")]) >= 2:
                return "microservices"

        # CLI tool heuristic
        if any(f in ("cli.py", "main.py", "__main__.py") for f in root_files) and not hints.get("has_docker"):
            if "click" in all_signals_lower or "typer" in all_signals_lower or "argparse" in all_signals_lower:
                return "cli"

        # Library
        if any(f in ("setup.py", "pyproject.toml") for f in root_files) and not hints.get("has_docker"):
            if "src" in top_dirs and "tests" in top_dirs and not any(
                ep in root_files for ep in ("app.py", "server.py", "manage.py")
            ):
                return "library"

        return "monolith"

    def _detect_architecture_pattern(
        self,
        top_dirs: List[str],
        all_signals_lower: str,
    ) -> str:
        top_dirs_set = {d.lower() for d in top_dirs}

        if any(sig in all_signals_lower for sig in _EVENT_DRIVEN_SIGNALS):
            return "event-driven"

        if len(top_dirs_set & _LAYERED_DIRS) >= 2:
            return "layered"

        if len(top_dirs_set & _MVC_DIRS) >= 2:
            return "mvc"

        return "layered"

    def _detect_statefulness(
        self,
        all_signals_lower: str,
        repo_summary: Dict[str, Any] | None,
    ) -> str:
        summary_text = json.dumps(repo_summary or {}).lower()
        combined = all_signals_lower + " " + summary_text

        if any(sig in combined for sig in _DB_SIGNALS):
            return "stateful"
        if any(sig in combined for sig in _CACHE_SIGNALS):
            return "stateful"
        return "stateless"

    def _detect_services(
        self,
        all_signals_lower: str,
        repo_summary: Dict[str, Any] | None,
    ) -> List[str]:
        summary_text = json.dumps(repo_summary or {}).lower()
        combined = all_signals_lower + " " + summary_text

        services: List[str] = []

        # Databases
        for sig in _DB_SIGNALS:
            if sig in combined:
                label = _DB_LABEL_MAP.get(sig, sig)
                if label not in services:
                    services.append(label)

        # Cache
        for sig in _CACHE_SIGNALS:
            if sig in combined:
                if sig not in services:
                    services.append(sig)

        # Messaging
        for sig in _MESSAGING_SIGNALS:
            if sig in combined:
                if sig not in services:
                    services.append(sig)

        # Frontend / backend split
        has_frontend = any(
            kw in combined
            for kw in ("react", "vue", "angular", "svelte", "next.js", "nuxt", "frontend")
        )
        has_backend = any(
            kw in combined
            for kw in ("fastapi", "flask", "django", "express", "spring", "backend", "api")
        )
        if has_frontend:
            services.append("frontend")
        if has_backend:
            services.append("backend-api")

        return services

    def _detect_workload(
        self,
        all_signals_lower: str,
        repo_summary: Dict[str, Any] | None,
    ) -> str:
        summary_text = json.dumps(repo_summary or {}).lower()
        combined = all_signals_lower + " " + summary_text

        has_cpu = any(lib in combined for lib in _CPU_BOUND_LIBS)
        has_mem = any(lib in combined for lib in _MEMORY_BOUND_SIGNALS)
        has_io = any(lib in combined for lib in _IO_BOUND_SIGNALS)

        if has_cpu and has_io:
            return "mixed"
        if has_mem and not has_cpu:
            return "memory_bound"
        if has_cpu:
            return "cpu_bound"
        if has_io:
            return "io_bound"
        return "io_bound"  # safe default for unknown web apps

    def _estimate_scalability(
        self,
        application_type: str,
        hints: Dict[str, Any],
        total_files: int,
        all_signals_lower: str,
    ) -> str:
        if application_type == "microservices":
            return "high"

        has_async = any(
            kw in all_signals_lower
            for kw in ("celery", "kafka", "rabbitmq", "asyncio", "aiohttp", "nats", "sqs")
        )
        if has_async or hints.get("has_kubernetes"):
            return "high"

        if total_files < 50 or application_type in ("cli", "library"):
            return "low"

        return "medium"

    def _extract_entrypoints(
        self,
        signal_files: List[str],
        root_files: List[str],
    ) -> List[str]:
        entrypoint_names = {
            "main.py", "app.py", "manage.py", "server.py", "wsgi.py", "asgi.py",
            "index.js", "index.ts", "main.ts", "main.js",
            "main.go", "main.java", "application.py",
        }
        found: List[str] = []
        seen: set = set()
        for f in signal_files + root_files:
            name = f.split("/")[-1].lower()
            if name in entrypoint_names and f not in seen:
                found.append(f)
                seen.add(f)
        return found

    # ------------------------------------------------------------------
    # LLM refinement layer
    # ------------------------------------------------------------------

    def _build_context_text(
        self,
        quick_scan: Dict[str, Any],
        architecture_summary: str,
        repo_summary: Dict[str, Any] | None,
        primary_stack: List[str],
    ) -> str:
        parts: List[str] = []

        if architecture_summary:
            parts.append(f"Architecture summary: {architecture_summary}")

        if primary_stack:
            parts.append(f"Primary stack: {', '.join(primary_stack)}")

        hints = quick_scan.get("hints", {})
        if hints:
            active_hints = [k for k, v in hints.items() if v]
            if active_hints:
                parts.append(f"Detected hints: {', '.join(active_hints)}")

        top_dirs = quick_scan.get("top_level_dirs", [])
        if top_dirs:
            parts.append(f"Top-level directories: {', '.join(top_dirs[:15])}")

        signal_files = quick_scan.get("signal_files", [])
        if signal_files:
            parts.append(f"Key files detected: {', '.join(signal_files[:20])}")

        if repo_summary:
            tech = repo_summary.get("tech_stack") or repo_summary.get("technologies") or []
            if tech:
                parts.append(f"Tech stack from readme: {', '.join(str(t) for t in tech[:10])}")

        return "\n".join(parts)

    def _llm_refine(self, context_text: str) -> Dict[str, Any]:
        raw = self._llm.chat_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=(
                f"Repository context:\n{context_text}\n\n"
                "Classify the repository. Return only the JSON object described above."
            ),
            temperature=0.1,
            max_tokens=256,
        )

        logger.debug(
            "[ApplicationProfilerService] LLM raw response: %s",
            json.dumps(raw, ensure_ascii=False) if isinstance(raw, dict) else repr(raw),
        )

        if not isinstance(raw, dict):
            logger.warning(
                "[ApplicationProfilerService] chat_json returned %s (expected dict) — treating as empty.",
                type(raw).__name__,
            )
            return {}

        return raw


# ---------------------------------------------------------------------------
# Internal mapping helpers
# ---------------------------------------------------------------------------

_DB_LABEL_MAP: Dict[str, str] = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "mariadb": "mariadb",
    "mongodb": "mongodb",
    "mongo": "mongodb",
    "sqlite": "sqlite",
    "mssql": "mssql",
    "sqlserver": "mssql",
    "cassandra": "cassandra",
    "dynamodb": "dynamodb",
    "firestore": "firestore",
    "supabase": "postgresql",
    "planetscale": "mysql",
}
