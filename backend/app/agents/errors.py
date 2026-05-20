"""
Structured agent error hierarchy.

Every agent that fails should raise a subclass of ``AgentError`` with a
machine-readable ``code``. The orchestrator and the FastAPI routes can then
distinguish ``blueprint_contract_violation`` (user-fixable: re-run analysis)
from ``terraform_llm_invalid_json`` (transient: retry) without parsing strings.

Frontend phase-routing already proves this pattern works for the corrector
flow — these classes formalise it for the rest of the agent graph.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class AgentError(Exception):
    """
    Base class for all agent-originated failures.

    Attributes
    ----------
    code : str
        Stable, machine-readable identifier (snake_case). Frontend routes on this.
    message : str
        Human-readable description; safe to surface in the UI.
    recoverable : bool
        ``True`` if a retry can plausibly succeed without user intervention
        (e.g. transient LLM JSON parse failure). ``False`` for contract
        violations and config bugs.
    phase : str | None
        The workflow phase that raised this error (``"planning"``,
        ``"terraform_generation"``, etc.). Surfaces via ``current_phase``.
    metadata : dict
        Free-form structured payload (validation errors, raw LLM response,
        retry counts, etc.). Never logged secrets.
    """

    code: str = "agent_error"
    recoverable: bool = False
    default_phase: Optional[str] = None

    def __init__(
        self,
        message: str,
        *,
        recoverable: Optional[bool] = None,
        phase: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if recoverable is not None:
            self.recoverable = recoverable
        self.phase = phase or self.default_phase
        self.metadata: Dict[str, Any] = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Serialisable form for HTTP responses / workflow state logs."""
        return {
            "error_class": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
            "phase": self.phase,
            "metadata": self.metadata,
        }


# ── Contract / generation errors ──────────────────────────────────────────────


class BlueprintContractError(AgentError):
    """
    Raised when a payload claiming to be an InfrastructureBlueprint does not
    match the schema. ALWAYS non-recoverable — it indicates a code-level
    drift between the producer (planner / architecture-decision) and the
    consumer (terraform / kubernetes).
    """

    code = "blueprint_contract_violation"
    recoverable = False
    default_phase = "planning"


class TerraformGenerationError(AgentError):
    """
    Raised when TerraformAgent could not produce valid HCL after exhausting
    its ReAct retries. ``recoverable=True`` because the same prompt may
    succeed on a subsequent LLM call.
    """

    code = "terraform_generation_failed"
    recoverable = True
    default_phase = "terraform_generation"


class TerraformValidationError(AgentError):
    """
    Raised when generated HCL is syntactically valid but fails one of the
    deterministic validators (hcl2 / fmt / validate / tfsec / checkov).

    The corrector agent (future Phase 4 work) consumes this to draft a patch.
    """

    code = "terraform_validation_failed"
    recoverable = True
    default_phase = "terraform_validation"

    def __init__(
        self,
        message: str,
        *,
        validator: str,
        findings: Optional[list] = None,
        **kwargs: Any,
    ) -> None:
        meta = kwargs.pop("metadata", {}) or {}
        meta.setdefault("validator", validator)
        meta.setdefault("findings", findings or [])
        super().__init__(message, metadata=meta, **kwargs)


class PlanPropagationError(AgentError):
    """
    Raised by ``resume_with_selected_plan`` when the user-selected strategy
    cannot be located in the architecture_decision payload. Was previously
    a bare ``ValueError``.
    """

    code = "plan_propagation_failed"
    recoverable = False
    default_phase = "plan_selection"
