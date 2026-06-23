"""Optional LLM enrichment (OPTIONAL phase).

The template is ALWAYS the source of truth. This step is a thin, defensive
refinement pass: it hands the already-rendered workflow to an LLM and asks ONLY
for small improvements (clarifying comments, conservative hardening) — it never
asks the model to author a workflow from scratch.

It is DEFAULT-OFF (``settings.GITHUB_ACTIONS_LLM_ENRICH``). Even when enabled it
is fully guarded: the enriched output is accepted ONLY if it still validates as a
GitHub Actions workflow AND preserves the template's job set. Any deviation,
error, or empty response falls back to the original rendered YAML. The caller
therefore can never end up worse off than the deterministic template.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.app.services.github_actions_generation.models import DeploymentContext
from backend.app.services.github_actions_generation.yaml_validator import (
    validate_workflow_yaml,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You refine an EXISTING GitHub Actions deployment workflow. "
    "You must NOT rewrite it from scratch and you must NOT change its triggers, "
    "job names, deployment commands, or the ${{ }} expressions. You may only add "
    "clarifying comments and conservative, well-known hardening (e.g. fail-fast "
    "shell options). Return ONLY the full YAML, no markdown fences, no prose."
)

# Keep the prompt + budget tiny — this is a polish pass, not generation.
_MAX_TOKENS = 2000


@dataclass
class EnrichmentResult:
    content: str
    applied: bool
    reason: str


def is_enrichment_enabled() -> bool:
    from backend.app.core.config import settings

    return bool(getattr(settings, "GITHUB_ACTIONS_LLM_ENRICH", False))


def enrich_workflow(
    rendered_yaml: str,
    context: DeploymentContext,
    *,
    enabled: bool | None = None,
) -> EnrichmentResult:
    """Optionally refine ``rendered_yaml``; fall back to it on ANY problem.

    Returns an :class:`EnrichmentResult` whose ``content`` is always safe to
    persist — either the accepted enrichment or the untouched template render.
    """
    if enabled is None:
        enabled = is_enrichment_enabled()
    if not enabled:
        return EnrichmentResult(rendered_yaml, applied=False, reason="disabled")

    try:
        candidate = _call_llm(rendered_yaml, context)
    except Exception as exc:  # noqa: BLE001 — enrichment must never break the phase
        logger.warning(
            "[GitHubActions] enrichment LLM call failed (%s) — using template",
            exc.__class__.__name__,
        )
        return EnrichmentResult(rendered_yaml, applied=False, reason="llm_error")

    if not candidate or not candidate.strip():
        return EnrichmentResult(rendered_yaml, applied=False, reason="empty_response")

    # ── Guardrails: enriched output must validate AND keep the job set ─────────
    original = validate_workflow_yaml(rendered_yaml)
    enriched = validate_workflow_yaml(candidate)
    if not enriched.valid:
        return EnrichmentResult(rendered_yaml, applied=False, reason="invalid_yaml")
    if _job_names(original.parsed) != _job_names(enriched.parsed):
        return EnrichmentResult(
            rendered_yaml, applied=False, reason="job_set_changed"
        )

    logger.info("[GitHubActions] enrichment applied (jobs preserved)")
    return EnrichmentResult(candidate, applied=True, reason="ok")


def _call_llm(rendered_yaml: str, context: DeploymentContext) -> str:
    # Unmapped agent name → Groq-only via ProviderFactory (no multi-provider
    # coupling, no OpenAI budget). A single sync call.
    from backend.app.services.llm.provider_factory import ProviderFactory

    llm = ProviderFactory.for_agent("GitHubActionsEnricher")
    user_prompt = (
        f"Deployment target: {context.deployment_target}. "
        "Refine the following GitHub Actions workflow per the rules. "
        "Return the full YAML only.\n\n"
        f"{rendered_yaml}"
    )
    return llm.chat(_SYSTEM_PROMPT, user_prompt, temperature=0.1, max_tokens=_MAX_TOKENS)


def _job_names(parsed) -> set:
    if not isinstance(parsed, dict):
        return set()
    jobs = parsed.get("jobs")
    return set(jobs.keys()) if isinstance(jobs, dict) else set()
