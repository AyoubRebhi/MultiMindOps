import json
import logging
import re
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

            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content or ""
            except Exception as error:
                last_error = error
                if is_groq_rate_limit_error(error):
                    retry_after_seconds = extract_retry_after_seconds(error)
                    self.key_manager.mark_key_rate_limited(
                        key_entry.name,
                        retry_after_seconds=retry_after_seconds,
                    )
                    continue

                if is_groq_auth_error(error):
                    self.key_manager.mark_key_invalid(key_entry.name)
                    continue

                raise

        unavailable_message = self.key_manager.describe_unavailable_state()
        logger.error(unavailable_message)
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

    @staticmethod
    def _build_client(api_key: str) -> OpenAI:
        return OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
