"""
Abstract base class for all corrector agents.

Contract:
  - Receive execution logs + artifact context
  - Return a structured CorrectorResult
  - NEVER write files or apply changes directly
  - NEVER trigger retries directly
  - All failures must be caught internally; analyze() never propagates exceptions

Future concrete implementations:
  - DockerCorrectorAgent (Phase 1 — this codebase)
  - TerraformCorrectorAgent
  - KubernetesCorrectorAgent
  - CICDCorrectorAgent
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from .remediation_models import CorrectorResult


class BaseCorrectorAgent(ABC):
    """
    Contract for all corrector agents in the DevSecOps platform.

    Subclasses implement `analyze()` and must:
      1. Run deterministic extraction/classification first.
      2. Optionally enrich results with an LLM.
      3. Return a CorrectorResult conforming to the platform schema.
      4. Never raise — wrap all exceptions and return an error result.
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._log = logging.getLogger(f"corrector.{agent_name}")

    @abstractmethod
    async def analyze(
        self,
        raw_logs: str,
        artifacts: Optional[dict] = None,
        context: Optional[dict] = None,
    ) -> CorrectorResult:
        """
        Analyze an execution failure and produce structured remediation.

        Args:
            raw_logs:  Raw execution output (stdout + stderr from the build).
            artifacts: Optional dict of artifact file contents, e.g.
                       {"dockerfile": "FROM python:3.11\n..."}.
            context:   Optional metadata dict, e.g. {"task_id": "...",
                       "image_tag": "...", "build_number": 2}.

        Returns:
            CorrectorResult — always, even if analysis fails internally.
        """
        ...

    # ── Shared logging helpers ────────────────────────────────────────────────

    def _log_analysis_start(self, task_id: Optional[str] = None) -> None:
        self._log.info(
            "[Corrector] Starting analysis: agent=%s task=%s",
            self.agent_name,
            task_id or "unknown",
        )

    def _log_analysis_complete(self, result: CorrectorResult) -> None:
        self._log.info(
            "[Corrector] Analysis complete: agent=%s type=%s confidence=%.2f "
            "retry=%s llm_enriched=%s fixes=%d",
            self.agent_name,
            result.error_type.value,
            result.confidence,
            result.retry_recommended,
            result.llm_enriched,
            len(result.fixes),
        )
