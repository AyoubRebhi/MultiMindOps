from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from typing import Any, Dict, List

import httpx
import yaml

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


class LightningClient:
    """OpenAI-compatible client for Lightning chat completions."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = (api_key or settings.LIGHTNING_API_KEY).strip()
        self.base_url = (base_url or settings.LIGHTNING_BASE_URL).rstrip("/")
        self.model = model or settings.LIGHTNING_MODEL
        self.timeout_seconds = timeout_seconds

        if not self.api_key:
            raise ValueError("LIGHTNING_API_KEY is not configured.")

    async def achat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 3200,
        model: str | None = None,
    ) -> Dict[str, Any]:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        timeout = httpx.Timeout(self.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 3200,
        model: str | None = None,
    ) -> Dict[str, Any]:
        return _run_async(
            self.achat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
            )
        )

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 3200,
    ) -> Dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self.chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @staticmethod
    def extract_content(payload: Dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return str(message.get("content") or "")

    @staticmethod
    def extract_usage(payload: Dict[str, Any]) -> Dict[str, int]:
        usage = payload.get("usage") or {}
        return {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 3200,
    ) -> Dict[str, Any]:
        t0 = time.monotonic()
        payload = self.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        usage = self.extract_usage(payload)
        logger.info(
            "[LLM] provider=lightning model=%s latency=%dms tokens=%d",
            self.model,
            latency_ms,
            usage["total_tokens"],
        )
        return self._safe_json_loads(self.extract_content(payload))

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
            repaired = LightningClient._escape_control_chars_in_strings(candidate)
            for payload in (candidate, repaired):
                if not payload:
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

        raise ValueError(f"Lightning did not return valid JSON. Raw output:\n{content}") from last_error

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


def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    container: dict[str, Any] = {}

    def _runner() -> None:
        try:
            container["result"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - re-raised in caller thread
            container["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in container:
        raise container["error"]
    return container.get("result")
