"""Agent-aware token budgeting for infrastructure generation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentTokenConfig:
    max_output_tokens: int
    retry_on_truncation: bool
    single_request_mode: bool
    small_repo_tokens: int = 4_000
    medium_repo_tokens: int = 8_000
    large_repo_tokens: int = 12_000
    reasoning_effort: str = "low"
    temperature: float = 0.1
    verbosity: str = "low"


AGENT_TOKEN_CONFIG: dict[str, AgentTokenConfig] = {
    "InfrastructureAgent": AgentTokenConfig(
        max_output_tokens=8_000,
        retry_on_truncation=False,
        single_request_mode=True,
    ),
    "TerraformAgent": AgentTokenConfig(
        max_output_tokens=8_000,
        retry_on_truncation=False,
        single_request_mode=True,
    ),
    "KubernetesAgent": AgentTokenConfig(
        max_output_tokens=8_000,
        retry_on_truncation=False,
        single_request_mode=True,
    ),
}


def get_agent_token_config(agent_name: str | None) -> AgentTokenConfig | None:
    if not agent_name:
        return None
    return AGENT_TOKEN_CONFIG.get(agent_name)


def estimate_repo_size(system_prompt: str | None, user_prompt: str | None) -> str:
    """Classify generation context size from prompt volume and infra markers."""
    text = f"{system_prompt or ''}\n{user_prompt or ''}"
    chars = len(text)

    structure_markers = (
        text.count("known_files")
        + text.count("Repository context")
        + text.count("dependency_files")
        + text.count("docker-compose")
        + text.count("terraform")
        + text.count("kubernetes")
    )

    if chars <= 12_000 and structure_markers <= 8:
        return "small"
    if chars <= 36_000 and structure_markers <= 24:
        return "medium"
    return "large"


def resolve_output_token_budget(
    agent_name: str | None,
    system_prompt: str | None,
    user_prompt: str | None,
    requested_tokens: int,
) -> tuple[int, dict[str, Any]]:
    """
    Return a deterministic token budget with no escalation path.

    Non-configured agents keep the caller-provided budget unchanged.
    """
    config = get_agent_token_config(agent_name)
    if config is None:
        return requested_tokens, {
            "agent": agent_name or "unknown",
            "configured": False,
            "repo_size": "unclassified",
            "requested_tokens": requested_tokens,
            "allocated_tokens": requested_tokens,
            "single_request": False,
            "retry_on_truncation": True,
        }

    repo_size = estimate_repo_size(system_prompt, user_prompt)
    if repo_size == "small":
        budget = config.small_repo_tokens
    elif repo_size == "large":
        budget = config.large_repo_tokens
    else:
        budget = config.medium_repo_tokens

    # The budget is precomputed up front. Tiny call-site budgets like 1200/1500
    # never force a retry path for configured infrastructure agents.

    telemetry = {
        "agent": agent_name,
        "configured": True,
        "repo_size": repo_size,
        "requested_tokens": requested_tokens,
        "allocated_tokens": budget,
        "single_request": config.single_request_mode,
        "retry_on_truncation": config.retry_on_truncation,
        "reasoning_effort": config.reasoning_effort,
        "temperature": config.temperature,
        "verbosity": config.verbosity,
    }
    logger.info(
        "[TokenStrategy] agent=%s repo_size=%s requested=%d allocated=%d "
        "single_request=%s retry_on_truncation=%s",
        agent_name,
        repo_size,
        requested_tokens,
        budget,
        config.single_request_mode,
        config.retry_on_truncation,
    )
    return budget, telemetry
