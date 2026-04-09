"""
GLM cloud LLM service — via Ollama's cloud model proxy.

glm-5.1:cloud is an Ollama cloud model: Ollama routes it to the cloud
without downloading the model locally. No API key needed in code.
Authentication is handled once via: ollama login

Default endpoint: local Ollama daemon (http://localhost:11434/v1)
Default model:    glm-5.1:cloud

Override via .env:
    GLM_BASE_URL=http://localhost:11434/v1
    GLM_MODEL=glm-5.1:cloud
    GLM_API_KEY=         # leave empty — Ollama ignores it
"""
import json
import logging
import re
from typing import Any, Dict

from openai import OpenAI
import yaml

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class GLMService:
    """
    LLM service for GLM-5.1:cloud via Ollama.

    Ollama exposes an OpenAI-compatible API at /v1.
    The API key is a required field for the OpenAI SDK but Ollama ignores it.
    """

    def __init__(self) -> None:
        self.model = settings.GLM_MODEL
        self.base_url = settings.GLM_BASE_URL.rstrip("/")
        # Ollama ignores the key — any non-empty string works
        self.api_key = settings.GLM_API_KEY or "ollama"
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

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
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.error("GLM chat error: %s", exc)
            raise

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

    # ------------------------------------------------------------------
    # JSON parsing helpers
    # ------------------------------------------------------------------

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

        last_error: Exception | None = None
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)

            for payload in (candidate, GLMService._escape_control_chars(candidate)):
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
            f"GLM did not return valid JSON. Raw output:\n{content}"
        ) from last_error

    @staticmethod
    def _escape_control_chars(payload: str) -> str:
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


_default_glm_service: GLMService | None = None


def get_glm_service() -> GLMService:
    global _default_glm_service
    if _default_glm_service is None:
        _default_glm_service = GLMService()
    return _default_glm_service
