"""Agent-aware token budgeting for infrastructure generation.

Real (not fake-dynamic) estimation: the budget is computed from multiple
repository signals so simple projects get a small budget and complex ones
get the headroom they need.

Tiers
-----
tiny    →  2 500 –  4 000   single FastAPI / Flask, one dependency file
small   →  4 000 –  5 500   small backend, no compose, no k8s
medium  →  6 000 –  9 000   Spring Boot or React+backend with compose
large   → 10 000 – 14 000   multi-service, k8s manifests, terraform
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentTokenConfig:
    tiny_tokens: int = 3_500
    small_tokens: int = 5_000
    medium_tokens: int = 8_000
    large_tokens: int = 12_000
    retry_on_truncation: bool = True
    single_request_mode: bool = True
    reasoning_effort: str = "low"
    temperature: float = 0.1
    verbosity: str = "low"


# Per-agent overrides. K8s and Terraform agents lean larger because their
# artifact output is heavier (YAML manifests, multi-resource HCL).
AGENT_TOKEN_CONFIG: dict[str, AgentTokenConfig] = {
    "InfrastructureAgent": AgentTokenConfig(
        tiny_tokens=3_500,
        small_tokens=5_000,
        medium_tokens=8_000,
        large_tokens=12_000,
    ),
    "TerraformAgent": AgentTokenConfig(
        tiny_tokens=4_500,
        small_tokens=6_500,
        medium_tokens=9_500,
        large_tokens=14_000,
    ),
    "KubernetesAgent": AgentTokenConfig(
        tiny_tokens=4_500,
        small_tokens=6_500,
        medium_tokens=9_500,
        large_tokens=14_000,
    ),
}


def get_agent_token_config(agent_name: str | None) -> AgentTokenConfig | None:
    if not agent_name:
        return None
    return AGENT_TOKEN_CONFIG.get(agent_name)


# ── Signal extraction ────────────────────────────────────────────────────────

def _count(text: str, *needles: str) -> int:
    return sum(text.lower().count(n.lower()) for n in needles)


def _extract_signals(system_prompt: str | None, user_prompt: str | None) -> dict[str, int]:
    """Pull repo-shape signals out of the assembled prompt text."""
    text = f"{system_prompt or ''}\n{user_prompt or ''}"
    chars = len(text)

    service_count = _count(text, '"name":', "service:", "services:") // 2
    dep_manifests = _count(
        text,
        "requirements.txt", "requirements-backend.txt", "pyproject.toml",
        "package.json", "pnpm-lock", "yarn.lock",
        "pom.xml", "build.gradle",
        "go.mod", "cargo.toml",
    )
    framework_signals = _count(
        text,
        "fastapi", "flask", "django",
        "spring", "springboot", "spring_boot",
        "express", "nestjs", "react", "vue", "next",
    )
    has_k8s = _count(text, "kubernetes", "k8s", "kind: Deployment", "kind: Service") > 0
    has_tf = _count(text, "terraform", "resource \"aws_", "provider \"aws") > 0
    languages = _count(text, '"languages"') + _count(text, '"language":')

    return {
        "chars": chars,
        "services": max(service_count, 0),
        "deps": dep_manifests,
        "frameworks": framework_signals,
        "languages": languages,
        "k8s": 1 if has_k8s else 0,
        "tf": 1 if has_tf else 0,
    }


def classify_repo_size(signals: dict[str, int]) -> str:
    """Map a signal bundle to one of: tiny | small | medium | large.

    Decision rules — first match wins:
      - any k8s/terraform marker OR services >= 3 OR deps >= 4   → large
      - services >= 2 OR deps >= 2 OR frameworks >= 2 OR chars > 28k → medium
      - deps == 1 AND frameworks <= 1 AND chars <= 9k AND services <= 1 → tiny
      - otherwise                                                 → small
    """
    if signals["k8s"] or signals["tf"] or signals["services"] >= 3 or signals["deps"] >= 4:
        return "large"
    if (
        signals["services"] >= 2
        or signals["deps"] >= 2
        or signals["frameworks"] >= 2
        or signals["chars"] > 28_000
    ):
        return "medium"
    if (
        signals["deps"] <= 1
        and signals["frameworks"] <= 1
        and signals["chars"] <= 9_000
        and signals["services"] <= 1
    ):
        return "tiny"
    return "small"


def estimate_repo_size(system_prompt: str | None, user_prompt: str | None) -> str:
    """Backwards-compatible classifier shim used by older callers."""
    signals = _extract_signals(system_prompt, user_prompt)
    return classify_repo_size(signals)


def resolve_output_token_budget(
    agent_name: str | None,
    system_prompt: str | None,
    user_prompt: str | None,
    requested_tokens: int,
) -> tuple[int, dict[str, Any]]:
    """
    Return a dynamically-sized token budget and telemetry.

    Non-configured agents keep the caller-provided budget unchanged.
    """
    config = get_agent_token_config(agent_name)
    if config is None:
        return requested_tokens, {
            "agent": agent_name or "unknown",
            "configured": False,
            "repo_size": "unclassified",
            "signals": {},
            "requested_tokens": requested_tokens,
            "allocated_tokens": requested_tokens,
            "single_request": False,
            "retry_on_truncation": True,
        }

    signals = _extract_signals(system_prompt, user_prompt)
    repo_size = classify_repo_size(signals)

    if repo_size == "tiny":
        budget = config.tiny_tokens
    elif repo_size == "small":
        budget = config.small_tokens
    elif repo_size == "large":
        budget = config.large_tokens
    else:
        budget = config.medium_tokens

    # If the caller explicitly asked for more (e.g. section_generator wants 1500
    # while we'd allocate 3500), allow the higher of the two — never starve.
    budget = max(budget, requested_tokens)

    telemetry = {
        "agent": agent_name,
        "configured": True,
        "repo_size": repo_size,
        "signals": signals,
        "requested_tokens": requested_tokens,
        "allocated_tokens": budget,
        "single_request": config.single_request_mode,
        "retry_on_truncation": config.retry_on_truncation,
        "reasoning_effort": config.reasoning_effort,
        "temperature": config.temperature,
        "verbosity": config.verbosity,
    }
    logger.info(
        "[TokenStrategy] agent=%s repo_size=%s services=%d frameworks=%d "
        "deps=%d k8s=%d tf=%d chars=%d requested=%d allocated=%d",
        agent_name, repo_size,
        signals["services"], signals["frameworks"], signals["deps"],
        signals["k8s"], signals["tf"], signals["chars"],
        requested_tokens, budget,
    )
    return budget, telemetry
