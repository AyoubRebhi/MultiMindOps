"""
OpenAI GPT provider — primary LLM backend for infrastructure agents.

API routing (per model family):
  GPT-5 family (gpt-5*)  → OpenAI Responses API   (/v1/responses)
                             token param: max_output_tokens
                             NEVER sends: max_tokens, max_completion_tokens,
                                          temperature, top_p, frequency_penalty,
                                          presence_penalty, logit_bias, best_of, n
  All other models        → Chat Completions API  (/v1/chat/completions)
                             token param: max_tokens (gpt-4) or max_completion_tokens (o-series)

Compatibility table:
  Model family   | API endpoint         | Token param          | Sampling params
  -------------- | -------------------- | -------------------- | ---------------
  gpt-5-*        | /v1/responses        | max_output_tokens    | NONE (stripped)
  o1 / o3 / o4   | /v1/chat/completions | max_completion_tokens| allowed
  gpt-4-* / 3.5  | /v1/chat/completions | max_tokens           | allowed

GPT-5 payload builders (build_gpt5_responses_payload + sanitize_gpt5_payload) are
intentionally separated from the Chat Completions builders — they share NO mutable
kwargs logic so drift is structurally impossible.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import openai

from backend.app.services.llm.base_provider import BaseLLMProvider
from backend.app.services.llm.models import LLMResponse

logger = logging.getLogger(__name__)


class TruncatedResponseError(RuntimeError):
    """
    Raised when the Responses API returns status='incomplete' (max_output_tokens hit).

    Callers should catch this and retry with a larger max_output_tokens budget.
    """

    def __init__(
        self,
        message: str,
        finish_reason: str = "max_output_tokens",
        tokens_used: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.finish_reason = finish_reason
        self.tokens_used = tokens_used


_RETRIABLE = (openai.APITimeoutError, openai.RateLimitError, openai.APIConnectionError)

# ALL parameters unsupported by GPT-5 reasoning models via the Responses API.
# Covers legacy token params, sampling/generation params, and function-calling params.
# This set is intentionally broad so future gpt-5* variants are automatically safe.
GPT5_UNSUPPORTED_PARAMS: frozenset[str] = frozenset({
    # Legacy token params (Responses API uses max_output_tokens instead)
    "max_tokens",
    "max_completion_tokens",
    # Sampling / generation params not used in this provider's GPT-5 path
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "logit_bias",
    "best_of",
    "n",
    # Function/tool calling via old interface
    "functions",
    "function_call",
})

# Private alias kept for any internal references
_GPT5_FORBIDDEN_PARAMS = GPT5_UNSUPPORTED_PARAMS


# ── Model-family helpers ──────────────────────────────────────────────────────

def is_gpt5_model(model: str) -> bool:
    """Return True for GPT-5 family models that require the Responses API."""
    return model.startswith("gpt-5")


def is_o_series_model(model: str) -> bool:
    """Return True for o1/o3/o4 reasoning models that use max_completion_tokens."""
    return model.startswith(("o1", "o3", "o4"))


def get_chat_token_param(model: str, max_tokens: int) -> dict:
    """
    Return the correct token-limit kwarg for Chat Completions.

    Never call this for GPT-5 models — they use the Responses API instead.
    """
    if is_o_series_model(model):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


# ── GPT-5 sanitizer ───────────────────────────────────────────────────────────

def sanitize_gpt5_payload(payload: dict) -> dict:
    """
    Strip ALL unsupported parameters from a GPT-5 Responses API payload.

    Acts as a defense-in-depth layer: even if a caller accidentally injects a
    sampling param, this removes it before the request is sent and logs exactly
    what was stripped so the injection source can be traced.

    Returns a new dict — never mutates the input.
    """
    removed = sorted(GPT5_UNSUPPORTED_PARAMS & payload.keys())
    sanitized = {k: v for k, v in payload.items() if k not in GPT5_UNSUPPORTED_PARAMS}
    if removed:
        logger.warning(
            "[OpenAIProvider] GPT5_SANITIZER removed=%s final=%s",
            removed,
            sorted(sanitized.keys()),
        )
    else:
        logger.debug(
            "[OpenAIProvider] GPT5_SANITIZER no removals — final=%s",
            sorted(sanitized.keys()),
        )
    return sanitized


# ── Payload builders ──────────────────────────────────────────────────────────

def build_gpt5_responses_payload(
    model: str,
    prompt: str,
    system_prompt: Optional[str],
    temperature: float,
    max_tokens: int,
    response_format: Optional[dict],
) -> dict:
    """
    Build a clean payload for the GPT-5 Responses API (/v1/responses).

    This builder is intentionally separate from the Chat Completions builder.
    It ONLY includes parameters supported by GPT-5 reasoning models and shares
    NO mutable kwargs logic with the legacy GPT-4 path.

    Supported:   model, input, instructions, max_output_tokens, text.format
    Never sent:  temperature, top_p, frequency_penalty, presence_penalty,
                 logit_bias, best_of, n, max_tokens, max_completion_tokens,
                 functions, function_call
    """
    payload: dict[str, Any] = {
        "model": model,
        "input": [{"role": "user", "content": prompt}],
        "max_output_tokens": max_tokens,
        "reasoning": {"effort": "low"},
        "temperature": temperature,
        "parallel_tool_calls": False,
        "store": False,
        "stream": False,
    }
    if system_prompt:
        payload["instructions"] = system_prompt
    text_options: dict[str, Any] = {"verbosity": "low"}
    if response_format:
        # Responses API uses text.format instead of response_format.
        text_options["format"] = response_format
    payload["text"] = text_options
    return payload


def build_responses_payload(
    model: str,
    prompt: str,
    system_prompt: Optional[str],
    temperature: float,  # accepted but intentionally dropped for GPT-5
    max_tokens: int,
    response_format: Optional[dict],
) -> dict:
    """
    Legacy wrapper — delegates to build_gpt5_responses_payload (temperature is dropped).

    Kept for any external callers that still pass temperature; it is silently
    ignored so existing call-sites do not need to be updated immediately.
    """
    return build_gpt5_responses_payload(
        model=model,
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
    )


def build_chat_payload(
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    response_format: Optional[dict],
) -> dict:
    """
    Build a payload for the Chat Completions API (/v1/chat/completions).

    Only for non-GPT-5 models.
    """
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        **get_chat_token_param(model, max_tokens),
    }
    if response_format:
        payload["response_format"] = response_format
    return payload


# ── Response parsers ──────────────────────────────────────────────────────────

def _parse_responses_result(response: Any, t0: float, model: str) -> LLMResponse:
    """Parse an OpenAI Responses API response object into LLMResponse."""
    latency_ms = int((time.monotonic() - t0) * 1000)
    status = getattr(response, "status", "completed")
    usage = getattr(response, "usage", None)

    # Detect truncation BEFORE extracting text — a truncated response must never
    # be silently passed to JSON parsers (it produces corrupted partial JSON).
    if status == "incomplete":
        incomplete_details = getattr(response, "incomplete_details", None)
        reason = (
            getattr(incomplete_details, "reason", "max_output_tokens")
            if incomplete_details
            else "max_output_tokens"
        )
        tokens_used = getattr(usage, "output_tokens", None)
        logger.warning(
            "[OpenAIProvider] Response INCOMPLETE: reason=%s output_tokens=%s model=%s — "
            "caller should retry with a higher max_output_tokens budget.",
            reason, tokens_used, model,
        )
        raise TruncatedResponseError(
            f"[OpenAIProvider] Response truncated "
            f"(status=incomplete reason={reason} output_tokens={tokens_used} model={model}). "
            "Retry with a higher max_output_tokens budget.",
            finish_reason=reason,
            tokens_used=tokens_used,
        )

    # output_text is the convenient shortcut; fall back to traversing output array
    text: str = getattr(response, "output_text", None) or ""
    if not text:
        for item in getattr(response, "output", []):
            for chunk in getattr(item, "content", []):
                candidate = getattr(chunk, "text", None)
                if candidate:
                    text = candidate
                    break
            if text:
                break

    text = text.strip()
    if not text:
        raise ValueError(
            f"[OpenAIProvider] Responses API returned empty content (model={model})"
        )

    return LLMResponse(
        content=text,
        provider="openai",
        model=model,
        latency_ms=latency_ms,
        prompt_tokens=getattr(usage, "input_tokens", None),
        completion_tokens=getattr(usage, "output_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        finish_reason=status,
        api_type="responses",
    )


def _parse_chat_result(response: Any, t0: float, model: str) -> LLMResponse:
    """Parse a Chat Completions API response object into LLMResponse."""
    latency_ms = int((time.monotonic() - t0) * 1000)
    content = (response.choices[0].message.content or "").strip()
    if not content:
        raise ValueError(
            f"[OpenAIProvider] Chat Completions returned empty content (model={model})"
        )
    usage = getattr(response, "usage", None)
    return LLMResponse(
        content=content,
        provider="openai",
        model=model,
        latency_ms=latency_ms,
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        finish_reason=response.choices[0].finish_reason,
        api_type="chat_completions",
    )


# ── Provider class ────────────────────────────────────────────────────────────

class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI GPT provider with:
      • Automatic API routing: Responses API for GPT-5, Chat Completions for others
      • Async and sync execution paths
      • Configurable retries with exponential backoff
      • Full token usage extraction
      • Latency tracking
      • Secrets-safe logging (API key never appears in logs)
      • Hard assertion: max_tokens is NEVER sent to GPT-5 models
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4-mini",
        timeout: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self._model = model
        self._max_retries = max_retries
        self._timeout = timeout
        self._sync_client = openai.OpenAI(api_key=api_key, timeout=timeout)
        self._async_client = openai.AsyncOpenAI(api_key=api_key, timeout=timeout)

        api_type = "responses" if is_gpt5_model(model) else "chat_completions"
        logger.info(
            "[OpenAIProvider] Initialized — model=%s api_type=%s timeout=%.0fs max_retries=%d",
            model, api_type, timeout, max_retries,
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    # ── Async path ────────────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        if is_gpt5_model(self._model):
            return await self._responses_async(
                prompt, system_prompt, temperature, max_tokens, response_format
            )
        return await self._chat_async(
            prompt, system_prompt, temperature, max_tokens, response_format
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
        if is_gpt5_model(self._model):
            return self._responses_sync(
                prompt, system_prompt, temperature, max_tokens, response_format
            )
        return self._chat_sync(
            prompt, system_prompt, temperature, max_tokens, response_format
        )

    # ── Responses API — async ─────────────────────────────────────────────────

    async def _responses_async(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[dict],
    ) -> LLMResponse:
        raw = build_gpt5_responses_payload(
            self._model, prompt, system_prompt, temperature, max_tokens, response_format
        )
        payload = sanitize_gpt5_payload(raw)
        self._assert_gpt5_payload_safe(payload)
        self._log_payload("async", "responses", payload)

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            t0 = time.monotonic()
            try:
                response = await self._async_client.responses.create(**payload)
                result = _parse_responses_result(response, t0, self._model)
                logger.info(
                    "[OpenAIProvider] responses/async model=%s latency=%dms "
                    "tokens=%s/%s/%s status=%s",
                    self._model, result.latency_ms,
                    result.prompt_tokens, result.completion_tokens,
                    result.total_tokens, result.finish_reason,
                )
                return result

            except _RETRIABLE as exc:
                last_error = exc
                if attempt < self._max_retries:
                    delay = 2.0 ** attempt
                    logger.warning(
                        "[OpenAIProvider] Transient error (attempt %d/%d): %s — retry in %.1fs",
                        attempt + 1, self._max_retries + 1, type(exc).__name__, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

            except openai.AuthenticationError:
                logger.error(
                    "[OpenAIProvider] Authentication failed — OPENAI_KEY is invalid or missing"
                )
                raise

            except openai.BadRequestError as exc:
                logger.error(
                    "[OpenAIProvider] BadRequest model=%s api=responses: %s",
                    self._model, str(exc)[:200],
                )
                raise

            except AttributeError as exc:
                # SDK version does not expose .responses — fall back gracefully
                logger.error(
                    "[OpenAIProvider] Responses API unavailable in installed openai SDK "
                    "(upgrade: pip install 'openai>=1.66.0'): %s", exc
                )
                raise RuntimeError(
                    "OpenAI SDK does not support Responses API. "
                    "Run: pip install 'openai>=1.66.0'"
                ) from exc

            except Exception:
                raise

        raise last_error  # type: ignore[misc]

    # ── Responses API — sync ──────────────────────────────────────────────────

    def _responses_sync(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[dict],
    ) -> LLMResponse:
        raw = build_gpt5_responses_payload(
            self._model, prompt, system_prompt, temperature, max_tokens, response_format
        )
        payload = sanitize_gpt5_payload(raw)
        self._assert_gpt5_payload_safe(payload)
        self._log_payload("sync", "responses", payload)

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            t0 = time.monotonic()
            try:
                response = self._sync_client.responses.create(**payload)
                result = _parse_responses_result(response, t0, self._model)
                logger.info(
                    "[OpenAIProvider] responses/sync model=%s latency=%dms "
                    "tokens=%s/%s/%s status=%s",
                    self._model, result.latency_ms,
                    result.prompt_tokens, result.completion_tokens,
                    result.total_tokens, result.finish_reason,
                )
                return result

            except _RETRIABLE as exc:
                last_error = exc
                if attempt < self._max_retries:
                    delay = 2.0 ** attempt
                    logger.warning(
                        "[OpenAIProvider] Transient error (attempt %d/%d): %s — retry in %.1fs",
                        attempt + 1, self._max_retries + 1, type(exc).__name__, delay,
                    )
                    time.sleep(delay)
                    continue
                raise

            except openai.AuthenticationError:
                logger.error(
                    "[OpenAIProvider] Authentication failed — OPENAI_KEY is invalid or missing"
                )
                raise

            except openai.BadRequestError as exc:
                logger.error(
                    "[OpenAIProvider] BadRequest model=%s api=responses: %s",
                    self._model, str(exc)[:200],
                )
                raise

            except AttributeError as exc:
                logger.error(
                    "[OpenAIProvider] Responses API unavailable in installed openai SDK "
                    "(upgrade: pip install 'openai>=1.66.0'): %s", exc
                )
                raise RuntimeError(
                    "OpenAI SDK does not support Responses API. "
                    "Run: pip install 'openai>=1.66.0'"
                ) from exc

            except Exception:
                raise

        raise last_error  # type: ignore[misc]

    # ── Chat Completions — async ──────────────────────────────────────────────

    async def _chat_async(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[dict],
    ) -> LLMResponse:
        messages = _build_messages(prompt, system_prompt)
        payload = build_chat_payload(
            self._model, messages, temperature, max_tokens, response_format
        )
        self._log_payload("async", "chat_completions", payload)

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            t0 = time.monotonic()
            try:
                response = await self._async_client.chat.completions.create(**payload)
                result = _parse_chat_result(response, t0, self._model)
                logger.info(
                    "[OpenAIProvider] chat/async model=%s latency=%dms "
                    "tokens=%s/%s/%s finish=%s",
                    self._model, result.latency_ms,
                    result.prompt_tokens, result.completion_tokens,
                    result.total_tokens, result.finish_reason,
                )
                return result

            except _RETRIABLE as exc:
                last_error = exc
                if attempt < self._max_retries:
                    delay = 2.0 ** attempt
                    logger.warning(
                        "[OpenAIProvider] Transient error (attempt %d/%d): %s — retry in %.1fs",
                        attempt + 1, self._max_retries + 1, type(exc).__name__, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

            except openai.AuthenticationError:
                logger.error(
                    "[OpenAIProvider] Authentication failed — OPENAI_KEY is invalid or missing"
                )
                raise

            except openai.BadRequestError as exc:
                logger.error(
                    "[OpenAIProvider] BadRequest model=%s api=chat_completions: %s",
                    self._model, str(exc)[:200],
                )
                raise

            except Exception:
                raise

        raise last_error  # type: ignore[misc]

    # ── Chat Completions — sync ───────────────────────────────────────────────

    def _chat_sync(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int,
        response_format: Optional[dict],
    ) -> LLMResponse:
        messages = _build_messages(prompt, system_prompt)
        payload = build_chat_payload(
            self._model, messages, temperature, max_tokens, response_format
        )
        self._log_payload("sync", "chat_completions", payload)

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            t0 = time.monotonic()
            try:
                response = self._sync_client.chat.completions.create(**payload)
                result = _parse_chat_result(response, t0, self._model)
                logger.info(
                    "[OpenAIProvider] chat/sync model=%s latency=%dms "
                    "tokens=%s/%s/%s finish=%s",
                    self._model, result.latency_ms,
                    result.prompt_tokens, result.completion_tokens,
                    result.total_tokens, result.finish_reason,
                )
                return result

            except _RETRIABLE as exc:
                last_error = exc
                if attempt < self._max_retries:
                    delay = 2.0 ** attempt
                    logger.warning(
                        "[OpenAIProvider] Transient error (attempt %d/%d): %s — retry in %.1fs",
                        attempt + 1, self._max_retries + 1, type(exc).__name__, delay,
                    )
                    time.sleep(delay)
                    continue
                raise

            except openai.AuthenticationError:
                logger.error(
                    "[OpenAIProvider] Authentication failed — OPENAI_KEY is invalid or missing"
                )
                raise

            except openai.BadRequestError as exc:
                logger.error(
                    "[OpenAIProvider] BadRequest model=%s api=chat_completions: %s",
                    self._model, str(exc)[:200],
                )
                raise

            except Exception:
                raise

        raise last_error  # type: ignore[misc]

    # ── Guards & observability ────────────────────────────────────────────────

    def _assert_gpt5_payload_safe(self, payload: dict) -> None:
        """
        Fail fast if ANY unsupported parameter appears in a GPT-5 request payload.

        Covers all sampling params (temperature, top_p, …), legacy token params, and
        function-calling params.  sanitize_gpt5_payload() should have already removed
        them — this assertion is the final gate before the wire.
        """
        violations = GPT5_UNSUPPORTED_PARAMS & payload.keys()
        if violations:
            raise AssertionError(
                f"[OpenAIProvider] UNSUPPORTED parameters leaked into GPT-5 payload "
                f"(model={self._model}): {sorted(violations)}. "
                "GPT-5 Responses API only accepts: model, input, instructions, "
                "max_output_tokens, text.format."
            )

    def _log_payload(self, path: str, api_type: str, payload: dict) -> None:
        """Log the sanitized payload (no secrets) before every OpenAI request."""
        safe = {
            k: v for k, v in payload.items()
            if k not in {"input", "instructions"}  # omit content from logs
        }
        safe["input_preview"] = str(payload.get("input", ""))[:80]
        logger.warning(
            "[OpenAIProvider] PRE-REQUEST %s/%s model=%s api_type=%s "
            "PAYLOAD_KEYS=%s SAFE_PAYLOAD=%s",
            path, api_type, payload.get("model"), api_type,
            sorted(payload.keys()), safe,
        )
        # Hard assertion: no unsupported params must survive into any GPT-5 request
        if is_gpt5_model(payload.get("model", "")):
            leaked = GPT5_UNSUPPORTED_PARAMS & payload.keys()
            assert not leaked, (
                f"[OpenAIProvider] BUG: unsupported params leaked into GPT-5 payload "
                f"(model={payload['model']}): {sorted(leaked)}"
            )


# ── Module helpers (private) ──────────────────────────────────────────────────

def _build_messages(prompt: str, system_prompt: Optional[str]) -> list[dict]:
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages
