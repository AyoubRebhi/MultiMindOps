"""
LLM-as-a-Judge service for DevSecOps execution plans.

Evaluates a plan on four metrics tailored to downstream agent usage:
  • Completeness   — all required artifacts named, full scope covered
  • Clarity        — steps are numbered, actionable, unambiguous
  • Agent-Readiness — does each step map to what InfrastructureAgent / CICDAgent expect?
  • Security Fit   — are security concerns (secrets, scanning, SAST) explicitly addressed?

Returns a structured dict compatible with the /evaluation/plan endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from backend.app.services.core.llm_service import LLMService, get_llm_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unicode-safe helpers (module-level so tests can import them directly)
# ---------------------------------------------------------------------------

def _safe_log(message: str, level: str = "info") -> None:
    """Log a message, falling back to ASCII replace encoding on non-UTF-8 streams."""
    try:
        getattr(logger, level)(message)
    except UnicodeEncodeError:
        # UTF-8 can represent all Unicode — the replace handler only helps on
        # ASCII/cp1252 streams, so we must encode to ASCII here.
        safe_msg = message.encode("ascii", errors="replace").decode("ascii")
        getattr(logger, level)(safe_msg)


def _serialize_json(data: dict) -> str:
    """Serialize *data* to a JSON string that preserves non-ASCII characters."""
    return json.dumps(data, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior DevSecOps architect reviewing an AI-generated execution plan.

Evaluate the plan on EXACTLY four metrics using the rubrics below.

=== SCORING RUBRICS ===

COMPLETENESS (0-100):
  +25  All artifacts mentioned in "required_artifacts" match the stated scope
  +25  No obvious gaps (e.g. Dockerfile without .dockerignore, k8s without configmap)
  +25  Environment variable handling described (how secrets reach the container)
  +25  Post-deployment validation or health-check steps included

CLARITY (0-100):
  +25  Steps are numbered, imperative, and unambiguous (no "configure things")
  +25  Each step has a single, well-scoped responsibility
  +25  Steps reference concrete file names or artifact keys from required_artifacts
  +25  Reasoning summary explains trade-offs, not just restating the prompt

AGENT_READINESS (0-100):
  +25  Steps map directly to InfrastructureAgent inputs (Dockerfile, compose, IaC)
  +25  CI/CD steps reference GitHub Actions workflow files specifically
  +25  Artifact keys use standard names (dockerfile, docker_compose, terraform_main …)
  +25  Plan complexity (low/medium/high) is consistent with the artifact count and steps

SECURITY_FIT (0-100):
  +25  Secrets management is explicitly addressed (env vars, Vault, GitHub Secrets)
  +25  At least one security scanning step present (SAST, image scan, secret scan)
  +25  Non-root container user mentioned or referenced
  +25  Security artifacts included (e.g. .github/workflows/security-scan.yml or notes)

=== GLOBAL SCORE ===
Weighted average:
  completeness    * 0.30
  clarity         * 0.20
  agent_readiness * 0.25
  security_fit    * 0.25

=== OUTPUT FORMAT ===
Respond with ONLY a valid JSON object - no markdown fences, no prose.

{
  "global_score": <integer 0-100>,
  "metrics": {
    "completeness":    { "score": <0-100>, "feedback": "<2-3 sentences>" },
    "clarity":         { "score": <0-100>, "feedback": "<2-3 sentences>" },
    "agent_readiness": { "score": <0-100>, "feedback": "<2-3 sentences>" },
    "security_fit":    { "score": <0-100>, "feedback": "<2-3 sentences>" }
  },
  "recommendations": [
    "<specific, actionable recommendation 1>",
    "<specific, actionable recommendation 2>",
    "<specific, actionable recommendation 3>"
  ],
  "detailed_report": "<3-5 sentence narrative of overall plan quality>"
}
"""

_WEIGHTS = {
    "completeness": 0.30,
    "clarity": 0.20,
    "agent_readiness": 0.25,
    "security_fit": 0.25,
}


class PlanJudgeService:
    """
    Evaluate a DevSecOps execution plan with an LLM judge (Groq / OpenAI-compatible).

    Usage::

        service = PlanJudgeService()
        result = service.evaluate_plan(
            plan=plan_dict,
            original_prompt="Set up CI/CD for a Spring Boot app",
            repository_context={"language": "Java", "framework": "Spring Boot"},
        )
    """

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        self._glm = llm_service or get_llm_service()

    def evaluate_plan(
        self,
        plan: Dict[str, Any],
        original_prompt: str,
        context: Optional[Dict[str, Any]] = None,
        repository_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate a plan dict and return a structured quality report.

        Args:
            plan:               The plan dict (keys: steps, required_artifacts,
                                reasoning_summary, estimated_complexity, …)
            original_prompt:    The user's original task description.
            context:            Optional hints/metadata for the evaluator.
            repository_context: Deprecated alias for context.

        Returns:
            dict with: global_score, metrics, recommendations, detailed_report
        """
        if not plan:
            return self._empty_result(reason="No plan provided")

        ctx = context or repository_context
        user_prompt = self._build_user_prompt(plan, original_prompt, ctx)

        try:
            raw = self._glm.chat_json(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=600,
            )
        except UnicodeEncodeError as exc:
            # UnicodeEncodeError inherits from ValueError; catch it first so it
            # is not mis-classified as a JSON-parse failure.
            _safe_log(f"[PlanJudgeService] Encoding error: {exc}", level="error")
            safe_reason = str(exc).encode("utf-8", errors="replace").decode("utf-8")
            return self._empty_result(reason=f"LLM call failed (encoding): {safe_reason}")
        except ValueError as exc:
            _safe_log(f"[PlanJudgeService] Parse error: {exc}", level="warning")
            safe_reason = str(exc).encode("utf-8", errors="replace").decode("utf-8")
            return self._empty_result(reason=f"LLM returned unparseable output: {safe_reason}")
        except Exception as exc:
            _safe_log(f"[PlanJudgeService] LLM call failed: {exc}", level="error")
            safe_reason = str(exc).encode("utf-8", errors="replace").decode("utf-8")
            return self._empty_result(reason=f"LLM call failed: {safe_reason}")

        return self._normalize(raw)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_user_prompt(
        self,
        plan: Dict[str, Any],
        original_prompt: str,
        context: Optional[Dict[str, Any]],
    ) -> str:
        steps = plan.get("steps") or []
        artifacts = plan.get("required_artifacts") or []
        complexity = plan.get("estimated_complexity") or "unknown"
        reasoning = plan.get("reasoning_summary") or ""
        variant = plan.get("plan_variant") or ""
        score = plan.get("plan_score")

        lines = [
            f"ORIGINAL USER PROMPT:\n{original_prompt}",
            "",
            "PLAN TO EVALUATE:",
            f"  Variant: {variant or 'single'}",
            f"  Internal score: {score if score is not None else 'n/a'}",
            f"  Complexity: {complexity}",
            f"  Steps ({len(steps)}):",
        ]
        for i, step in enumerate(steps, 1):
            lines.append(f"    {i}. {step}")

        lines.append(f"  Required artifacts ({len(artifacts)}):")
        for art in artifacts:
            lines.append(f"    - {art}")

        if reasoning:
            lines.append(f"  Reasoning summary:\n    {reasoning}")

        if context:
            lines.append("\nCONTEXT:")
            for k, v in context.items():
                lines.append(f"  {k}: {v}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Response normalization
    # ------------------------------------------------------------------

    def _normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {}
        weighted_sum = 0.0

        for name, weight in _WEIGHTS.items():
            metric_raw = raw.get("metrics", {}).get(name, {})
            score = _clamp(metric_raw.get("score", 50))
            feedback = str(metric_raw.get("feedback", "No feedback provided."))
            metrics[name] = {"score": score, "feedback": feedback}
            weighted_sum += score * weight

        recomputed = round(weighted_sum)
        raw_global = raw.get("global_score")
        global_score = _clamp(int(raw_global)) if isinstance(raw_global, (int, float)) else recomputed

        recommendations: List[str] = raw.get("recommendations", [])
        if not isinstance(recommendations, list):
            recommendations = []
        recommendations = [str(r) for r in recommendations[:3]]

        detailed_report = str(
            raw.get("detailed_report", "Evaluation complete. See metric feedback for details.")
        )

        return {
            "global_score": global_score,
            "metrics": metrics,
            "recommendations": recommendations,
            "detailed_report": detailed_report,
        }

    @staticmethod
    def _empty_result(reason: str = "") -> Dict[str, Any]:
        empty = {"score": 0, "feedback": reason or "Evaluation unavailable."}
        return {
            "global_score": 0,
            "metrics": {
                "completeness": empty,
                "clarity": empty,
                "agent_readiness": empty,
                "security_fit": empty,
            },
            "recommendations": [],
            "detailed_report": reason or "Plan evaluation could not be completed.",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: Any, lo: int = 0, hi: int = 100) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return 50


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_default_plan_judge: PlanJudgeService | None = None


def get_plan_judge_service() -> PlanJudgeService:
    global _default_plan_judge
    if _default_plan_judge is None:
        _default_plan_judge = PlanJudgeService()
    return _default_plan_judge
