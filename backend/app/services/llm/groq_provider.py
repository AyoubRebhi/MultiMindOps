"""Groq provider — wraps existing LLMService for backward compatibility."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from backend.app.services.llm.base_provider import BaseLLMProvider
from backend.app.services.llm.models import LLMResponse

logger = logging.getLogger(__name__)


class GroqProvider(BaseLLMProvider):
    """
    Groq provider that delegates to the existing battle-tested LLMService.

    Preserves all existing behaviour:
      • Multi-key rotation (GROQ_API_KEY_1 … GROQ_API_KEY_6)
      • Per-key throttling and rate-limit handling
      • Exponential backoff on network errors
      • ASCII sanitisation for Windows locale safety

    The async path wraps the synchronous LLMService.chat() in a thread-pool
    executor so it never blocks the FastAPI event loop.
    """

    def __init__(self, llm_service=None) -> None:
        # Import lazily to avoid circular imports at module load time.
        if llm_service is None:
            from backend.app.services.core.llm_service import LLMService
            llm_service = LLMService()
        self._service = llm_service
        logger.info(
            "[GroqProvider] Initialized — model=%s keys=%d",
            self._service.model,
            self._service.key_manager.configured_keys_count,
        )

    # ── Identity ──────────────────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return "groq"

    @property
    def model_name(self) -> str:
        return self._service.model

    # ── Async path ────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        """Run synchronous LLMService.chat() in a thread-pool executor."""
        loop = asyncio.get_event_loop()
        t0 = time.monotonic()

        content = await loop.run_in_executor(
            None,
            lambda: self._service.chat(
                system_prompt=system_prompt or "",
                user_prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
        )

        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "[GroqProvider] async model=%s latency=%dms", self._service.model, latency_ms
        )
        return LLMResponse(
            content=content,
            provider="groq",
            model=self._service.model,
            latency_ms=latency_ms,
        )

    # ── Sync path ─────────────────────────────────────────────────────────────

    def generate_sync(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        """Direct synchronous call — zero overhead for sync callers."""
        t0 = time.monotonic()
        content = self._service.chat(
            system_prompt=system_prompt or "",
            user_prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.info(
            "[GroqProvider] sync model=%s latency=%dms", self._service.model, latency_ms
        )
        return LLMResponse(
            content=content,
            provider="groq",
            model=self._service.model,
            latency_ms=latency_ms,
        )
