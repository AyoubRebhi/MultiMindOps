from __future__ import annotations

import logging
import time
from typing import Any, Dict

import httpx

from backend.app.core.config import settings
from backend.app.services.core.llm_service import LLMService
from backend.app.services.llm.lightning_client import LightningClient

logger = logging.getLogger(__name__)


class LLMRouter:
    """
    Primary/fallback LLM router for TerraformAgent.

    - Primary: Lightning (OpenAI-compatible)
    - Fallback: Groq
    """

    _LIGHTNING_MAX_ATTEMPTS = 2

    def __init__(
        self,
        provider: str = "lightning",
        lightning_timeout_seconds: float = 45.0,
    ) -> None:
        self.provider = (provider or settings.TERRAFORM_LLM_PROVIDER).strip().lower()
        self.lightning_model = settings.LIGHTNING_MODEL
        self.groq_model = settings.GROQ_FALLBACK_MODEL or settings.GROQ_MODEL
        self._lightning_timeout_seconds = lightning_timeout_seconds

        self._lightning: LightningClient | None = None
        if self.provider != "groq":
            self._lightning = LightningClient(
                api_key=settings.LIGHTNING_API_KEY,
                base_url=settings.LIGHTNING_BASE_URL,
                model=self.lightning_model,
                timeout_seconds=self._lightning_timeout_seconds,
            )
        self._groq = self._build_groq_service()

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 3200,
    ) -> Dict[str, Any]:
        if self.provider == "groq":
            return self._chat_with_groq(system_prompt, user_prompt, temperature, max_tokens)

        lightning_error: Exception | None = None
        for attempt in range(1, self._LIGHTNING_MAX_ATTEMPTS + 1):
            t0 = time.monotonic()
            try:
                if self._lightning is None:
                    raise RuntimeError("Lightning primary provider is unavailable.")
                payload = self._lightning.chat(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                latency_ms = int((time.monotonic() - t0) * 1000)
                usage = self._lightning.extract_usage(payload)
                logger.info(
                    "[LLM] provider=lightning model=%s latency=%dms tokens=%d",
                    self.lightning_model,
                    latency_ms,
                    usage["total_tokens"],
                )
                return self._lightning._safe_json_loads(self._lightning.extract_content(payload))
            except Exception as exc:
                lightning_error = exc
                if attempt >= self._LIGHTNING_MAX_ATTEMPTS or not self._is_retriable_lightning_error(exc):
                    break
                logger.warning(
                    "[LLM] provider=lightning retry=%d/%d reason=%s",
                    attempt,
                    self._LIGHTNING_MAX_ATTEMPTS,
                    self._classify_error(exc),
                )

        logger.warning(
            "[LLM] fallback=groq reason=%s",
            self._classify_error(lightning_error),
        )
        return self._chat_with_groq(system_prompt, user_prompt, temperature, max_tokens)

    def _chat_with_groq(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        if self._groq is None:
            raise RuntimeError("Groq fallback is unavailable: GROQ_API_KEY is not configured.")
        payload = self._groq.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "[LLM] provider=groq model=%s latency=%dms tokens=%s",
            self.groq_model,
            latency_ms,
            "n/a",
        )
        return payload

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
    def _is_retriable_lightning_error(exc: Exception) -> bool:
        if isinstance(exc, httpx.TimeoutException):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in (429,)
        reason = str(exc).lower()
        if "timeout" in reason:
            return True
        return "429" in reason

    @staticmethod
    def _classify_error(exc: Exception | None) -> str:
        if exc is None:
            return "unknown"
        if isinstance(exc, httpx.TimeoutException):
            return "timeout"
        if isinstance(exc, httpx.HTTPStatusError):
            code = exc.response.status_code
            if code in (401, 403):
                return "401"
            if code == 429:
                return "429"
            return str(code)
        text = str(exc).lower()
        if "timeout" in text:
            return "timeout"
        if "401" in text or "auth" in text:
            return "401"
        if "429" in text or "rate" in text:
            return "429"
        return text[:64]
