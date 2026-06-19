"""Phase 7 — Architecture-planning model routing contract.

The architecture-planning generation is produced by ``PlannerAgent`` (which
backs ``ArchitectureDecisionAgent``). Its generation strategy must be:

    PRIMARY  : OpenAI GPT-5-mini  (settings.OPENAI_MODEL)
    FALLBACK : Groq               (settings.GROQ_MODEL)

tried in that order via ``ProviderFactory`` — a SINGLE call, never both, with
NO token-budget inflation and the architecture-plan JSON contract unchanged.

These tests lock that contract WITHOUT any network access by stubbing the
provider objects.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.services.llm.provider_factory import AGENT_PROVIDER_MAP, ProviderFactory
from backend.app.services.llm.token_strategy import (
    get_agent_token_config,
    resolve_output_token_budget,
)


# ── A. Routing is registered for the planning agent ──────────────────────────

def test_planner_agent_routes_to_openai_primary():
    assert AGENT_PROVIDER_MAP.get("PlannerAgent") == "openai_primary"


def test_for_agent_does_not_force_groq_only_for_planner():
    """``for_agent`` must enable the OpenAI primary path when a key is present."""
    factory = ProviderFactory.for_agent(
        "PlannerAgent",
        openai_api_key="sk-test-not-real",  # client init is offline; no call made
        groq_service=_FakeGroqService(),
    )
    assert factory._agent_name == "PlannerAgent"
    assert factory._primary is not None  # GPT-5-mini primary wired in
    assert factory._openai_enabled is True


# ── B. No token-budget inflation, contract preserved ─────────────────────────

def test_planner_agent_is_not_token_budgeted():
    """PlannerAgent is intentionally absent from AGENT_TOKEN_CONFIG so the
    caller's max_tokens passes through unchanged (no inflation)."""
    assert get_agent_token_config("PlannerAgent") is None

    requested = 900  # PlannerAgent._single_plan asks for 900
    allocated, telemetry = resolve_output_token_budget(
        "PlannerAgent", "system", "user prompt", requested
    )
    assert allocated == requested
    assert telemetry["configured"] is False


# ── C. Single execution: try GPT-5-mini, except → Groq (never both) ──────────

def test_chat_json_falls_back_to_groq_on_primary_failure():
    factory = ProviderFactory(_force_groq_only=True, _agent_name="PlannerAgent")

    primary = _FakePrimary(should_raise=True)
    groq = _FakeGroqProvider(content='{"ok": true, "agent": "PlannerAgent"}')
    factory._primary = primary       # pretend the OpenAI primary exists
    factory._fallback = groq

    result = factory.chat_json(
        system_prompt="sys", user_prompt="usr", temperature=0.1, max_tokens=900,
    )

    assert result == {"ok": True, "agent": "PlannerAgent"}
    # Primary attempted exactly once, fallback used exactly once — not both run.
    assert primary.calls == 1
    assert groq.calls == 1


def test_chat_json_uses_primary_when_it_succeeds():
    factory = ProviderFactory(_force_groq_only=True, _agent_name="PlannerAgent")

    primary = _FakePrimary(content='{"source": "openai"}')
    groq = _FakeGroqProvider(content='{"source": "groq"}')
    factory._primary = primary
    factory._fallback = groq

    result = factory.chat_json(
        system_prompt="sys", user_prompt="usr", temperature=0.1, max_tokens=900,
    )

    assert result == {"source": "openai"}
    assert primary.calls == 1
    assert groq.calls == 0  # Groq NOT touched when the primary returns


# ── Test doubles ──────────────────────────────────────────────────────────────

def _resp(content: str):
    return SimpleNamespace(
        content=content,
        model="gpt-5-mini",
        api_type="responses",
        latency_ms=12,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        finish_reason="stop",
    )


class _FakePrimary:
    model_name = "gpt-5-mini"

    def __init__(self, content: str = "{}", should_raise: bool = False):
        self.content = content
        self.should_raise = should_raise
        self.calls = 0

    def generate_sync(self, **kwargs):
        self.calls += 1
        if self.should_raise:
            raise RuntimeError("primary unavailable")
        return _resp(self.content)


class _FakeGroqProvider:
    def __init__(self, content: str = "{}"):
        self.content = content
        self.calls = 0
        self.model_name = "llama3-8b-8192"

    def generate_sync(self, **kwargs):
        self.calls += 1
        return _resp(self.content)


class _FakeGroqService:
    """Minimal stand-in for LLMService used only for ProviderFactory log lines."""

    model = "llama3-8b-8192"
    key_manager = SimpleNamespace(configured_keys_count=1)
