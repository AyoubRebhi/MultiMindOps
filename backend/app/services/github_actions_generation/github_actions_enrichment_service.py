"""GPT-5-mini enrichment for GitHub Actions deployment workflows (OPTIONAL phase).

Pipeline position:

    deployment context → template selection → render → [ENRICH] → YAML validation → persist

The rendered template is the SOURCE OF TRUTH. GPT-5-mini is a polish layer only.
It MAY improve caching, permissions, concurrency, naming, comments, action
versions, retry behaviour, and artifact retention. It may NEVER author the
workflow from scratch, remove jobs, drop the terraform / Docker / deployment
steps, or change the deployment target.

Every enriched candidate is verified against the original render BEFORE it is
accepted:

  1. non-empty,
  2. valid GitHub Actions YAML,
  3. identical job set (no job removed/renamed),
  4. every critical deployment marker present in the original survives
     (``terraform apply``, ``configure-aws-credentials``, ECR login,
     ``docker build``/``docker push`` and the target-specific deploy command
     such as ``aws ecs update-service`` / ``aws lambda update-function-code`` /
     ``aws eks update-kubeconfig`` / ``aws ssm send-command``).

ANY deviation, error, invalid YAML, or empty response falls back to the
untouched template render, so the caller can never end up worse off than the
deterministic template. Provider routing is GPT-5-mini primary → Groq fallback
via :class:`ProviderFactory` (``GitHubActionsEnricher`` agent route).

DEFAULT-OFF via ``settings.ENABLE_GITHUB_ACTIONS_ENRICHMENT``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from backend.app.services.github_actions_generation.models import DeploymentContext
from backend.app.services.github_actions_generation.yaml_validator import (
    validate_workflow_yaml,
)

logger = logging.getLogger(__name__)

# Provider route key (see AGENT_PROVIDER_MAP): GPT-5-mini primary → Groq fallback.
AGENT_NAME = "GitHubActionsEnricher"

# Output budget for a single polish pass. The rendered workflow is small
# (~2-3 KB); this leaves headroom for added comments/steps + GPT-5 reasoning
# tokens. chat() does not retry on truncation, so a truncated response simply
# fails YAML validation and we fall back to the template — never unsafe.
_MAX_TOKENS = 8000
# Low temperature → deterministic, conservative edits.
_TEMPERATURE = 0.1

# ── Strict system prompt (Phase 3) ───────────────────────────────────────────
_SYSTEM_PROMPT = (
    "You are improving an existing GitHub Actions workflow.\n"
    "\n"
    "You must not remove jobs.\n"
    "You must not remove deployment steps.\n"
    "You must not remove the Terraform steps (terraform init / terraform apply).\n"
    "You must not remove the Docker build/push steps.\n"
    "You must not change the deployment target.\n"
    "You must not redesign the workflow or author one from scratch.\n"
    "You must not alter the ${{ ... }} expressions, secret names, env var "
    "names, resource names, or the deploy commands.\n"
    "\n"
    "You may only improve the existing workflow by adding well-known, "
    "conservative best practices: dependency/layer caching, least-privilege "
    "permissions, concurrency groups, clearer step names and comments, pinned "
    "action versions, artifact retention, and retry/fail-fast behaviour.\n"
    "\n"
    "Return valid YAML only. No markdown fences, no prose, no explanation."
)

# Critical deployment markers. Any of these present in the ORIGINAL render MUST
# survive enrichment; this is what concretely enforces "preserve terraform
# apply / Docker steps / deployment steps / deployment target". They are checked
# dynamically (only those present in the original are required), so a target that
# legitimately lacks one is never falsely rejected.
_CRITICAL_MARKERS: tuple[str, ...] = (
    "terraform init",
    "terraform apply",
    "configure-aws-credentials",
    "amazon-ecr-login",
    "docker build",
    "docker push",
    "aws ecs update-service",
    "aws lambda update-function-code",
    "aws eks update-kubeconfig",
    "kubectl",
    "aws ssm send-command",
)


@dataclass
class EnrichmentResult:
    """Result of an enrichment attempt; ``content`` is ALWAYS safe to persist."""

    content: str
    applied: bool
    reason: str


class _LogSink:
    """Append workflow-log entries (UI-visible) and mirror them to the logger."""

    def __init__(self, logs: Optional[List[dict]]) -> None:
        self._logs = logs

    def emit(self, message: str) -> None:
        if self._logs is not None:
            self._logs.append({"step": "github_actions", "message": message})
        logger.info("[GitHubActions][enrichment] %s", message)


class GitHubActionsEnrichmentService:
    """Optional GPT-5-mini refinement of a rendered deploy.yml (template-first)."""

    AGENT_NAME = AGENT_NAME

    @staticmethod
    def is_enabled() -> bool:
        from backend.app.core.config import settings

        return bool(getattr(settings, "ENABLE_GITHUB_ACTIONS_ENRICHMENT", False))

    @classmethod
    def enrich(
        cls,
        rendered_yaml: str,
        context: DeploymentContext,
        *,
        enabled: Optional[bool] = None,
        logs: Optional[List[dict]] = None,
        forbidden_markers: tuple[str, ...] = (),
    ) -> EnrichmentResult:
        """Optionally refine ``rendered_yaml``; fall back to it on ANY problem.

        Returns an :class:`EnrichmentResult` whose ``content`` is always safe to
        persist — either the accepted enrichment or the untouched template
        render.

        ``forbidden_markers`` lets a caller reject an enrichment that INTRODUCES a
        step that must not exist for this pipeline kind (e.g. the delivery
        workflow must never gain ``terraform apply``). A forbidden marker that is
        absent from the original render but present in the candidate triggers a
        fallback to the template.
        """
        log = _LogSink(logs)

        if enabled is None:
            enabled = cls.is_enabled()
        if not enabled:
            return EnrichmentResult(rendered_yaml, applied=False, reason="disabled")

        log.emit("Optimizing workflow with AI...")
        log.emit(
            "Starting GPT-5-mini enrichment (template remains the source of truth)."
        )

        # ── Call GPT-5-mini (never lets an LLM error break the phase) ──────────
        try:
            log.emit("Calling GPT-5-mini to refine the deployment workflow.")
            candidate = cls._call_llm(rendered_yaml, context)
        except Exception as exc:  # noqa: BLE001 — enrichment must never break the phase
            logger.warning(
                "[GitHubActions] enrichment LLM call failed (%s) — using template",
                exc.__class__.__name__,
            )
            log.emit("Enrichment failed (llm_error); falling back to the template.")
            return EnrichmentResult(rendered_yaml, applied=False, reason="llm_error")

        candidate = _strip_code_fences(candidate or "")
        if not candidate.strip():
            log.emit("Enrichment returned an empty workflow; falling back to the template.")
            return EnrichmentResult(rendered_yaml, applied=False, reason="empty_response")

        # ── Guardrails: validate + preserve jobs + preserve critical steps ────
        original = validate_workflow_yaml(rendered_yaml)
        enriched = validate_workflow_yaml(candidate)

        if not enriched.valid:
            log.emit("Enriched workflow failed YAML validation; falling back to the template.")
            return EnrichmentResult(rendered_yaml, applied=False, reason="invalid_yaml")

        if _job_names(original.parsed) != _job_names(enriched.parsed):
            log.emit("Enriched workflow changed the job set; falling back to the template.")
            return EnrichmentResult(rendered_yaml, applied=False, reason="job_set_changed")

        missing = _missing_markers(rendered_yaml, candidate)
        if missing:
            log.emit(
                "Enriched workflow dropped critical deployment steps "
                f"({', '.join(missing)}); falling back to the template."
            )
            return EnrichmentResult(
                rendered_yaml, applied=False, reason="critical_step_removed"
            )

        introduced = _added_markers(rendered_yaml, candidate, forbidden_markers)
        if introduced:
            log.emit(
                "Enriched workflow introduced forbidden steps "
                f"({', '.join(introduced)}); falling back to the template."
            )
            return EnrichmentResult(
                rendered_yaml, applied=False, reason="forbidden_step_added"
            )

        log.emit("Enrichment succeeded (jobs and deployment steps preserved).")
        return EnrichmentResult(candidate, applied=True, reason="ok")

    # ── LLM call ──────────────────────────────────────────────────────────────

    @classmethod
    def _call_llm(cls, rendered_yaml: str, context: DeploymentContext) -> str:
        from backend.app.services.llm.provider_factory import ProviderFactory

        llm = ProviderFactory.for_agent(cls.AGENT_NAME)
        user_prompt = cls._build_user_prompt(rendered_yaml, context)
        return llm.chat(
            _SYSTEM_PROMPT,
            user_prompt,
            temperature=_TEMPERATURE,
            max_tokens=_MAX_TOKENS,
        )

    @staticmethod
    def _build_user_prompt(rendered_yaml: str, context: DeploymentContext) -> str:
        summary = context.infrastructure_summary or {}
        summary_line = (
            "; ".join(f"{k}={v}" for k, v in summary.items()) or "none"
        )
        return (
            "Improve the following GitHub Actions deployment workflow.\n"
            f"Cloud provider: {context.cloud_provider}\n"
            f"Deployment target: {context.deployment_target}\n"
            f"AWS region: {context.aws_region}\n"
            f"Docker artifacts: {', '.join(context.docker_artifacts) or 'none'}\n"
            f"Terraform artifacts: {', '.join(context.terraform_artifacts) or 'none'}\n"
            f"Infrastructure summary: {summary_line}\n"
            "\n"
            "Apply ONLY the allowed improvements. Preserve every job and every "
            "Terraform, Docker, and deployment step exactly. Return the full "
            "YAML only.\n\n"
            f"{rendered_yaml}"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _job_names(parsed) -> set:
    if not isinstance(parsed, dict):
        return set()
    jobs = parsed.get("jobs")
    return set(jobs.keys()) if isinstance(jobs, dict) else set()


def _missing_markers(original: str, candidate: str) -> list[str]:
    """Critical markers present in ``original`` but absent from ``candidate``."""
    orig_lower = original.lower()
    cand_lower = candidate.lower()
    return [
        marker
        for marker in _CRITICAL_MARKERS
        if marker in orig_lower and marker not in cand_lower
    ]


def _added_markers(
    original: str, candidate: str, markers: tuple[str, ...]
) -> list[str]:
    """Forbidden ``markers`` absent from ``original`` but present in ``candidate``."""
    orig_lower = original.lower()
    cand_lower = candidate.lower()
    return [
        marker
        for marker in markers
        if marker not in orig_lower and marker in cand_lower
    ]


def _strip_code_fences(text: str) -> str:
    """Remove a leading/trailing ```yaml ... ``` fence if the model added one."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    # Drop the opening fence line (``` or ```yaml) and a trailing fence line.
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
