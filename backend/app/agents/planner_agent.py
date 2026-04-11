"""
PlannerAgent — produces a ranked DevSecOps execution plan.

Upgrades over the previous single-plan version
-----------------------------------------------
1. **Multi-plan generation** — asks the LLM to generate three plan variants
   (minimal / standard / comprehensive) in a single call.

2. **Plan scoring** — each variant is scored on four axes:
   • Artifact coverage  — more needed artifacts = higher score.
   • Step quality       — clear, numbered steps.
   • Reasoning depth    — longer, more specific summary.
   • Complexity fit     — "medium" is the sweet spot; extremes are slightly
                          penalised to avoid over- and under-engineering.

3. **Best-plan selection** — the highest-scoring variant is returned.
   All three variants are stored in memory for context and debugging.

4. **Graceful fallback** — if multi-plan generation fails (parse error, LLM
   timeout, etc.) the agent falls back to the original single-plan approach
   to guarantee a result.

Public API (unchanged)
-----------------------
``PlannerAgent.run(prompt, planner_context) → dict``
Returns the same dict shape as before so the orchestrator needs no changes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ValidationError

from backend.app.agents.base_agent import BaseAgent
from backend.app.agents.memory import AgentMemory
from backend.app.services.core.llm_service import LLMService

logger = logging.getLogger(__name__)


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class PlannerResponseSchema(BaseModel):
    agent: str
    input_prompt: str
    steps: list[str]
    required_artifacts: list[str]
    estimated_complexity: Literal["low", "medium", "high"]
    reasoning_summary: str


class PlanVariant(BaseModel):
    """One plan variant returned by the multi-plan LLM call."""

    variant: Literal["minimal", "standard", "comprehensive"]
    input_prompt: str
    steps: list[str]
    required_artifacts: list[str]
    estimated_complexity: Literal["low", "medium", "high"]
    reasoning_summary: str
    description: str = ""


class MultiPlanResponse(BaseModel):
    """Expected shape of the multi-plan LLM response."""

    plans: list[PlanVariant]


# ── Multi-plan system prompt ──────────────────────────────────────────────────

_MULTI_PLAN_SUFFIX = """
=== MULTI-PLAN MODE ===
Generate THREE plan alternatives and return them as a JSON object with a
"plans" array. Each plan must have these keys:

  "variant"              : "minimal" | "standard" | "comprehensive"
  "input_prompt"         : (string) restate the user task
  "steps"                : (array of strings) ordered execution steps
  "required_artifacts"   : (array of file-path strings)
  "estimated_complexity" : "low" | "medium" | "high"
  "reasoning_summary"    : (string) one-paragraph rationale
  "description"          : (string) one-sentence description of this variant

Plan definitions:
  • minimal        — only the essential artifacts to run the project.
  • standard       — the recommended balanced approach.
  • comprehensive  — full coverage including monitoring, security scans, IaC.

Respond with ONLY valid JSON — no markdown, no prose, no code fences.
"""


# ── Agent ─────────────────────────────────────────────────────────────────────


class PlannerAgent(BaseAgent):
    """
    Autonomous planner that generates, scores, and returns the best
    DevSecOps execution plan for a given user task.

    Memory
    ------
    ``self.memory`` caches the winning plan per prompt hash so repeated calls
    with the same input skip the LLM entirely.
    """

    def __init__(self, prompt_template: str):
        super().__init__(name="PlannerAgent")
        self.llm = LLMService()
        self.prompt_template = prompt_template
        self.memory = AgentMemory(agent_name="PlannerAgent")

    # ── Public interface ──────────────────────────────────────────────────────

    def run(
        self,
        prompt: str,
        planner_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Generate a ranked execution plan.

        1. Try multi-plan generation (3 variants, scored, best selected).
        2. Fall back to single-plan generation if multi-plan fails.
        3. Normalise and return the plan dict.
        """
        user_prompt = f"User task:\n{prompt}\n\nRepository context:\n{planner_context or {}}"

        # ── Memory cache check ────────────────────────────────────────────────
        cached = self.memory.recall(user_prompt)
        if cached and cached.confidence >= 0.7:
            logger.info("[PlannerAgent] Cache hit — returning memorised plan")
            return cached.output

        # ── Try multi-plan ────────────────────────────────────────────────────
        plan = self._try_multi_plan(prompt, planner_context, user_prompt)

        if plan is None:
            logger.info("[PlannerAgent] Multi-plan failed — falling back to single-plan")
            plan = self._single_plan(prompt, planner_context, user_prompt)

        normalised = self._normalize_plan(plan, prompt=prompt, planner_context=planner_context)
        self.memory.remember(user_prompt, normalised, confidence=0.9)
        return normalised

    # ── Multi-plan generation ─────────────────────────────────────────────────

    def _try_multi_plan(
        self,
        prompt: str,
        planner_context: Optional[Dict[str, Any]],
        user_prompt: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Ask the LLM to generate three plan variants in one call.
        Returns the best-scoring variant as a plain dict, or None on failure.
        """
        multi_system_prompt = self.prompt_template + _MULTI_PLAN_SUFFIX
        multi_user_prompt = (
            f"User task:\n{prompt}\n\n"
            f"Repository context:\n{planner_context or {}}"
        )

        try:
            raw = self.llm.chat_json(
                system_prompt=multi_system_prompt,
                user_prompt=multi_user_prompt,
                temperature=0.3,
                max_tokens=2200,
            )
        except Exception as exc:
            logger.warning("[PlannerAgent] Multi-plan LLM call failed: %s", exc)
            return None

        # Parse multi-plan response
        try:
            parsed = MultiPlanResponse.model_validate(raw)
        except (ValidationError, Exception) as exc:
            logger.warning("[PlannerAgent] Multi-plan parse failed: %s", exc)
            return None

        if not parsed.plans:
            logger.warning("[PlannerAgent] Multi-plan returned empty plans list")
            return None

        # Score and select the best plan
        scored = [
            (variant, self._score_plan(variant.model_dump(), prompt))
            for variant in parsed.plans
        ]
        scored.sort(key=lambda t: t[1], reverse=True)

        winner, best_score = scored[0]
        logger.info(
            "[PlannerAgent] Multi-plan winner: variant=%s score=%.3f",
            winner.variant,
            best_score,
        )

        # Log alternatives into memory for debugging
        self.memory.record_decision(
            decision=f"multi_plan_winner:{winner.variant}",
            reasoning=(
                f"Scored {best_score:.3f}. "
                f"Variants: {[(v.variant, round(s, 3)) for v, s in scored]}"
            ),
            confidence=best_score,
            context={
                "variants": [
                    {"variant": v.variant, "score": round(s, 3), "artifacts": v.required_artifacts}
                    for v, s in scored
                ]
            },
        )

        # Convert the winning PlanVariant to the standard plan dict shape
        return {
            "agent": "PlannerAgent",
            "input_prompt": winner.input_prompt,
            "steps": winner.steps,
            "required_artifacts": winner.required_artifacts,
            "estimated_complexity": winner.estimated_complexity,
            "reasoning_summary": winner.reasoning_summary,
            # Extra metadata kept in the plan for observability
            "plan_variant": winner.variant,
            "plan_score": round(best_score, 3),
            "plan_description": winner.description,
            "plan_alternatives": [
                {
                    "variant": v.variant,
                    "score": round(s, 3),
                    "description": v.description,
                    "required_artifacts": v.required_artifacts,
                    "estimated_complexity": v.estimated_complexity,
                }
                for v, s in scored
            ],
        }

    # ── Single-plan fallback ──────────────────────────────────────────────────

    def _single_plan(
        self,
        prompt: str,
        planner_context: Optional[Dict[str, Any]],
        user_prompt: str,
    ) -> Dict[str, Any]:
        """Original single-plan generation (kept as fallback)."""
        response = self.llm.chat_json(
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=1400,
        )

        if "ERROR" in response or "error" in response:
            raise ValueError(f"Planner provider returned an error payload: {response}")

        try:
            validated = PlannerResponseSchema.model_validate(response)
        except ValidationError as exc:
            raise ValueError(
                f"Planner returned an invalid JSON structure: {exc}"
            ) from exc

        return validated.model_dump()

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_plan(self, plan: Dict[str, Any], prompt: str) -> float:
        """
        Score a plan variant on a 0–2 scale across four axes.

        Axis                  Max   Notes
        ─────────────────────────────────────────────────────────
        Artifact coverage     0.6   0.1 per artifact, up to 6
        Step quality          0.5   0.1 per step, up to 5
        Reasoning depth       0.5   proportional to summary length
        Complexity fit        0.4   "medium" scores highest
        """
        score = 0.0

        # -- Artifact coverage -------------------------------------------------
        artifacts = plan.get("required_artifacts") or []
        score += min(0.6, len(artifacts) * 0.1)

        # -- Step quality ------------------------------------------------------
        steps = plan.get("steps") or []
        score += min(0.5, len(steps) * 0.1)

        # -- Reasoning depth ---------------------------------------------------
        reasoning = plan.get("reasoning_summary") or ""
        score += min(0.5, len(reasoning) / 300)  # max at 150+ chars

        # -- Complexity fit ----------------------------------------------------
        complexity_scores: Dict[str, float] = {"low": 0.2, "medium": 0.4, "high": 0.2}
        score += complexity_scores.get(plan.get("estimated_complexity", "medium"), 0.2)

        return round(score, 4)

    # ── Normalisation (unchanged from original) ───────────────────────────────

    def _normalize_plan(
        self,
        plan: Dict[str, Any],
        *,
        prompt: str,
        planner_context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        normalized = dict(plan)
        required_artifacts = [
            self._normalize_artifact_path(item)
            for item in normalized.get("required_artifacts", [])
            if str(item or "").strip()
        ]

        github_actions_only: List[str] = []
        cicd_requested = self._cicd_is_requested(prompt=prompt, planner_context=planner_context)

        for path in required_artifacts:
            if self._is_disallowed_cicd_artifact(path.lower()):
                cicd_requested = True
                continue
            github_actions_only.append(path)

        if cicd_requested and not any(
            self._is_supported_github_actions_artifact(p) for p in github_actions_only
        ):
            github_actions_only.append(".github/workflows/ci-cd.yml")

        normalized["required_artifacts"] = self._dedupe_preserve_order(github_actions_only)
        return normalized

    # ── Path helpers (unchanged) ───────────────────────────────────────────────

    def _cicd_is_requested(
        self,
        *,
        prompt: str,
        planner_context: Optional[Dict[str, Any]],
    ) -> bool:
        text = f"{prompt}\n{planner_context or {}}".lower()
        return any(
            marker in text
            for marker in (
                "ci/cd", "cicd", "pipeline", "github actions", "workflow",
                "jenkins", "gitlab ci", "azure pipelines", "circleci",
            )
        )

    def _normalize_artifact_path(self, path: str) -> str:
        lowered = str(path).replace("\\", "/").strip()
        if self._is_supported_github_actions_artifact(lowered):
            return ".github/workflows/ci-cd.yml"
        return lowered

    def _is_supported_github_actions_artifact(self, path: str) -> bool:
        lowered = str(path).lower()
        return lowered.startswith(".github/workflows/") and lowered.endswith((".yml", ".yaml"))

    def _is_disallowed_cicd_artifact(self, path: str) -> bool:
        return any(
            token in path
            for token in (
                "jenkinsfile", ".gitlab-ci", "azure-pipelines",
                ".circleci/", "scripts/build.sh", "scripts/deploy.sh",
            )
        )

    def _dedupe_preserve_order(self, items: List[str]) -> List[str]:
        seen: set[str] = set()
        result: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result
