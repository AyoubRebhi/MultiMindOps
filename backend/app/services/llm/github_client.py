from __future__ import annotations

import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)


class GitHubLLMClient:
    """
    OpenAI-compatible client for GitHub Models (Azure-backed inference).

    Endpoint : https://models.inference.ai.azure.com
    Auth     : GITHUB_TOKEN (PAT or GitHub Actions GITHUB_TOKEN)
    Interface: mirrors openai.OpenAI — raises on any failure so the caller
               (LLMRouter) can decide whether to retry or fall back to Groq.
    """

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=os.getenv("GITHUB_TOKEN", ""),
            base_url=os.getenv("GITHUB_BASE_URL", "https://models.inference.ai.azure.com"),
        )
        self.model = os.getenv("GITHUB_MODEL", "meta/llama-3-70b-instruct")

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        """Send a chat request and return the raw content string.

        Raises on any failure — never silently returns empty content.
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content

        if not content or content.strip() == "":
            raise ValueError("GitHub Models returned empty content — generation failed")

        total_tokens = getattr(getattr(response, "usage", None), "total_tokens", "?")
        logger.info(
            "[LLM] provider=github model=%s tokens=%s",
            self.model,
            total_tokens,
        )
        print(f"[LLM] GitHub | model={self.model} | tokens={total_tokens}")

        return content
