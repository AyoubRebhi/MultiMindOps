"""Abstract base class that all LLM providers must implement."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from backend.app.services.llm.models import LLMResponse


class BaseLLMProvider(ABC):
    """
    Uniform interface for every LLM backend.

    Every provider exposes two execution paths:
      • async generate()       — for async callers (FastAPI routes, async pipelines)
      • sync  generate_sync()  — for synchronous callers (agents, ReAct loops)

    Both paths return a typed LLMResponse so the caller always knows which
    provider answered, how long it took, and how many tokens were consumed.

    Future providers (Anthropic, Gemini, Azure, Ollama, DeepSeek …) need only
    subclass BaseLLMProvider and implement these four members.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        """Async generation — primary entry point for async callers."""
        ...

    @abstractmethod
    def generate_sync(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4000,
        response_format: Optional[dict] = None,
    ) -> LLMResponse:
        """Sync generation — drop-in for code that cannot await."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider identifier (e.g. 'openai', 'groq')."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier used for this provider (e.g. 'gpt-5-mini')."""
        ...
