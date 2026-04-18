import json
import logging
import re
import time
from typing import Any, Callable, Dict

from openai import OpenAI
import yaml

from backend.app.core.config import settings
from backend.app.services.core.groq_key_manager import (
    GroqKeyManager,
    NoGroqAPIKeysAvailableError,
    extract_retry_after_seconds,
    get_default_groq_key_manager,
    is_groq_auth_error,
    is_groq_rate_limit_error,
)

logger = logging.getLogger(__name__)

# Number of times to retry the same key on transient network errors
_NETWORK_RETRY_ATTEMPTS = 3
# Base delay (seconds) for exponential backoff: 1s, 2s, 4s
_NETWORK_RETRY_BASE_DELAY = 1.0
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Minimum wait before rotating to the next key after a rate-limit hit.
# Groq free-tier resets TPM counters every 60 s; 12 s gives the current key
# time to partially drain before we try the next one.
_RATE_LIMIT_MIN_WAIT_SECONDS = 12

# Throttle: minimum gap (seconds) between two consecutive requests on the
# same key. Keeps per-key TPM well below the free-tier ceiling.
_PER_KEY_THROTTLE_SECONDS = 2.0


def _ascii_safe(text: str) -> str:
    """Replace common non-ASCII Unicode characters with ASCII equivalents.

    Mirrors GLMService._ascii_safe so that the Groq OpenAI SDK path is also
    protected against UnicodeEncodeError on Windows ASCII/cp1252 locales.
    """
    _REPLACEMENTS = {
        "\u2014": "--",   # em-dash
        "\u2013": "-",    # en-dash
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2026": "...",  # horizontal ellipsis
        "\u00d7": "x",    # multiplication sign
        "\u2022": "*",    # bullet
        "\u00b7": "-",    # middle dot
        "\u00a0": " ",    # non-breaking space
    }
    for uni, asc in _REPLACEMENTS.items():
        text = text.replace(uni, asc)
    return text.encode("ascii", "replace").decode("ascii")


def is_network_error(error: Exception) -> bool:
    """Return True for transient connection-level errors worth retrying."""
    message = str(error).lower()
    return any(
        token in message
        for token in (
            "upstream connect error",
            "disconnect/reset before headers",
            "connection reset",
            "connection refused",
            "connection aborted",
            "remote end closed connection",
            "broken pipe",
            "eof occurred",
            "timed out",
            "timeout",
            "network",
            "ssl",
            "handshake",
        )
    )


class LLMService:
    def __init__(
        self,
        key_manager: GroqKeyManager | None = None,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.key_manager = key_manager or get_default_groq_key_manager()
        if self.key_manager.configured_keys_count == 0:
            raise ValueError(
                "No Groq API key is configured. Set GROQ_API_KEY or GROQ_API_KEY_<N> "
                "in your environment or .env file."
            )

        self.model = settings.GROQ_MODEL
        self._client_factory = client_factory or self._build_client
        # Track the timestamp of the last successful request per key name
        self._last_request_time: dict[str, float] = {}

        logger.info(
            "[LLMService] Initialized — model=%s host=%s keys=%d throttle=%.1fs",
            self.model,
            _GROQ_BASE_URL,
            self.key_manager.configured_keys_count,
            _PER_KEY_THROTTLE_SECONDS,
        )

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        last_error: Exception | None = None
        attempted_names: set[str] = set()
        max_attempts = max(1, self.key_manager.configured_keys_count)

        for _ in range(max_attempts):
            key_entry = self.key_manager.get_next_available_key(exclude_names=attempted_names)
            if key_entry is None:
                break

            attempted_names.add(key_entry.name)
            client = self._client_factory(key_entry.value)

            # Per-key throttle: enforce minimum gap between consecutive requests
            self._apply_throttle(key_entry.name)

            # Sanitise prompts once per key rotation (not per retry).
            safe_system = _ascii_safe(system_prompt)
            safe_user = _ascii_safe(user_prompt)

            # Per-key: retry transient network errors with exponential backoff
            for attempt in range(_NETWORK_RETRY_ATTEMPTS):
                try:
                    response = client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": safe_system},
                            {"role": "user", "content": safe_user},
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    self._last_request_time[key_entry.name] = time.monotonic()
                    return response.choices[0].message.content or ""

                except Exception as error:
                    last_error = error

                    if is_groq_rate_limit_error(error):
                        retry_after_seconds = extract_retry_after_seconds(error)
                        # Wait at least _RATE_LIMIT_MIN_WAIT_SECONDS so the TPM
                        # window has time to partially reset before the next key
                        # is tried. Avoids exhausting all keys in one burst.
                        effective_wait = max(
                            _RATE_LIMIT_MIN_WAIT_SECONDS,
                            retry_after_seconds or 0,
                        )
                        logger.warning(
                            "[LLMService] Rate-limited on key=%s — "
                            "waiting %ds before rotating to next key",
                            key_entry.name,
                            effective_wait,
                        )
                        time.sleep(effective_wait)
                        self.key_manager.mark_key_rate_limited(
                            key_entry.name,
                            retry_after_seconds=retry_after_seconds,
                        )
                        break  # Try next key

                    if is_groq_auth_error(error):
                        self.key_manager.mark_key_invalid(key_entry.name)
                        break  # Try next key

                    if is_network_error(error):
                        delay = _NETWORK_RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            "[LLMService] Network error on attempt %d/%d "
                            "(host=%s model=%s key=%s): %s — retrying in %.1fs",
                            attempt + 1,
                            _NETWORK_RETRY_ATTEMPTS,
                            _GROQ_BASE_URL,
                            self.model,
                            key_entry.name,
                            error,
                            delay,
                        )
                        if attempt < _NETWORK_RETRY_ATTEMPTS - 1:
                            time.sleep(delay)
                            continue
                        # All network retries exhausted for this key — try next key
                        logger.error(
                            "[LLMService] All %d network retries exhausted for key=%s",
                            _NETWORK_RETRY_ATTEMPTS,
                            key_entry.name,
                        )
                        break

                    # Non-retryable error — surface immediately with context
                    logger.error(
                        "[LLMService] Non-retryable error (host=%s model=%s key=%s): %s",
                        _GROQ_BASE_URL,
                        self.model,
                        key_entry.name,
                        error,
                        exc_info=True,
                    )
                    raise

        unavailable_message = self.key_manager.describe_unavailable_state()
        logger.error(
            "[LLMService] All keys exhausted — host=%s model=%s last_error=%s",
            _GROQ_BASE_URL,
            self.model,
            last_error,
        )
        raise NoGroqAPIKeysAvailableError(unavailable_message) from last_error

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> Dict[str, Any]:
        content = self.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._safe_json_loads(content)

    @staticmethod
    def _safe_json_loads(content: str) -> Dict[str, Any]:
        content = content.strip()

        if content.startswith("```"):
            lines = content.splitlines()
            if len(lines) >= 3:
                content = "\n".join(lines[1:-1]).strip()

        candidates = [content]
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            candidates.append(match.group(0))

        seen: set[str] = set()
        last_error: Exception | None = None
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)

            repaired = LLMService._escape_control_chars_in_strings(candidate)
            for payload in (candidate, repaired):
                if not payload or payload in seen and payload != candidate:
                    continue
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

        raise ValueError(f"LLM did not return valid JSON. Raw output:\n{content}") from last_error

    @staticmethod
    def _escape_control_chars_in_strings(payload: str) -> str:
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

    def _apply_throttle(self, key_name: str) -> None:
        """Sleep if necessary so consecutive requests on the same key are
        at least _PER_KEY_THROTTLE_SECONDS apart."""
        last = self._last_request_time.get(key_name)
        if last is None:
            return
        elapsed = time.monotonic() - last
        gap = _PER_KEY_THROTTLE_SECONDS - elapsed
        if gap > 0:
            logger.debug(
                "[LLMService] Throttling key=%s for %.2fs", key_name, gap
            )
            time.sleep(gap)

    @staticmethod
    def _build_client(api_key: str) -> OpenAI:
        return OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )


_default_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _default_llm_service
    if _default_llm_service is None:
        _default_llm_service = LLMService()
    return _default_llm_service
