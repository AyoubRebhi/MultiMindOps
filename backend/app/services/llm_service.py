import json
import logging
import re
from typing import Any, Callable, Dict

from openai import OpenAI

from backend.app.core.config import settings
from backend.app.services.groq_key_manager import (
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

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise ValueError(f"LLM did not return valid JSON. Raw output:\n{content}")

    @staticmethod
    def _build_client(api_key: str) -> OpenAI:
        return OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
