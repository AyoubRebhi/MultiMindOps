"""LLM-powered file priority engine (OpenAI-compatible backend)."""
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from backend.app.services.core.glm_service import LLMClient, get_glm_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a DevSecOps expert analyzing code repositories to automate infrastructure and CI/CD.
Given a lightweight repository structure summary, select the MOST CRITICAL files
needed to understand the project and generate infrastructure automation.

Focus on:
1. Application entrypoints (main.py, app.py, index.js, server.ts, manage.py, etc.)
2. Dependency manifests (requirements.txt, package.json, pom.xml, pyproject.toml)
3. Container definitions (Dockerfile, docker-compose.yml/yaml)
4. CI/CD workflows (.github/workflows/*.yml)
5. Infrastructure-as-Code (*.tf, k8s/*.yml, helm/Chart.yaml)
6. Architecture documentation (README.md, docs/)
7. Configuration files (application.yml, .env.example)

Rules:
- Return between 5 and 20 files maximum.
- Rank by importance descending (1 = most critical).
- Avoid test files, generated files, lock files, node_modules, venv.
- If this is a monorepo, select the primary entrypoint per service.
- Output ONLY valid JSON, no explanation.

Output format (strict JSON):
{
  "critical_files": [
    {
      "path": "backend/src/main.py",
      "priority": 1,
      "reason": "FastAPI application entrypoint; defines all routes",
      "category": "entrypoint"
    }
  ],
  "architecture_hint": "multi-service monorepo with React frontend and FastAPI backend",
  "primary_stack": ["Python", "FastAPI", "Docker", "GitHub Actions"]
}
"""

# ---------------------------------------------------------------------------
# Token-budget constants
# ---------------------------------------------------------------------------

# File names / patterns that must always be sent to the LLM regardless of
# how many files the repository contains.
_CRITICAL_FILENAMES = frozenset({
    "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml",
    "package.json",
    "requirements.txt", "requirements-backend.txt",
    "pyproject.toml",
    "pom.xml", "build.gradle",
    "Chart.yaml",
    "main.py", "app.py", "manage.py", "server.py",
    "index.js", "index.ts", "main.ts", "main.go",
    "README.md",
    ".env.example", ".env.template",
    "main.tf",
})

# Maximum number of file paths forwarded to the LLM.  Keeps the prompt under
# ~4 k tokens even for very large repos.
_MAX_FILES_FOR_LLM = 150


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileRanking:
    path: str
    priority: int
    reason: str
    category: str  # entrypoint | dependency | infra | ci_cd | config | docs


@dataclass
class PriorityResult:
    critical_files: List[FileRanking] = field(default_factory=list)
    architecture_hint: str = ""
    primary_stack: List[str] = field(default_factory=list)
    llm_used: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_critical_path(file_path: str) -> bool:
    """Return True if *file_path* should always be included in the LLM prompt."""
    name = file_path.split("/")[-1]
    return (
        name in _CRITICAL_FILENAMES
        or ".github/workflows/" in file_path
        or file_path.endswith(".tf")
        or any(
            file_path.startswith(prefix)
            for prefix in ("k8s/", "kubernetes/", "helm/", "infra/")
        )
    )


def _truncate_file_list(files: List[str], max_count: int) -> List[str]:
    """
    Guarantee critical files are always present; trim the rest so the total
    stays within *max_count*.  Preserves original ordering within each group.
    """
    if len(files) <= max_count:
        return files

    critical: List[str] = []
    others: List[str] = []
    seen: set = set()

    for f in files:
        if f in seen:
            continue
        seen.add(f)
        (critical if _is_critical_path(f) else others).append(f)

    remaining_slots = max(0, max_count - len(critical))
    trimmed_others = others[:remaining_slots]

    logger.debug(
        "[LLMPriorityEngine] File list truncated: %d critical + %d sampled "
        "(original=%d, limit=%d)",
        len(critical),
        len(trimmed_others),
        len(files),
        max_count,
    )
    return critical + trimmed_others


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class LLMPriorityEngine:
    """
    Selects the 5–20 most critical repository files via an OpenAI-compatible
    LLM (LLaMA 3, Mixtral, Mistral, …).  Configured through:

        LLM_API_KEY   — provider API key
        LLM_BASE_URL  — endpoint base URL  (e.g. https://api.groq.com/openai/v1)
        LLM_MODEL     — model identifier   (e.g. llama3-70b-8192)

    Falls back to heuristic selection when the LLM call fails.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._client = llm_client  # lazy-initialised on first use

    @property
    def _llm(self) -> LLMClient:
        if self._client is None:
            self._client = get_glm_service()  # factory returns the singleton LLMClient
        return self._client

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def rank(
        self,
        quick_scan: Dict[str, Any],
        user_prompt: str | None = None,
        max_files: int = 20,
    ) -> PriorityResult:
        """Rank files by importance; fall back to heuristics on any error."""
        try:
            result = self._llm_rank(quick_scan, user_prompt, max_files)
            result.llm_used = True
            return result
        except Exception as exc:
            logger.warning(
                "[LLMPriorityEngine] LLM ranking failed (%s) — using heuristic fallback.", exc
            )
            return self._heuristic_rank(quick_scan, max_files)

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    def _llm_rank(
        self,
        quick_scan: Dict[str, Any],
        user_prompt: str | None,
        max_files: int,
    ) -> PriorityResult:
        # Build a token-budget-aware scan summary
        signal_files: List[str] = quick_scan.get("signal_files", [])
        root_files: List[str] = quick_scan.get("root_files", [])

        # Deduplicate and merge; signal_files take precedence
        all_files: List[str] = signal_files + [f for f in root_files if f not in set(signal_files)]
        truncated_files = _truncate_file_list(all_files, _MAX_FILES_FOR_LLM)

        scan_summary = {
            "files": truncated_files,
            "top_level_dirs": quick_scan.get("top_level_dirs", []),
            "languages_hinted": quick_scan.get("languages_hinted", []),
            "hints": quick_scan.get("hints", {}),
            "size_category": quick_scan.get("size_category", "unknown"),
            "truncated": len(all_files) > _MAX_FILES_FOR_LLM,
            "total_files_seen": len(all_files),
        }

        user_parts = [
            f"Repository structure:\n{json.dumps(scan_summary, indent=2, ensure_ascii=False)}",
        ]
        if user_prompt:
            user_parts.append(f"\nUser request context: {user_prompt}")
        user_parts.append(f"\nSelect at most {max_files} critical files.")

        raw = self._llm.chat_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt="\n".join(user_parts),
            temperature=0.1,   # deterministic; must be <= 0.3
            max_tokens=1500,
        )

        logger.debug(
            "[LLMPriorityEngine] Raw LLM response (truncated): %.500s",
            json.dumps(raw, ensure_ascii=False),
        )

        files: List[FileRanking] = []
        for item in raw.get("critical_files", []):
            files.append(FileRanking(
                path=str(item.get("path", "")),
                priority=int(item.get("priority", 99)),
                reason=str(item.get("reason", "")),
                category=str(item.get("category", "general")),
            ))

        files.sort(key=lambda f: f.priority)

        return PriorityResult(
            critical_files=files[:max_files],
            architecture_hint=str(raw.get("architecture_hint", "")),
            primary_stack=list(raw.get("primary_stack", [])),
        )

    # ------------------------------------------------------------------
    # Heuristic fallback (no LLM)
    # ------------------------------------------------------------------

    def _heuristic_rank(self, quick_scan: Dict[str, Any], max_files: int) -> PriorityResult:
        signal_files: List[str] = quick_scan.get("signal_files", [])
        root_files: List[str] = quick_scan.get("root_files", [])
        hints: Dict[str, Any] = quick_scan.get("hints", {})
        langs: List[str] = quick_scan.get("languages_hinted", [])

        priority_map = {
            # entrypoints
            "main.py": (1, "entrypoint"),
            "app.py": (1, "entrypoint"),
            "manage.py": (1, "entrypoint"),
            "server.py": (1, "entrypoint"),
            "index.js": (1, "entrypoint"),
            "index.ts": (1, "entrypoint"),
            "main.ts": (1, "entrypoint"),
            "main.go": (1, "entrypoint"),
            # dependencies
            "requirements.txt": (2, "dependency"),
            "requirements-backend.txt": (2, "dependency"),
            "pyproject.toml": (2, "dependency"),
            "package.json": (2, "dependency"),
            "pom.xml": (2, "dependency"),
            "build.gradle": (2, "dependency"),
            # infra
            "Dockerfile": (3, "infra"),
            "docker-compose.yml": (3, "infra"),
            "docker-compose.yaml": (3, "infra"),
            "main.tf": (3, "infra"),
            "Chart.yaml": (3, "infra"),
            # docs
            "README.md": (4, "docs"),
            ".env.example": (5, "config"),
            ".env.template": (5, "config"),
        }

        ranked: List[FileRanking] = []
        seen: set = set()

        all_candidates = signal_files + [f for f in root_files if f not in signal_files]

        for file_path in all_candidates:
            filename = file_path.split("/")[-1]
            if file_path in seen:
                continue
            seen.add(file_path)

            if ".github/workflows/" in file_path:
                ranked.append(FileRanking(
                    path=file_path,
                    priority=3,
                    reason="CI/CD workflow definition",
                    category="ci_cd",
                ))
                continue

            if file_path.endswith(".tf") or file_path.startswith(("k8s/", "kubernetes/")):
                ranked.append(FileRanking(
                    path=file_path,
                    priority=3,
                    reason="Infrastructure as Code",
                    category="infra",
                ))
                continue

            if filename in priority_map:
                pri, cat = priority_map[filename]
                ranked.append(FileRanking(
                    path=file_path,
                    priority=pri,
                    reason=f"Key {cat} file",
                    category=cat,
                ))

        ranked.sort(key=lambda f: (f.priority, f.path))

        arch_hint = ""
        if hints.get("is_monorepo"):
            arch_hint = "monorepo"
        if hints.get("has_docker"):
            arch_hint += " with Docker"
        if hints.get("has_kubernetes"):
            arch_hint += " and Kubernetes"

        return PriorityResult(
            critical_files=ranked[:max_files],
            architecture_hint=arch_hint.strip(),
            primary_stack=langs,
            llm_used=False,
        )
