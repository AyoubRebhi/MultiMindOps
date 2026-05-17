"""
Base agent classes for the DevSecOps AI platform.

BaseAgent
---------
Unchanged abstract interface — all existing agents stay compatible.

EnhancedBaseAgent
-----------------
Production-grade base that adds:

  • ReAct loop  — iterative Reasoning + Action with configurable max iterations.
  • Memory      — short-term prompt/output cache + decision history.
  • Validation  — rule-based artifact checks (+ optional LLM fallback).
  • Confidence  — score degrades with each retry iteration.
  • Logging     — per-agent structured logger.

Subclasses override `run()` and optionally `_evaluate_quality()` to inject
domain-specific quality checks into the ReAct loop.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Abstract base (unchanged public contract) ─────────────────────────────────


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def run(self, *args, **kwargs) -> Dict[str, Any]:
        pass


# ── Enhanced base with ReAct + memory + validation ────────────────────────────


class EnhancedBaseAgent(BaseAgent):
    """
    Production-grade base agent.

    ReAct loop
    ----------
    Call ``react_loop(llm, system_prompt, user_prompt, evaluate_fn)`` instead
    of a bare ``llm.chat_json(...)`` call.  The loop:

    1. Checks the memory cache on the first attempt.
    2. Calls the LLM.
    3. Evaluates the response via *evaluate_fn* (or the default stub).
    4. If issues are found, appends a refinement instruction and retries.
    5. Stores the final result in memory with a confidence score.

    Parameters
    ----------
    name:                  Logical agent name — used for logging and memory keys.
    max_react_iterations:  Maximum ReAct iterations before returning the last
                           (possibly imperfect) result. Default: 3.

    Memory & Validation
    -------------------
    ``self.memory``     — AgentMemory instance (short-term, in-process).
    ``self.validation`` — ValidationService instance (rule-based by default).
    Both are lazily constructed to avoid circular import issues at module load.
    """

    # Confidence threshold — cached results below this score are ignored.
    _CACHE_MIN_CONFIDENCE: float = 0.7

    def __init__(self, name: str, max_react_iterations: int = 3):
        super().__init__(name=name)
        self.max_react_iterations = max_react_iterations
        self._log = logging.getLogger(f"agents.{name}")

        # Lazy-init avoids circular imports at module load time.
        from backend.app.agents.memory import AgentMemory
        from backend.app.services.validation.validation_service import ValidationService

        self.memory: AgentMemory = AgentMemory(agent_name=name)
        self.validation: ValidationService = ValidationService()

    # ── ReAct loop ────────────────────────────────────────────────────────────

    def react_loop(
        self,
        llm: Any,
        system_prompt: str,
        user_prompt: str,
        evaluate_fn: Optional[Callable[[Dict[str, Any]], List[str]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """
        Iterative Reasoning + Action loop.

        Parameters
        ----------
        llm            : LLMService instance — must expose ``chat_json()``.
        system_prompt  : Static system/persona prompt.
        user_prompt    : Initial user-facing prompt (extended on each retry).
        evaluate_fn    : ``(response: dict) → List[str]`` — returns a list of
                         issue strings; empty list means the output is acceptable.
                         Defaults to ``_default_evaluate``.
        temperature    : LLM temperature.
        max_tokens     : LLM max output tokens.

        Returns
        -------
        dict — the best LLM response obtained within the iteration budget.

        Raises
        ------
        RuntimeError   — if the LLM fails on every attempt (propagates the last
                         exception after the iteration budget is exhausted).
        """
        evaluator = evaluate_fn or self._default_evaluate
        current_prompt = user_prompt
        last_response: Optional[Dict[str, Any]] = None
        last_exc: Optional[Exception] = None
        iteration_limit = (
            1 if getattr(llm, "single_request_mode", False) else self.max_react_iterations
        )
        if iteration_limit == 1 and self.max_react_iterations > 1:
            self._log.info(
                "[%s] Single-request mode enabled; ReAct refinement retries disabled",
                self.name,
            )

        for attempt in range(1, iteration_limit + 1):
            self._log.info(
                "[%s] ReAct iteration %d/%d", self.name, attempt, iteration_limit
            )

            # ── 1. Cache check (first attempt only, unmodified prompt) ────────
            if attempt == 1:
                cached = self.memory.recall(user_prompt)
                if cached and cached.confidence >= self._CACHE_MIN_CONFIDENCE:
                    self._log.info(
                        "[%s] Cache hit — returning memorized output (conf=%.2f)",
                        self.name,
                        cached.confidence,
                    )
                    self.memory.record_decision(
                        "cache_hit",
                        "Returning cached output",
                        confidence=cached.confidence,
                    )
                    return cached.output

            # ── 2. LLM call ───────────────────────────────────────────────────
            try:
                response = llm.chat_json(
                    system_prompt=system_prompt,
                    user_prompt=current_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:
                last_exc = exc
                self._log.warning(
                    "[%s] LLM call failed (attempt %d/%d): %s",
                    self.name,
                    attempt,
                    iteration_limit,
                    exc,
                )
                if attempt < iteration_limit:
                    time.sleep(0.5 * attempt)
                    continue
                raise

            last_response = response

            # ── 3. Evaluate quality ───────────────────────────────────────────
            issues: List[str] = []
            try:
                issues = evaluator(response) or []
            except Exception as exc:
                self._log.warning(
                    "[%s] Evaluator raised on attempt %d: %s", self.name, attempt, exc
                )

            # ── 4a. No issues → memorise and return ───────────────────────────
            if not issues:
                confidence = max(0.5, 1.0 - 0.15 * (attempt - 1))
                self.memory.remember(user_prompt, response, confidence=confidence)
                self.memory.record_decision(
                    decision=f"react_ok_iter{attempt}",
                    reasoning="No quality issues detected",
                    confidence=confidence,
                )
                self._log.info(
                    "[%s] ReAct succeeded at iteration %d (conf=%.2f)",
                    self.name,
                    attempt,
                    confidence,
                )
                return response

            # ── 4b. Issues found → build refinement prompt and retry ──────────
            self._log.warning(
                "[%s] Quality issues at iteration %d: %s", self.name, attempt, issues
            )
            if iteration_limit == 1:
                self._log.warning(
                    "[%s] Returning first response with quality issues because single-request mode is enabled",
                    self.name,
                )
                self.memory.remember(user_prompt, response, confidence=0.45)
                return response
            current_prompt = self._build_refinement_prompt(user_prompt, issues, attempt)

        # ── 5. Iteration budget exhausted ────────────────────────────────────
        self._log.warning(
            "[%s] ReAct loop exhausted after %d iterations — returning last response",
            self.name,
            iteration_limit,
        )
        if last_response is not None:
            self.memory.remember(user_prompt, last_response, confidence=0.3)
            self.memory.record_decision(
                decision="react_exhausted",
                reasoning="Quality issues were not fully resolved within the iteration budget",
                confidence=0.3,
            )
            return last_response

        # All LLM calls failed — re-raise the last exception.
        if last_exc:
            raise last_exc
        raise RuntimeError(
            f"[{self.name}] ReAct loop produced no response after "
            f"{iteration_limit} iterations"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_refinement_prompt(
        original_prompt: str, issues: List[str], attempt: int
    ) -> str:
        """Append a structured refinement block to the original prompt."""
        issues_block = "\n".join(f"  • {issue}" for issue in issues)
        return (
            f"{original_prompt}\n\n"
            f"{'=' * 60}\n"
            f"REFINEMENT REQUEST — attempt {attempt}\n"
            f"{'=' * 60}\n"
            f"The previous output had the following issues that must ALL be fixed:\n"
            f"{issues_block}\n\n"
            f"Regenerate the complete output addressing every issue listed above."
        )

    def _default_evaluate(self, response: Dict[str, Any]) -> List[str]:
        """
        Minimal default quality gate — subclasses should override with
        domain-specific checks.

        Returns a list of issue strings (empty list = response is acceptable).
        """
        issues: List[str] = []
        if not response:
            issues.append("Response is empty")
        if isinstance(response, dict):
            error_val = response.get("error") or response.get("ERROR")
            if error_val:
                issues.append(f"LLM returned error payload: {error_val}")
        return issues

    @abstractmethod
    def run(self, *args, **kwargs) -> Dict[str, Any]:
        pass
