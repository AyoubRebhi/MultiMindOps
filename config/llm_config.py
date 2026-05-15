"""
Centralized LLM configuration.

All provider-related defaults live here.  The actual values are loaded from
environment variables (via pydantic-settings in backend/app/core/config.py) —
this module documents the shape and serves as a reference for operators.

API routing rules:
  GPT-5 family (gpt-5*)  → OpenAI Responses API   (/v1/responses)
                           parameter: max_output_tokens
  All other OpenAI models → Chat Completions API  (/v1/chat/completions)
                           parameter: max_tokens (gpt-4) | max_completion_tokens (o-series)

Provider priority by agent:
  InfrastructureAgent    → OpenAI GPT-5.4-mini (PRIMARY)  → Groq (FALLBACK)
  TerraformAgent         → OpenAI GPT-5.4-mini (PRIMARY)  → Groq (FALLBACK)
  KubernetesAgent        → OpenAI GPT-5.4-mini (PRIMARY)  → Groq (FALLBACK)
  All other agents       → Groq only (no OpenAI)

Environment variables consumed by ProviderFactory:
  OPENAI_KEY           — OpenAI API key (sk-...)
  OPENAI_MODEL         — model identifier (default: gpt-5.4-mini)
  OPENAI_TIMEOUT       — request timeout in seconds (default: 120)
  OPENAI_MAX_RETRIES   — transient-error retries (default: 2)

  GROQ_API_KEY         — primary Groq key
  GROQ_API_KEY_2 … _6  — additional keys for rotation
  GROQ_MODEL           — model for direct Groq calls (default: llama-3.3-70b-versatile)
"""

# ── OpenAI defaults ───────────────────────────────────────────────────────────

PRIMARY_LLM_PROVIDER = "openai"
OPENAI_MODEL = "gpt-5.4-mini"
OPENAI_TIMEOUT = 120          # seconds
OPENAI_MAX_RETRIES = 2

# GPT-5 family: must use Responses API, never chat/completions
GPT5_FAMILY_PREFIXES = ("gpt-5",)

# ── Groq fallback defaults ────────────────────────────────────────────────────

FALLBACK_PROVIDER = "groq"
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Agent → provider routing ──────────────────────────────────────────────────
# "openai_primary" = OpenAI GPT-5.4-mini with Groq fallback
# "groq"           = Groq only (no OpenAI)

AGENT_PROVIDER_MAP: dict[str, str] = {
    "InfrastructureAgent": "openai_primary",
    "TerraformAgent":      "openai_primary",
    "KubernetesAgent":     "openai_primary",
    # All other agents default to "groq"
    "PlannerAgent":        "groq",
    "CostEstimationAgent": "groq",
    "RemediationAgent":    "groq",
    "DockerCorrectorAgent": "groq",
}

# ── Centralized model config per role ─────────────────────────────────────────
# Used by ProviderFactory.for_role() and for documentation / future dashboard.

LLM_MODEL_CONFIG: dict[str, dict] = {
    "infra": {
        "provider":        "openai",
        "model":           "gpt-5.4-mini",
        "api_type":        "responses",
        "fallback":        "groq",
        "fallback_model":  "llama-3.3-70b-versatile",
    },
    "terraform": {
        "provider":        "openai",
        "model":           "gpt-5.4-mini",
        "api_type":        "responses",
        "fallback":        "groq",
        "fallback_model":  "llama-3.3-70b-versatile",
    },
    "kubernetes": {
        "provider":        "openai",
        "model":           "gpt-5.4-mini",
        "api_type":        "responses",
        "fallback":        "groq",
        "fallback_model":  "llama-3.3-70b-versatile",
    },
    "planner": {
        "provider":        "groq",
        "model":           "llama-3.3-70b-versatile",
        "api_type":        "chat_completions",
        "fallback":        None,
    },
    "cost": {
        "provider":        "groq",
        "model":           "llama-3.3-70b-versatile",
        "api_type":        "chat_completions",
        "fallback":        None,
    },
    "corrector": {
        "provider":        "groq",
        "model":           "llama-3.3-70b-versatile",
        "api_type":        "chat_completions",
        "fallback":        None,
    },
}

# ── Future provider placeholders (not yet wired) ──────────────────────────────
# ANTHROPIC_MODEL = "claude-opus-4-7"
# GEMINI_MODEL    = "gemini-2.5-pro"
# AZURE_MODEL     = "gpt-5.4-mini"
# DEEPSEEK_MODEL  = "deepseek-v3"
# OLLAMA_MODEL    = "llama3.2:3b"
