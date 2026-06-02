"""
Generic OpenAI-compatible LLM client.

All GLM/Ollama-specific logic has been removed.  Supports any provider that
exposes an OpenAI-compatible /chat/completions endpoint (NVIDIA NIM,
Together.ai, Groq, OpenAI, etc.).

Configure via environment / .env:
    LLM_API_KEY   — provider API key (falls back to GROQ_API_KEY)
    LLM_BASE_URL  — base URL  (default: https://api.groq.com/openai/v1)
    LLM_MODEL     — model name (default: llama3-70b-8192)

Backward-compatible alias: ``GLMService = LLMClient``
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict

import httpx
import yaml

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2          # total extra retries after the first attempt
_RETRY_BASE_DELAY = 1.0   # exponential backoff base (seconds)
_REQUEST_TIMEOUT = 60.0   # per-request timeout (seconds)


class LLMClient:
    """
    Lightweight, retry-aware wrapper around any OpenAI-compatible LLM endpoint.

    Uses ``httpx`` with ``json=`` so payloads are always UTF-8 encoded without
    locale-codec surprises.  Retries transient errors with exponential back-off.
    """

    # Groq is the sole authorised LLM provider for all pipeline stages.
    _GROQ_BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self) -> None:
        groq_key = settings.GROQ_API_KEY.strip()
        if not groq_key:
            raise Exception(
                "Missing GROQ API key — set GROQ_API_KEY in your environment or .env file."
            )
        self.api_key: str = groq_key
        self.base_url: str = self._GROQ_BASE_URL
        self.model: str = settings.GROQ_MODEL

        logger.info(
            "[LLMClient] Initialized — provider=GROQ model=%s endpoint=%s",
            self.model,
            self.base_url,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        """Send a chat request and return the raw string response."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                logger.debug(
                    "[LLMClient] POST %s/chat/completions attempt=%d/%d model=%s",
                    self.base_url,
                    attempt + 1,
                    _MAX_RETRIES + 1,
                    self.model,
                )
                with httpx.Client(timeout=_REQUEST_TIMEOUT) as http:
                    resp = http.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,  # httpx serialises with UTF-8 automatically
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                    )

                resp.raise_for_status()
                data: dict = json.loads(resp.content.decode("utf-8"))
                content: str = data["choices"][0]["message"]["content"] or ""

                logger.debug(
                    "[LLMClient] Response received (%d chars): %.200s",
                    len(content),
                    content,
                )
                return content

            except Exception as exc:
                last_error = exc
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "[LLMClient] Attempt %d/%d failed (%s) — retrying in %.1fs",
                        attempt + 1,
                        _MAX_RETRIES + 1,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "[LLMClient] All %d attempts failed — last error: %s",
                        _MAX_RETRIES + 1,
                        exc,
                    )

        raise RuntimeError(
            f"LLM request failed after {_MAX_RETRIES + 1} attempts"
        ) from last_error

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        """Send a chat request and parse the response as JSON."""
        raw = self.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        logger.debug("[LLMClient] Raw response for JSON parsing: %.500s", raw)
        return _safe_json_loads(raw)


# ---------------------------------------------------------------------------
# Backward-compatible alias (judges import GLMService)
# ---------------------------------------------------------------------------

GLMService = LLMClient


# ---------------------------------------------------------------------------
# JSON parsing helpers (module-level so they can be unit-tested directly)
# ---------------------------------------------------------------------------

def _safe_json_loads(content: str) -> Dict[str, Any]:
    """Parse LLM output as JSON, stripping markdown fences and repairing control chars."""
    content = content.strip()

    # Strip ```json … ``` or ``` … ``` fences
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) >= 3:
            content = "\n".join(lines[1:-1]).strip()

    candidates = [content]
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        candidates.append(match.group(0))

    # Recovery: if the JSON looks truncated (starts with { but doesn't close),
    # try appending common closing suffixes to recover partial artifact output.
    trimmed = content.rstrip()
    if trimmed.startswith("{") and not trimmed.endswith("}"):
        for tail in ('"}}}', '"}}', '"}'  , '}}}', '}}', '}'):
            candidates.append(trimmed + tail)

    seen: set[str] = set()
    last_error: Exception | None = None

    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)

        for payload in (candidate, _escape_control_chars(candidate)):
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError as exc:
                last_error = exc

            try:
                parsed_yaml = yaml.safe_load(payload)
                if isinstance(parsed_yaml, dict):
                    return parsed_yaml
            except yaml.YAMLError as exc:
                last_error = exc

    raise ValueError(
        f"LLM did not return valid JSON. Raw output:\n{content}"
    ) from last_error


def _escape_control_chars(payload: str) -> str:
    """Escape bare newlines/tabs inside JSON string literals."""
    result: list[str] = []
    in_string = False
    escaped = False

    for char in payload:
        if in_string:
            if escaped:
                result.append(char)
                escaped = False
                continue
            if char == "\\":
                result.append(char)
                escaped = True
                continue
            if char == '"':
                result.append(char)
                in_string = False
                continue
            if char == "\n":
                result.append("\\n")
                continue
            if char == "\r":
                result.append("\\r")
                continue
            if char == "\t":
                result.append("\\t")
                continue
            result.append(char)
            continue

        result.append(char)
        if char == '"':
            in_string = True

    return "".join(result)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_default_instance: LLMClient | None = None


def get_glm_service() -> LLMClient:
    global _default_instance
    if _default_instance is None:
        _default_instance = LLMClient()
    return _default_instance
