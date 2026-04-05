import logging
import math
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 15 * 60
DEFAULT_INVALID_KEY_COOLDOWN_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class GroqKeyEntry:
    name: str
    value: str
    label: str


class NoGroqAPIKeysAvailableError(RuntimeError):
    """Raised when no configured Groq key is currently usable."""


class GroqKeyManager:
    """Track Groq API keys and rotate them when one becomes unavailable."""

    def __init__(self, key_entries: Iterable[dict[str, str]] | None = None) -> None:
        normalized_entries = self._normalize_entries(key_entries or [])
        self._entries = normalized_entries
        self._blocked_until: dict[str, datetime] = {}
        self._cursor = 0
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings_obj=settings) -> "GroqKeyManager":
        return cls(settings_obj.get_groq_key_entries())

    @property
    def configured_keys_count(self) -> int:
        return len(self._entries)

    def get_active_key(self) -> GroqKeyEntry:
        entry = self.get_next_available_key()
        if entry is None:
            raise NoGroqAPIKeysAvailableError(self.describe_unavailable_state())
        return entry

    def get_next_available_key(
        self,
        exclude_names: set[str] | None = None,
        now: datetime | None = None,
    ) -> GroqKeyEntry | None:
        with self._lock:
            if not self._entries:
                return None

            current_time = now or datetime.now(timezone.utc)
            excluded = exclude_names or set()
            total = len(self._entries)

            for offset in range(total):
                index = (self._cursor + offset) % total
                entry = self._entries[index]
                if entry.name in excluded:
                    continue
                if self._is_available(entry.name, current_time):
                    self._cursor = index
                    return entry
            return None

    def mark_key_rate_limited(
        self,
        key_name: str,
        retry_after_seconds: int | None = None,
        now: datetime | None = None,
    ) -> None:
        cooldown_seconds = retry_after_seconds or DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
        current_time = now or datetime.now(timezone.utc)
        unblock_time = current_time + timedelta(seconds=max(1, cooldown_seconds))

        with self._lock:
            self._blocked_until[key_name] = unblock_time
            self._advance_cursor_from(key_name)

        logger.warning(
            "%s rate-limited, switching to the next Groq key",
            self.get_key_label(key_name),
        )

    def mark_key_invalid(
        self,
        key_name: str,
        cooldown_seconds: int = DEFAULT_INVALID_KEY_COOLDOWN_SECONDS,
        now: datetime | None = None,
    ) -> None:
        current_time = now or datetime.now(timezone.utc)
        unblock_time = current_time + timedelta(seconds=max(1, cooldown_seconds))

        with self._lock:
            self._blocked_until[key_name] = unblock_time
            self._advance_cursor_from(key_name)

        logger.error(
            "%s rejected by Groq authentication, disabling it temporarily",
            self.get_key_label(key_name),
        )

    def get_key_label(self, key_name: str) -> str:
        for entry in self._entries:
            if entry.name == key_name:
                return entry.label
        return "Groq key"

    def describe_unavailable_state(self, now: datetime | None = None) -> str:
        current_time = now or datetime.now(timezone.utc)
        next_retry_seconds: list[int] = []

        with self._lock:
            for blocked_until in self._blocked_until.values():
                remaining = math.ceil((blocked_until - current_time).total_seconds())
                if remaining > 0:
                    next_retry_seconds.append(remaining)

        if not self._entries:
            return "No Groq API keys are configured."

        if next_retry_seconds:
            soonest = min(next_retry_seconds)
            return (
                "No Groq API keys are currently available. "
                f"The next key should become available in about {soonest} seconds."
            )

        return (
            "No Groq API keys are currently available. "
            "All configured keys are blocked or invalid."
        )

    def _advance_cursor_from(self, key_name: str) -> None:
        for index, entry in enumerate(self._entries):
            if entry.name == key_name:
                self._cursor = (index + 1) % max(1, len(self._entries))
                return

    def _is_available(self, key_name: str, current_time: datetime) -> bool:
        blocked_until = self._blocked_until.get(key_name)
        if blocked_until is None:
            return True
        if blocked_until <= current_time:
            self._blocked_until.pop(key_name, None)
            return True
        return False

    @staticmethod
    def _normalize_entries(key_entries: Iterable[dict[str, str]]) -> list[GroqKeyEntry]:
        entries: list[GroqKeyEntry] = []
        seen_values: set[str] = set()

        for index, item in enumerate(key_entries, start=1):
            name = str(item.get("name") or "").strip()
            value = str(item.get("value") or "").strip()
            if not name or not value or value in seen_values:
                continue
            entries.append(GroqKeyEntry(name=name, value=value, label=f"key {index}"))
            seen_values.add(value)
        return entries


def is_groq_rate_limit_error(error: Exception) -> bool:
    message = str(error).lower()
    status_code = _extract_status_code(error)
    return status_code == 429 or any(
        token in message
        for token in (
            "rate_limit_exceeded",
            "rate limit reached",
            "too many requests",
            "tokens per day",
            "tokens per minute",
            "quota",
            "try again in",
        )
    )


def is_groq_auth_error(error: Exception) -> bool:
    message = str(error).lower()
    status_code = _extract_status_code(error)
    return status_code in {401, 403} or any(
        token in message
        for token in (
            "invalid api key",
            "authentication",
            "unauthorized",
            "forbidden",
            "incorrect api key",
        )
    )


def extract_retry_after_seconds(error: Exception) -> int | None:
    retry_after = _extract_retry_after_header(error)
    if retry_after is not None:
        return retry_after

    message = str(error)
    patterns = (
        r"try again in\s+(?:(\d+)h)?(?:(\d+)m)?([0-9.]+)s",
        r"retry after\s+([0-9.]+)\s*seconds?",
        r"retry after\s+([0-9.]+)\s*s",
    )

    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if not match:
            continue

        groups = [group for group in match.groups() if group is not None]
        if len(groups) == 3:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2) or 0)
            seconds = float(match.group(3) or 0)
            return max(1, math.ceil(hours * 3600 + minutes * 60 + seconds))

        seconds = float(groups[-1])
        return max(1, math.ceil(seconds))

    return None


def _extract_status_code(error: Exception) -> int | None:
    for attribute_name in ("status_code", "http_status"):
        value = getattr(error, attribute_name, None)
        if isinstance(value, int):
            return value

    response = getattr(error, "response", None)
    if response is not None:
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code

    return None


def _extract_retry_after_header(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None

    value = headers.get("retry-after") or headers.get("Retry-After")
    if value is None:
        return None

    try:
        return max(1, math.ceil(float(value)))
    except (TypeError, ValueError):
        return None


_default_groq_key_manager: GroqKeyManager | None = None


def get_default_groq_key_manager() -> GroqKeyManager:
    global _default_groq_key_manager

    if _default_groq_key_manager is None:
        _default_groq_key_manager = GroqKeyManager.from_settings(settings)

    return _default_groq_key_manager
