"""
ProviderFactory — multi-provider LLM orchestration layer.

Architecture:
  PRIMARY  : OpenAI GPT-5.4-mini  (Responses API for GPT-5 family)
  FALLBACK : Groq (existing LLMService with multi-key rotation)

Provider routing by agent:
  InfrastructureAgent, TerraformAgent, KubernetesAgent → OpenAI primary → Groq fallback
  All other agents                                      → Groq only

Fallback triggers on ANY primary failure:
  • timeout          (APITimeoutError)
  • rate limit       (RateLimitError / 429)
  • auth failure     (AuthenticationError / 401)
  • provider outage  (APIConnectionError)
  • SDK too old      (RuntimeError: Responses API unavailable)
  • malformed / empty response

Public interface — drop-in for both LLMService and LLMRouter callers:
  chat_json()               — sync, returns Dict[str, Any]
  chat()                    — sync, returns raw str
  generate_with_fallback()  — async, returns LLMResponse

Design choices:
  • OpenAI is tried ONLY when OPENAI_KEY is set — absence silently degrades to Groq.
  • ProviderFactory.for_agent(name) instantiates the correct factory for the agent.
  • Every provider switch is logged with reason so ops can investigate.
  • API keys are NEVER logged or included in exception messages.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from backend.app.services.llm.models import LLMResponse

# Agents that get OpenAI as primary provider; all others are Groq-only.
# Mirrors AGENT_PROVIDER_MAP in config/llm_config.py.
AGENT_PROVIDER_MAP: Dict[str, str] = {
    "InfrastructureAgent": "openai_primary",
    "TerraformAgent":      "openai_primary",
    "KubernetesAgent":     "openai_primary",
}

logger = logging.getLogger(__name__)


class ProviderFactory:
    """
    Orchestrates OpenAI (primary) → Groq (fallback) with full observability.

    Drop-in replacement for both LLMService and LLMRouter:
      • chat()             — sync, returns str
      • chat_json()        — sync, returns dict
      • generate_with_fallback() — async, returns LLMResponse
      • model property     — mirrors LLMService.model

    Usage in agents (explicit routing):
        self.llm = ProviderFactory.for_agent("InfrastructureAgent")
        # OR (backwards-compatible):
        self.llm = ProviderFactory()
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        openai_model: Optional[str] = None,
        openai_timeout: Optional[float] = None,
        openai_max_retries: Optional[int] = None,
        groq_service=None,
        _force_groq_only: bool = False,
    ) -> None:
        from backend.app.core.config import settings

        self._primary: Optional[Any] = None
        self._openai_enabled = False

        if not _force_groq_only:
            api_key = (openai_api_key or settings.OPENAI_KEY or "").strip()
            if api_key:
                try:
                    from backend.app.services.llm.openai_provider import OpenAIProvider
                    self._primary = OpenAIProvider(
                        api_key=api_key,
                        model=openai_model or settings.OPENAI_MODEL,
                        timeout=openai_timeout if openai_timeout is not None else settings.OPENAI_TIMEOUT,
                        max_retries=openai_max_retries if openai_max_retries is not None else settings.OPENAI_MAX_RETRIES,
                    )
                    self._openai_enabled = True
                    logger.info(
                        "[ProviderFactory] Initialized — primary=OpenAI/%s fallback=Groq",
                        self._primary.model_name,
                    )
                except Exception as exc:
                    logger.warning(
                        "[ProviderFactory] OpenAI provider init failed (%s) — Groq only",
                        type(exc).__name__,
                    )
            else:
                logger.info(
                    "[ProviderFactory] OPENAI_KEY not configured — using Groq as primary"
                )
        else:
            logger.info("[ProviderFactory] Groq-only mode (agent routing)")

        from backend.app.services.llm.groq_provider import GroqProvider
        self._fallback = GroqProvider(llm_service=groq_service)

    # ── Factory method: agent-aware routing ──────────────────────────────────

    @classmethod
    def for_agent(cls, agent_name: str, **kwargs) -> "ProviderFactory":
        """
        Create a ProviderFactory with the provider routing defined for the given agent.

        Agents mapped to "openai_primary" get OpenAI+Groq fallback.
        All others get Groq only (regardless of OPENAI_KEY).
        """
        route = AGENT_PROVIDER_MAP.get(agent_name, "groq")
        if route == "groq":
            logger.info(
                "[ProviderFactory] Agent '%s' → Groq-only (per AGENT_PROVIDER_MAP)",
                agent_name,
            )
            return cls(_force_groq_only=True, **kwargs)
        logger.info(
            "[ProviderFactory] Agent '%s' → OpenAI primary + Groq fallback",
            agent_name,
        )
        return cls(**kwargs)

    # ── Compatibility properties ──────────────────────────────────────────────

    @property
    def model(self) -> str:
        """Returns the active model name — mirrors LLMService.model."""
        if self._primary is not None:
            return self._primary.model_name
        return self._fallback.model_name

    # ── Async interface ───────────────────────────────────────────────────────

    async def generate_with_fallback(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        """
        Async generation: try OpenAI first, fall back to Groq on any error.

        Returns an LLMResponse with fallback_used=True when Groq was used.
        """
        if self._primary is not None:
            try:
                result = await self._primary.generate(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
                logger.info(
                    "[ProviderFactory] provider=openai model=%s api=%s latency=%dms tokens=%s",
                    result.model, result.api_type, result.latency_ms, result.total_tokens,
                )
                return result

            except Exception as exc:
                reason = _classify_error(exc)
                logger.warning(
                    "[ProviderFactory] OpenAI primary failed (%s) — switching to Groq fallback",
                    reason,
                )

        result = await self._fallback.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        result = result.model_copy(update={"fallback_used": True})
        logger.info(
            "[ProviderFactory] provider=groq model=%s latency=%dms [FALLBACK]",
            result.model, result.latency_ms,
        )
        return result

    # ── Sync interface — drop-in for LLMService / LLMRouter ──────────────────

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        """
        Sync chat: OpenAI primary → Groq fallback.

        Signature matches LLMService.chat() exactly.
        """
        if self._primary is not None:
            try:
                result = self._primary.generate_sync(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                logger.info(
                    "[ProviderFactory] provider=openai model=%s api=%s latency=%dms "
                    "tokens=%s/%s/%s",
                    result.model, result.api_type, result.latency_ms,
                    result.prompt_tokens, result.completion_tokens, result.total_tokens,
                )
                return result.content

            except Exception as exc:
                reason = _classify_error(exc)
                logger.warning(
                    "[ProviderFactory] OpenAI primary failed (%s) — switching to Groq fallback",
                    reason,
                )

        result = self._fallback.generate_sync(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        logger.info(
            "[ProviderFactory] provider=groq model=%s latency=%dms [FALLBACK]",
            result.model, result.latency_ms,
        )
        return result.content

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """
        Sync chat returning a parsed JSON dict.

        Signature matches LLMService.chat_json() and LLMRouter.chat_json()
        exactly — direct drop-in for the ReAct loop and all agent callers.
        """
        from backend.app.services.core.llm_service import LLMService

        content = self.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMService._safe_json_loads(content)


# ── Module-level singleton (optional) ─────────────────────────────────────────

_default_factory: Optional[ProviderFactory] = None


def get_provider_factory() -> ProviderFactory:
    """Return the shared ProviderFactory instance (lazy init, process-wide)."""
    global _default_factory
    if _default_factory is None:
        _default_factory = ProviderFactory()
    return _default_factory


# ── Error classification ──────────────────────────────────────────────────────

def _classify_error(exc: Exception) -> str:
    """Produce a loggable, key-free description of the error cause."""
    exc_type = type(exc).__name__
    text = str(exc).lower()

    if exc_type == "APITimeoutError" or "timeout" in text:
        return "timeout"
    if exc_type == "AuthenticationError" or "401" in text or "invalid_api_key" in text:
        return "auth_failure"
    if exc_type == "RateLimitError" or "429" in text or "rate_limit" in text:
        return "rate_limit"
    if exc_type == "APIConnectionError" or "connection" in text:
        return "provider_outage"
    if "empty" in text or "no content" in text:
        return "empty_response"
    if "responses api" in text or "openai sdk" in text:
        return "sdk_too_old"
    if exc_type == "BadRequestError" or "400" in text:
        if "max_tokens" in text or "max_completion_tokens" in text or "max_output_tokens" in text:
            return "token_param_mismatch"
        return "malformed_request"
    return f"{exc_type}:{text[:48]}"
