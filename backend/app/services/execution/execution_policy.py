"""ExecutionPolicy — composable execution-time gates.

A "gate" is a pure function that takes an :class:`ExecutionContext` and
returns a :class:`GateDecision`. The policy is a list of gates; the
executor runs every gate (or short-circuits on the first denial,
configurably). The Terraform executor — when it eventually lands — will
build its policy from these gates rather than re-implementing the
checks inline.

Why a policy layer NOW (before TerraformExecutor exists)
--------------------------------------------------------
* Gives the audit's stale-approval / drift / severity checks a single
  named home, so a future executor cannot "forget" to invoke one.
* The current set of gates is testable independently of the executor —
  we prove the gates accept/reject correctly without ever running
  ``terraform apply``.
* New gates (cost ceiling, plan-hash freshness, environment-tag match)
  slot in as additional list entries — no refactor.

Gates shipped in Phase 5
------------------------
* :func:`approval_gate` — the release candidate is formally approved AND
  every snapshot still matches the live artifact.
* :func:`severity_gate` — no security finding above the configured
  severity ceiling.
* :func:`stale_plan_gate` — the plan output the executor is about to
  apply matches the hash that was approved (apply-on-stale-plan refusal).
* :func:`environment_isolation_gate` — the candidate's environment tag
  matches the executor's environment (prevents a "dev" candidate from
  landing on "prod" by misconfiguration).

The actual subprocess invocation of ``terraform apply`` is OUT OF SCOPE
for this phase — only the gating contract is built.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.release import ReleaseCandidate
from backend.app.services.core.release_service import require_executable_candidate

logger = logging.getLogger(__name__)


# Severity ordering — higher index = more severe. Anything ≥ the ceiling
# the gate is configured with is rejected.
_SEVERITY_ORDER = ["info", "low", "warning", "medium", "high", "error", "critical"]


def _severity_at_least(level: str, ceiling: str) -> bool:
    """True iff ``level`` is at least as severe as ``ceiling``.

    Unknown levels are treated as 'info' (the safest assumption — don't
    accidentally block on a level we don't recognise).
    """
    def _rank(s: str) -> int:
        try:
            return _SEVERITY_ORDER.index((s or "info").strip().lower())
        except ValueError:
            return 0
    return _rank(level) >= _rank(ceiling)


@dataclass
class ExecutionContext:
    """Everything a gate needs to make a decision.

    Fields are optional so a gate that doesn't care about a particular
    field can be skipped by ``policy_for`` without breaking the contract.
    A field that IS required by a chosen gate and is None ⇒ the gate
    denies with a clear "missing data" reason rather than crashing.
    """

    db: Session
    project_id: str
    target_phase: str  # "terraform_apply" | "terraform_destroy" | "kubernetes_deploy" | ...
    release_candidate: Optional[ReleaseCandidate] = None
    # Most-severe security finding observed by the validator pipeline.
    # E.g. "critical" if tfsec flagged a critical issue.
    max_security_severity: Optional[str] = None
    # Hash of the terraform plan output the executor IS ABOUT TO apply.
    plan_hash: Optional[str] = None
    # Hash of the plan that was approved (stored on the release candidate's
    # metadata, typically). Mismatch ⇒ stale-plan refusal.
    approved_plan_hash: Optional[str] = None
    # "dev" | "staging" | "prod" — labels the executor was configured for.
    executor_environment: Optional[str] = None
    # Same label baked into the candidate (typically from
    # release.candidate_metadata["environment"]).
    candidate_environment: Optional[str] = None


@dataclass
class GateDecision:
    allow: bool
    gate: str
    reason: str = ""

    @classmethod
    def allowed(cls, gate: str, reason: str = "") -> "GateDecision":
        return cls(allow=True, gate=gate, reason=reason)

    @classmethod
    def denied(cls, gate: str, reason: str) -> "GateDecision":
        return cls(allow=False, gate=gate, reason=reason)


Gate = Callable[[ExecutionContext], GateDecision]


# ── Built-in gates ────────────────────────────────────────────────────────


def approval_gate(ctx: ExecutionContext) -> GateDecision:
    """Refuses execution unless the candidate is formally approved AND
    every snapshot still matches the live artifact (no drift)."""
    if ctx.release_candidate is None:
        return GateDecision.denied(
            "approval", "No release candidate attached — refusing execution."
        )
    decision = require_executable_candidate(ctx.db, ctx.release_candidate)
    if decision.executable:
        return GateDecision.allowed(
            "approval",
            f"Candidate {ctx.release_candidate.id} is approved and unchanged.",
        )
    return GateDecision.denied("approval", decision.primary_reason)


def make_severity_gate(*, ceiling: str = "high") -> Gate:
    """Returns a gate that refuses if any finding ≥ ``ceiling`` was seen.

    ``ceiling`` accepts ``info|low|warning|medium|high|error|critical``.
    Default ``high`` matches the audit's "tfsec/checkov findings at HIGH
    must block apply" recommendation.
    """
    def _gate(ctx: ExecutionContext) -> GateDecision:
        if ctx.max_security_severity is None:
            # Absent severity ⇒ no validator ran. Don't allow execution
            # without evidence — that's how silently-skipped scanners
            # become production incidents.
            return GateDecision.denied(
                "severity",
                "No security validation result available (validator did not run "
                "or was skipped). Refusing execution.",
            )
        if _severity_at_least(ctx.max_security_severity, ceiling):
            return GateDecision.denied(
                "severity",
                f"Security severity '{ctx.max_security_severity}' is at or above "
                f"the configured ceiling '{ceiling}'.",
            )
        return GateDecision.allowed(
            "severity",
            f"Highest severity '{ctx.max_security_severity}' is below ceiling '{ceiling}'.",
        )
    return _gate


def stale_plan_gate(ctx: ExecutionContext) -> GateDecision:
    """Refuses to apply a plan that differs from the one that was approved.

    The TerraformExecutor will produce a plan, store its hash on the
    release candidate at approval time, then re-plan immediately before
    apply. A hash mismatch means the inputs changed (artifact edit, state
    drift) and the apply would do something the reviewer did not see —
    the same class of risk as the artifact-drift gate, one layer down.
    """
    if not ctx.plan_hash or not ctx.approved_plan_hash:
        return GateDecision.denied(
            "stale_plan",
            "Plan hashes not provided — cannot verify the apply matches "
            "what was approved.",
        )
    if ctx.plan_hash != ctx.approved_plan_hash:
        return GateDecision.denied(
            "stale_plan",
            f"Plan hash changed since approval "
            f"(approved={ctx.approved_plan_hash[:12]} now={ctx.plan_hash[:12]}). "
            "Re-plan + re-approve before applying.",
        )
    return GateDecision.allowed(
        "stale_plan", "Plan hash matches the approved plan."
    )


def environment_isolation_gate(ctx: ExecutionContext) -> GateDecision:
    """Refuses if the candidate's environment doesn't match the executor's.

    Cheap mis-routing protection — a "dev" candidate that somehow lands
    on the prod executor is the most-feared single-character mistake.
    """
    if not ctx.executor_environment or not ctx.candidate_environment:
        return GateDecision.denied(
            "environment_isolation",
            "Environment tags missing on candidate or executor — refusing "
            "to execute without explicit environment alignment.",
        )
    if ctx.executor_environment.strip().lower() != ctx.candidate_environment.strip().lower():
        return GateDecision.denied(
            "environment_isolation",
            f"Candidate environment '{ctx.candidate_environment}' does not match "
            f"executor environment '{ctx.executor_environment}'.",
        )
    return GateDecision.allowed(
        "environment_isolation",
        f"Both candidate and executor target '{ctx.executor_environment}'.",
    )


# ── Policy composition ─────────────────────────────────────────────────────


@dataclass
class PolicyResult:
    allowed: bool
    decisions: List[GateDecision] = field(default_factory=list)

    @property
    def denials(self) -> List[GateDecision]:
        return [d for d in self.decisions if not d.allow]


def evaluate(
    ctx: ExecutionContext,
    gates: List[Gate],
    *,
    short_circuit: bool = True,
) -> PolicyResult:
    """Run gates against ``ctx`` and aggregate the result.

    ``short_circuit=True`` (default) stops at the first denial — useful
    when downstream gates rely on data the failed gate would have
    populated. ``False`` runs every gate so the UI can render the full
    list of issues at once.
    """
    decisions: List[GateDecision] = []
    for gate in gates:
        decision = gate(ctx)
        decisions.append(decision)
        if not decision.allow and short_circuit:
            return PolicyResult(allowed=False, decisions=decisions)
    return PolicyResult(
        allowed=all(d.allow for d in decisions),
        decisions=decisions,
    )


# Convenience: the canonical Terraform-apply policy. The future
# TerraformExecutor builds this once and passes it to ``evaluate``.
def terraform_apply_policy(*, severity_ceiling: str = "high") -> List[Gate]:
    return [
        approval_gate,
        make_severity_gate(ceiling=severity_ceiling),
        stale_plan_gate,
        environment_isolation_gate,
    ]
