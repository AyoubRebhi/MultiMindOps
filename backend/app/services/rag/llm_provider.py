"""
Multi-provider LLM abstraction: Lightning AI (primary) → Groq (fallback).

Design principles
-----------------
- No silent failures: every provider switch is logged with the reason.
- Strict failover: Lightning → Groq on any non-retriable error.
- Token tracking: input + output tokens logged per request.
- Cost estimation: per-request and cumulative monthly USD estimate.
- Task-aware model selection: different models for chunking vs evaluation.

Usage
-----
    from backend.app.services.rag.llm_provider import build_provider, ProviderResult

    provider = build_provider(task="chunking")
    result   = provider.generate(system="...", user="...")
    print(result.provider, result.model, result.cost_usd)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Cost table (USD per 1 000 000 tokens, input+output blended) ──────────────
# Approximate values — update when providers change pricing.
_COST_PER_1M: dict[str, float] = {
    # Lightning AI
    "meta-llama/Meta-Llama-3.1-8B-Instruct":  0.05,
    "meta-llama/Meta-Llama-3.1-70B-Instruct": 0.90,
    # Groq (free-tier friendly)
    "llama3-8b-8192":            0.05,
    "llama-3.3-70b-versatile":   0.59,
    "llama3-70b-8192":           0.59,
    "mixtral-8x7b-32768":        0.27,
}

_DEFAULT_COST = 0.10   # fallback if model not in table

# ── Monthly usage tracker (persisted in-memory + optional JSON file) ─────────

_usage_lock = threading.Lock()
_usage_state: dict[str, Any] = {
    "total_input_tokens":  0,
    "total_output_tokens": 0,
    "total_requests":      0,
    "total_cost_usd":      0.0,
    "by_provider": {
        "lightning": {"requests": 0, "tokens": 0, "cost_usd": 0.0},
        "groq":      {"requests": 0, "tokens": 0, "cost_usd": 0.0},
    },
}


def _record_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Thread-safe usage accounting. Returns the cost for this request."""
    total = input_tokens + output_tokens
    rate  = _COST_PER_1M.get(model, _DEFAULT_COST)
    cost  = total * rate / 1_000_000

    with _usage_lock:
        _usage_state["total_input_tokens"]  += input_tokens
        _usage_state["total_output_tokens"] += output_tokens
        _usage_state["total_requests"]      += 1
        _usage_state["total_cost_usd"]      += cost

        bucket = _usage_state["by_provider"].setdefault(
            provider, {"requests": 0, "tokens": 0, "cost_usd": 0.0}
        )
        bucket["requests"] += 1
        bucket["tokens"]   += total
        bucket["cost_usd"] += cost

    return cost


def get_usage_summary() -> dict[str, Any]:
    """Return a snapshot of accumulated token/cost usage."""
    with _usage_lock:
        return json.loads(json.dumps(_usage_state))  # deep copy


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ProviderResult:
    content:       str
    provider:      str
    model:         str
    input_tokens:  int   = 0
    output_tokens: int   = 0
    cost_usd:      float = 0.0
    latency_ms:    int   = 0
    fallback_used: bool  = False


# ── Base provider ─────────────────────────────────────────────────────────────

class LLMProvider:
    """Abstract base — subclasses must implement generate() and test_connection()."""

    name: str = "base"

    def generate(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> ProviderResult:
        raise NotImplementedError

    def test_connection(self) -> dict[str, Any]:
        raise NotImplementedError

    @staticmethod
    def _mask_key(key: str) -> str:
        if len(key) > 10:
            return key[:6] + "…" + key[-4:]
        return "SET" if key else "NOT SET"


# ── Lightning AI provider ─────────────────────────────────────────────────────

class LightningProvider(LLMProvider):
    """OpenAI-compatible client for Lightning AI."""

    name = "lightning"

    _REQUEST_TIMEOUT = 60.0
    _MAX_RETRIES     = 3
    _RETRY_BACKOFF   = (5.0, 10.0, 20.0)  # seconds between attempts

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.lightning.ai/v1",
        model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct",
    ):
        self._api_key  = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model    = model
        self._available = bool(self._api_key)

        masked = self._mask_key(self._api_key)
        if self._available:
            logger.info(
                "[LLM] LightningProvider ready | model=%s | key=%s",
                model, masked,
            )
        else:
            logger.warning("[LLM] LightningProvider: LIGHTNING_API_KEY not set — provider disabled")

    @property
    def available(self) -> bool:
        return self._available

    def generate(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> ProviderResult:
        if not self._available:
            raise RuntimeError("LightningProvider: api_key not configured")

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": temperature,
            "max_tokens":  max_tokens,
            "stream":      False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            t0 = time.monotonic()
            try:
                with httpx.Client(timeout=self._REQUEST_TIMEOUT) as client:
                    resp = client.post(
                        f"{self._base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                latency_ms = round((time.monotonic() - t0) * 1000)

                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", 15 * attempt))
                    logger.warning(
                        "[LLM] Lightning rate-limited (429) — waiting %.0fs (attempt %d/%d)",
                        wait, attempt, self._MAX_RETRIES,
                    )
                    time.sleep(min(wait, 90.0))
                    continue

                if resp.status_code in (401, 403):
                    body = resp.text[:200]
                    raise PermissionError(
                        f"Lightning auth failed ({resp.status_code}): {body}"
                    )

                resp.raise_for_status()
                data   = resp.json()
                choice = data["choices"][0]["message"]["content"].strip()
                usage  = data.get("usage", {})
                in_tok  = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)

                cost = _record_usage("lightning", self._model, in_tok, out_tok)
                logger.debug(
                    "[LLM] Lightning OK | model=%s | in=%d out=%d | cost=$%.5f | %dms",
                    self._model, in_tok, out_tok, cost, latency_ms,
                )
                return ProviderResult(
                    content=choice,
                    provider="lightning",
                    model=self._model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                )

            except (PermissionError, httpx.HTTPStatusError) as exc:
                # Non-retriable
                raise
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "[LLM] Lightning timeout (attempt %d/%d)", attempt, self._MAX_RETRIES
                )
                if attempt < self._MAX_RETRIES:
                    time.sleep(self._RETRY_BACKOFF[attempt - 1])
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[LLM] Lightning error (attempt %d/%d): %s",
                    attempt, self._MAX_RETRIES, exc,
                )
                if attempt < self._MAX_RETRIES:
                    time.sleep(self._RETRY_BACKOFF[attempt - 1])

        raise RuntimeError(f"Lightning failed after {self._MAX_RETRIES} attempts: {last_exc}")

    def test_connection(self) -> dict[str, Any]:
        if not self._available:
            return {"ok": False, "provider": "lightning", "error": "LIGHTNING_API_KEY not set"}
        try:
            result = self.generate(
                system="You are a test assistant.",
                user="Reply with the single word: pong",
                temperature=0.0,
                max_tokens=5,
            )
            masked = self._mask_key(self._api_key)
            logger.info(
                "[LLM] Lightning connectivity OK | model=%s | key=%s | %dms | preview='%s'",
                result.model, masked, result.latency_ms, result.content[:40],
            )
            return {
                "ok":        True,
                "provider":  "lightning",
                "model":     result.model,
                "latency_ms": result.latency_ms,
                "preview":   result.content[:40],
            }
        except Exception as exc:
            logger.error("[LLM] Lightning connectivity FAILED: %s", exc)
            return {"ok": False, "provider": "lightning", "error": str(exc)}


# ── Groq provider ─────────────────────────────────────────────────────────────

class GroqProvider(LLMProvider):
    """OpenAI-compatible client for Groq (fallback + agent provider)."""

    name = "groq"

    _BASE_URL        = "https://api.groq.com/openai/v1"
    _REQUEST_TIMEOUT = 45.0
    _MAX_RETRIES     = 3
    _RETRY_BACKOFF   = (2.0, 5.0, 10.0)

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
    ):
        self._api_key   = api_key.strip()
        self._model     = model
        self._available = bool(self._api_key)

        masked = self._mask_key(self._api_key)
        if self._available:
            logger.info(
                "[LLM] GroqProvider ready | model=%s | key=%s",
                model, masked,
            )
        else:
            logger.warning("[LLM] GroqProvider: GROQ_API_KEY not set — provider disabled")

    @property
    def available(self) -> bool:
        return self._available

    def generate(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> ProviderResult:
        if not self._available:
            raise RuntimeError("GroqProvider: api_key not configured")

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "temperature": temperature,
            "max_tokens":  min(max_tokens, 8192),  # Groq hard cap
            "stream":      False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type":  "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(1, self._MAX_RETRIES + 1):
            t0 = time.monotonic()
            try:
                with httpx.Client(timeout=self._REQUEST_TIMEOUT) as client:
                    resp = client.post(
                        f"{self._BASE_URL}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                latency_ms = round((time.monotonic() - t0) * 1000)

                if resp.status_code == 429:
                    wait = float(resp.headers.get("Retry-After", 12 * attempt))
                    logger.warning(
                        "[LLM] Groq rate-limited (429) — waiting %.0fs (attempt %d/%d)",
                        wait, attempt, self._MAX_RETRIES,
                    )
                    time.sleep(min(wait, 60.0))
                    continue

                if resp.status_code in (401, 403):
                    body = resp.text[:200]
                    raise PermissionError(f"Groq auth failed ({resp.status_code}): {body}")

                resp.raise_for_status()
                data    = resp.json()
                choice  = data["choices"][0]["message"]["content"].strip()
                usage   = data.get("usage", {})
                in_tok  = usage.get("prompt_tokens", 0)
                out_tok = usage.get("completion_tokens", 0)

                cost = _record_usage("groq", self._model, in_tok, out_tok)
                logger.debug(
                    "[LLM] Groq OK | model=%s | in=%d out=%d | cost=$%.5f | %dms",
                    self._model, in_tok, out_tok, cost, latency_ms,
                )
                return ProviderResult(
                    content=choice,
                    provider="groq",
                    model=self._model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                )

            except (PermissionError, httpx.HTTPStatusError) as exc:
                raise
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "[LLM] Groq timeout (attempt %d/%d)", attempt, self._MAX_RETRIES
                )
                if attempt < self._MAX_RETRIES:
                    time.sleep(self._RETRY_BACKOFF[attempt - 1])
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "[LLM] Groq error (attempt %d/%d): %s",
                    attempt, self._MAX_RETRIES, exc,
                )
                if attempt < self._MAX_RETRIES:
                    time.sleep(self._RETRY_BACKOFF[attempt - 1])

        raise RuntimeError(f"Groq failed after {self._MAX_RETRIES} attempts: {last_exc}")

    def test_connection(self) -> dict[str, Any]:
        if not self._available:
            return {"ok": False, "provider": "groq", "error": "GROQ_API_KEY not set"}
        try:
            result = self.generate(
                system="You are a test assistant.",
                user="Reply with the single word: pong",
                temperature=0.0,
                max_tokens=5,
            )
            return {
                "ok":        True,
                "provider":  "groq",
                "model":     result.model,
                "latency_ms": result.latency_ms,
                "preview":   result.content[:40],
            }
        except Exception as exc:
            return {"ok": False, "provider": "groq", "error": str(exc)}


# ── Multi-provider: Lightning → Groq strict failover ─────────────────────────

class MultiProvider(LLMProvider):
    """
    Strict failover: Lightning AI → Groq.

    Rules
    -----
    - If Lightning fails for any reason, logs the exact error and switches to Groq.
    - No silent fallback: every switch is an explicit WARNING log entry.
    - If both providers fail, raises RuntimeError (never swallows errors).
    """

    name = "multi"

    def __init__(
        self,
        lightning: LightningProvider,
        groq:      GroqProvider,
    ):
        self._lightning = lightning
        self._groq      = groq

    def generate(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> ProviderResult:
        # ── Primary: Lightning ────────────────────────────────────────────────
        if self._lightning.available:
            try:
                result = self._lightning.generate(system, user, temperature, max_tokens)
                return result
            except Exception as exc:
                logger.warning(
                    "[LLM] Lightning failed (%s) → switching to Groq",
                    _classify_error(exc),
                )

        # ── Fallback: Groq ────────────────────────────────────────────────────
        if self._groq.available:
            try:
                result = self._groq.generate(system, user, temperature, max_tokens)
                result.fallback_used = True
                return result
            except Exception as exc:
                raise RuntimeError(f"Both Lightning and Groq failed. Last Groq error: {exc}") from exc

        raise RuntimeError(
            "No LLM provider available: "
            "set LIGHTNING_API_KEY or GROQ_API_KEY in .env"
        )

    def test_connection(self) -> dict[str, Any]:
        lightning_result = self._lightning.test_connection()
        groq_result      = self._groq.test_connection()
        return {
            "lightning": lightning_result,
            "groq":      groq_result,
            "primary":   "lightning" if lightning_result.get("ok") else "groq",
        }


# ── Factory ───────────────────────────────────────────────────────────────────

def build_provider(task: str = "chunking") -> MultiProvider:
    """
    Build a configured MultiProvider for the given task.

    task: "chunking" | "evaluation" | "agent"
    """
    # Import here to avoid circular imports at module load time
    from backend.app.core.rag_config import rag_config  # noqa: PLC0415

    provider_name, base_url, model = rag_config.model_for_task(task)

    lightning_key   = rag_config.lightning_api_key
    lightning_url   = rag_config.lightning_base_url
    lightning_model = (
        rag_config.lightning_eval_model
        if task == "evaluation"
        else rag_config.lightning_model
    )

    groq_key   = rag_config.groq_api_key
    groq_model = rag_config.groq_model

    logger.info(
        "[LLM] build_provider | task=%s | effective_provider=%s | model=%s",
        task, rag_config.effective_provider(), model,
    )

    lightning = LightningProvider(
        api_key=lightning_key,
        base_url=lightning_url,
        model=lightning_model,
    )
    groq = GroqProvider(
        api_key=groq_key,
        model=groq_model,
    )
    return MultiProvider(lightning=lightning, groq=groq)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _classify_error(exc: Exception) -> str:
    """Return a short human-readable reason for a provider failure."""
    msg = str(exc).lower()
    if "401" in msg or "invalid" in msg or "auth" in msg:
        return "401 invalid key"
    if "403" in msg or "forbidden" in msg:
        return "403 forbidden"
    if "429" in msg or "rate" in msg:
        return "429 rate-limited"
    if "timeout" in msg:
        return "timeout"
    if "connect" in msg:
        return "connection error"
    return str(exc)[:80]
