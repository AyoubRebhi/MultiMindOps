"""
LLM-as-a-Judge service — evaluates generated artifacts on 4 quality metrics.

Each evaluation returns per-metric scores (0-100) + a global score + top-3
recommendations.

Supported artifact types
------------------------
- dockerfile      — Dockerfile best practices, security, multi-stage
- docker-compose  — Compose files, secrets exposure, resource limits
- python          — Python code: syntax, patterns, complexity
- yaml            — Generic YAML (k8s manifests, CI configs, etc.)
- terraform       — HCL/Terraform: idempotency, security, modularity
- typescript      — TypeScript/JavaScript: typing, async patterns
- documentation   — Markdown docs: clarity, completeness, accuracy
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.app.services.core.llm_service import LLMService, get_llm_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring rubric embedded in system prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert DevSecOps code reviewer.

You will receive an artifact (source code, config file, or documentation) and
evaluate it across EXACTLY four metrics using the rubrics below.

=== SCORING RUBRICS ===

CORRECTION (0-100):
  +30  Syntax is valid and parseable
  +30  Logic has no contradictions or unreachable code
  +20  No unresolved placeholders (e.g. <YOUR_VALUE>, TODO, FIXME)
  +20  Coherent with the provided context (language, framework, constraints)

PERFORMANCE (0-100):
  +25  No obviously inefficient loops, N+1 queries, or redundant operations
  +25  Resources (memory, CPU, I/O) used optimally
  +25  Build / runtime optimized (caching, layer ordering, parallelism)
  +25  Caching and reuse layers well structured (e.g. pip install before COPY)

SECURITY (0-100):
  +30  No secrets, credentials, or API keys hard-coded
  +20  Non-root user, minimal permissions, principle of least privilege
  +20  Image/dependency vulnerability scanning configured or recommended
  +30  Secrets management in place or explicitly recommended

MAINTAINABILITY (0-100):
  +25  Code is clear, well-named, and commented where non-obvious
  +25  No duplicated logic; DRY principles followed
  +25  Configuration externalized (env vars, config files, not hardcoded)
  +25  Testable structure (dependency injection, separation of concerns)

=== OUTPUT FORMAT ===

Respond with ONLY a valid JSON object - no markdown fences, no prose.

{
  "global_score": <integer 0-100, weighted average of the four metrics>,
  "metrics": {
    "correction":      { "score": <0-100>, "feedback": "<2-4 sentences>" },
    "performance":     { "score": <0-100>, "feedback": "<2-4 sentences>" },
    "security":        { "score": <0-100>, "feedback": "<2-4 sentences>" },
    "maintainability": { "score": <0-100>, "feedback": "<2-4 sentences>" }
  },
  "recommendations": [
    "<actionable recommendation 1>",
    "<actionable recommendation 2>",
    "<actionable recommendation 3>"
  ],
  "detailed_report": "<3-6 sentence narrative summary of overall quality>"
}

Weights for global_score:
  correction      * 0.25
  performance     * 0.20
  security        * 0.35
  maintainability * 0.20
"""

# ---------------------------------------------------------------------------
# Per-artifact-type context injected into the user prompt
# ---------------------------------------------------------------------------

_ARTIFACT_CONTEXT: Dict[str, str] = {
    "dockerfile": (
        "Artifact type: Dockerfile.\n"
        "Focus on: multi-stage builds, non-root USER, HEALTHCHECK, layer caching "
        "(COPY requirements before COPY .), no secrets in ENV or ARG, minimal base image."
    ),
    "docker-compose": (
        "Artifact type: docker-compose.yml.\n"
        "Focus on: no plain-text passwords in environment block, use of secrets or "
        "env_file, healthchecks, depends_on conditions, network isolation, resource limits."
    ),
    "python": (
        "Artifact type: Python source code.\n"
        "Focus on: PEP-8, type annotations, exception handling, no bare except, "
        "no mutable default arguments, SQL injection risks, logging vs print."
    ),
    "yaml": (
        "Artifact type: Generic YAML configuration (Kubernetes, CI/CD, etc.).\n"
        "Focus on: schema validity, no secrets in plain text, correct indentation, "
        "resource limits (requests/limits), RBAC least-privilege."
    ),
    "terraform": (
        "Artifact type: Terraform HCL.\n"
        "Focus on: no hardcoded secrets, use of variables and outputs, "
        "backend state configuration, idempotency, resource tagging."
    ),
    "typescript": (
        "Artifact type: TypeScript/JavaScript source code.\n"
        "Focus on: strict typing (no any), async/await vs callbacks, "
        "error boundaries, no console.log in production paths, XSS risks."
    ),
    "documentation": (
        "Artifact type: Documentation (Markdown or plain text).\n"
        "Focus on: clarity of language, completeness (covers purpose, usage, "
        "examples), technical accuracy, absence of outdated references."
    ),
}

_DEFAULT_ARTIFACT_CONTEXT = (
    "Artifact type: generic software artifact.\n"
    "Apply all four metrics using general best practices."
)

# ---------------------------------------------------------------------------
# Metric weights
# ---------------------------------------------------------------------------

_WEIGHTS = {
    "correction": 0.25,
    "performance": 0.20,
    "security": 0.35,
    "maintainability": 0.20,
}


class LLMJudgeService:
    """
    Evaluate a generated artifact using an LLM judge (Groq / OpenAI-compatible).

    Usage::

        service = LLMJudgeService()
        result = service.evaluate_artifact(
            artifact_type="dockerfile",
            content=dockerfile_text,
            context={"framework": "FastAPI", "base_image": "python:3.11-slim"},
        )
    """

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self._glm = llm_service or get_llm_service()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_artifact(
        self,
        artifact_type: str,
        content: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a single artifact and return a structured quality report.

        Args:
            artifact_type: One of dockerfile | docker-compose | python |
                           yaml | terraform | typescript | documentation.
                           Unknown types fall back to generic evaluation.
            content:       Raw text content of the artifact.
            context:       Optional dict with additional hints for the LLM
                           (e.g. framework, language version, project name).

        Returns:
            dict with keys: global_score, metrics, recommendations,
            detailed_report, artifact_type.
        """
        if not content or not content.strip():
            return self._empty_result(artifact_type, reason="No content provided")

        user_prompt = self._build_user_prompt(artifact_type, content, context)

        try:
            raw = self._glm.chat_json(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,   # low temp for deterministic scoring
                max_tokens=1500,
            )
        except UnicodeEncodeError as exc:
            # UnicodeEncodeError inherits from ValueError; catch it first so it
            # is not mis-classified as a JSON-parse failure.
            safe_reason = str(exc).encode("ascii", errors="replace").decode("ascii")
            logger.error("LLM judge encoding error for %s: %s", artifact_type, safe_reason)
            return self._empty_result(
                artifact_type, reason=f"LLM call failed (encoding): {safe_reason}"
            )
        except ValueError as exc:
            logger.warning("LLM judge parse error for %s: %s", artifact_type, exc)
            return self._empty_result(
                artifact_type, reason=f"LLM returned unparseable output: {exc}"
            )
        except Exception as exc:
            logger.error("LLM judge call failed for %s: %s", artifact_type, exc)
            return self._empty_result(
                artifact_type, reason=f"LLM call failed: {exc}"
            )

        return self._normalize(raw, artifact_type)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        artifact_type: str,
        content: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        type_hint = _ARTIFACT_CONTEXT.get(artifact_type.lower(), _DEFAULT_ARTIFACT_CONTEXT)

        parts = [type_hint]

        if context:
            context_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
            parts.append(f"Additional context:\n{context_lines}")

        # Truncate very large artifacts to avoid token overflow
        truncated = content
        if len(content) > 6000:
            truncated = content[:6000] + "\n\n... [truncated for evaluation] ..."
            parts.append("Note: artifact was truncated to 6000 chars for evaluation.")

        parts.append(f"=== ARTIFACT TO EVALUATE ===\n{truncated}")

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Response normalization
    # ------------------------------------------------------------------

    def _normalize(self, raw: Dict[str, Any], artifact_type: str) -> Dict[str, Any]:
        """Clamp scores to [0, 100], recompute global_score, fill missing keys."""
        metrics: Dict[str, Any] = {}
        weighted_sum = 0.0

        for name, weight in _WEIGHTS.items():
            metric_raw = raw.get("metrics", {}).get(name, {})
            score = self._clamp(metric_raw.get("score", 50))
            feedback = str(metric_raw.get("feedback", "No feedback provided."))
            metrics[name] = {"score": score, "feedback": feedback}
            weighted_sum += score * weight

        recomputed_global = round(weighted_sum)
        raw_global = raw.get("global_score")
        if isinstance(raw_global, (int, float)):
            global_score = self._clamp(int(raw_global))
        else:
            global_score = recomputed_global

        recommendations = raw.get("recommendations", [])
        if not isinstance(recommendations, list):
            recommendations = []
        recommendations = [str(r) for r in recommendations[:3]]

        detailed_report = str(
            raw.get("detailed_report", "Evaluation complete. See metric feedback for details.")
        )

        return {
            "artifact_type": artifact_type,
            "global_score": global_score,
            "metrics": metrics,
            "recommendations": recommendations,
            "detailed_report": detailed_report,
        }

    @staticmethod
    def _clamp(value: Any, lo: int = 0, hi: int = 100) -> int:
        try:
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return 50

    @staticmethod
    def _empty_result(artifact_type: str, reason: str = "") -> Dict[str, Any]:
        """Return a zeroed-out result when evaluation cannot proceed."""
        empty_metric = {"score": 0, "feedback": reason or "Evaluation unavailable."}
        return {
            "artifact_type": artifact_type,
            "global_score": 0,
            "metrics": {
                "correction": empty_metric,
                "performance": empty_metric,
                "security": empty_metric,
                "maintainability": empty_metric,
            },
            "recommendations": [],
            "detailed_report": reason or "Evaluation could not be completed.",
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_default_judge: LLMJudgeService | None = None


def get_llm_judge_service() -> LLMJudgeService:
    global _default_judge
    if _default_judge is None:
        _default_judge = LLMJudgeService()
    return _default_judge
