"""
PlannerAgent — produces a single standard DevSecOps execution plan.

Sprint 3 note: multi-plan generation is deferred. This agent issues one
LLM call with a compressed context to stay within the Groq free-tier
12 k TPM limit (~5-7k tokens per request vs the previous ~15.6k).

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

# Maximum characters of planner_context forwarded to the LLM
_MAX_CONTEXT_CHARS = 500


# ── Pydantic schema ───────────────────────────────────────────────────────────


class PlannerResponseSchema(BaseModel):
    agent: str
    input_prompt: str
    steps: list[str]
    required_artifacts: list[str]
    estimated_complexity: Literal["low", "medium", "high"]
    reasoning_summary: str


# ── Agent ─────────────────────────────────────────────────────────────────────


class PlannerAgent(BaseAgent):
    """
    Generates a single standard DevSecOps execution plan per user task.

    Memory
    ------
    ``self.memory`` caches the plan per prompt hash so repeated calls with
    the same input skip the LLM entirely.
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
        Generate and return a standard execution plan.

        1. Check memory cache.
        2. Build a compressed user prompt (~5-7k tokens total).
        3. Call LLM once (single plan, standard variant).
        4. Validate, normalise, cache, and return.
        """
        compressed = self._compress_context(planner_context)
        user_prompt = f"User task:\n{prompt}\n\nRepository context:\n{compressed}"

        # ── Memory cache check ────────────────────────────────────────────────
        cached = self.memory.recall(user_prompt)
        if cached and cached.confidence >= 0.7:
            logger.info("[PlannerAgent] Cache hit — returning memorised plan")
            return cached.output

        plan = self._single_plan(prompt, user_prompt)
        normalised = self._normalize_plan(plan, prompt=prompt, planner_context=planner_context)
        self.memory.remember(user_prompt, normalised, confidence=0.9)
        return normalised

    # ── Single-plan generation ────────────────────────────────────────────────

    def _single_plan(self, prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Issue one LLM call and return the validated plan dict."""
        response = self.llm.chat_json(
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=900,
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

    # ── Context compression ───────────────────────────────────────────────────

    @staticmethod
    def _compress_context(planner_context: Optional[Dict[str, Any]]) -> str:
        """
        Extract the three most useful fields from the planner context and
        truncate the result to _MAX_CONTEXT_CHARS characters.

        Keeps: project_type, language, security_findings.
        Drops: verbose logs, full file trees, chunk lists, etc.
        """
        if not planner_context:
            return "{}"

        compressed: Dict[str, Any] = {}

        for key in ("project_type", "language", "framework", "runtime"):
            if planner_context.get(key):
                compressed[key] = planner_context[key]

        sec = planner_context.get("security_findings") or planner_context.get("security")
        if sec:
            sec_str = str(sec)[:200]
            compressed["security"] = sec_str
        else:
            compressed["security"] = "No issues"

        summary = str(compressed)
        if len(summary) > _MAX_CONTEXT_CHARS:
            summary = summary[:_MAX_CONTEXT_CHARS] + "…"
        return summary

    # ── Normalisation ─────────────────────────────────────────────────────────

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

    # ── Path helpers ──────────────────────────────────────────────────────────

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
