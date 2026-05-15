"""Shared response model for all LLM providers."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class LLMResponse(BaseModel):
    """Normalized response returned by every LLM provider."""

    content: str
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    # "responses" (OpenAI Responses API) or "chat_completions" or "groq"
    api_type: Optional[str] = None
    # True when the primary provider failed and Groq fallback was used
    fallback_used: bool = False
