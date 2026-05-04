from __future__ import annotations

import logging
import time
from typing import Any, Dict

from backend.app.core.config import settings
from backend.app.services.core.llm_service import LLMService
from backend.app.services.llm.github_client import GitHubLLMClient

logger = logging.getLogger(__name__)


class LLMRouter:
    """
    Primary/fallback LLM router for TerraformAgent and KubernetesAgent.

    - Primary : GitHub Models (Azure-backed, OpenAI-compatible)
    - Fallback : Groq

    Never silently swallows errors — every failure is logged with its reason
    and the fallback path is always explicit.
    """

    _GITHUB_MAX_ATTEMPTS = 2

    def __init__(
        self,
        provider: str = "",
        github_timeout_seconds: float = 45.0,
    ) -> None:
        # Empty string → read from settings so callers can just do LLMRouter()
        self.provider = (provider or settings.TERRAFORM_LLM_PROVIDER).strip().lower()
        self.github_model = settings.GITHUB_MODEL
        self.groq_model = settings.GROQ_FALLBACK_MODEL or settings.GROQ_MODEL
        self._github_timeout_seconds = github_timeout_seconds

        self._github: GitHubLLMClient | None = None
        if self.provider != "groq":
            self._github = GitHubLLMClient()

        self._groq = self._build_groq_service()

    # ── Public interface ──────────────────────────────────────────────────────

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 3200,
    ) -> Dict[str, Any]:
        if self.provider == "groq":
            return self._chat_with_groq(system_prompt, user_prompt, temperature, max_tokens)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        github_error: Exception | None = None
        for attempt in range(1, self._GITHUB_MAX_ATTEMPTS + 1):
            t0 = time.monotonic()
            try:
                if self._github is None:
                    raise RuntimeError("GitHub Models primary provider is not initialised.")

                content = self._github.chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                # Hard fail-safe — should already be caught inside the client,
                # but we enforce it at the router boundary as well.
                if not content or content.strip() == "":
                    raise RuntimeError("LLM returned empty output — generation failed")

                latency_ms = int((time.monotonic() - t0) * 1000)
                logger.info(
                    "[LLM] provider=github model=%s latency=%dms",
                    self.github_model,
                    latency_ms,
                )
                return LLMService._safe_json_loads(content)

            except Exception as exc:
                github_error = exc
                if attempt >= self._GITHUB_MAX_ATTEMPTS or not self._is_retriable_error(exc):
                    break
                logger.warning(
                    "[LLM] provider=github retry=%d/%d reason=%s",
                    attempt,
                    self._GITHUB_MAX_ATTEMPTS,
                    self._classify_error(exc),
                )

        logger.warning(
            "[LLM] GitHub failed — falling back to Groq. reason=%s",
            self._classify_error(github_error),
        )
        print(f"[LLM] Falling back to Groq... reason={self._classify_error(github_error)}")
        return self._chat_with_groq(system_prompt, user_prompt, temperature, max_tokens)

    # ── Groq fallback ─────────────────────────────────────────────────────────

    def _chat_with_groq(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        if self._groq is None:
            raise RuntimeError(
                "Groq fallback is unavailable — GROQ_API_KEY is not configured."
            )
        t0 = time.monotonic()
        payload = self._groq.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if not payload:
            raise RuntimeError("LLM returned empty output — generation failed")

        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "[LLM] provider=groq model=%s latency=%dms",
            self.groq_model,
            latency_ms,
        )
        return payload

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_groq_service() -> LLMService | None:
        try:
            service = LLMService()
            if settings.GROQ_FALLBACK_MODEL:
                service.model = settings.GROQ_FALLBACK_MODEL
            return service
        except Exception as exc:
            logger.warning("[LLM] Groq fallback unavailable: %s", exc)
            return None

    @staticmethod
    def _is_retriable_error(exc: Exception) -> bool:
        exc_type = type(exc).__name__
        if exc_type in ("APITimeoutError", "RateLimitError"):
            return True
        reason = str(exc).lower()
        return "timeout" in reason or "429" in reason or "rate" in reason

    @staticmethod
    def _classify_error(exc: Exception | None) -> str:
        if exc is None:
            return "unknown"
        exc_type = type(exc).__name__
        text = str(exc).lower()
        if exc_type == "APITimeoutError" or "timeout" in text:
            return "timeout"
        if exc_type == "AuthenticationError" or "401" in text or "auth" in text:
            return "401"
        if exc_type == "RateLimitError" or "429" in text or "rate" in text:
            return "429"
        if "empty" in text:
            return "empty_response"
        return text[:64]
