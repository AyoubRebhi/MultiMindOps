"""WorkflowTraceService — observability layer over the workflow engine.

This service NEVER drives execution. It only OBSERVES:

* :meth:`sync_from_workflow` materialises an ordered ``WorkflowExecutionTrace``
  per phase FROM the authoritative ``Workflow.phases_state`` (the single source
  of truth) — recording phase start/end timestamps, inputs, artifacts produced
  and failure classification. It is idempotent (safe to call on every read) and
  does not modify ``phases_state``.
* :meth:`record_replay_step` writes ``source='replay'`` trace rows for the
  deterministic replay path.
* :meth:`build_debug_payload` assembles the ``/debug`` view: phase timeline +
  artifacts list + failure classifications + execution trace + an artifact
  completeness audit.

Design constraints honoured: it does not touch ``run_phase`` / ``start_workflow``
/ the finalizers, does not introduce phases, and does not change the state model.
The trace table is purely additive observability.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.workflow import Workflow
from backend.app.models.workflow_execution_trace import WorkflowExecutionTrace
from backend.app.services.core.artifact_persistence_service import (
    classify_artifact,
    extract_artifacts_from_state,
)

logger = logging.getLogger(__name__)

# Canonical phase order for tie-breaking when timestamps collide.
_PHASE_ORDER = [
    "ANALYSIS",
    "ARCHITECTURE_DECISION",
    "PLAN_SELECTED",
    "TERRAFORM_GENERATION",
    "TERRAFORM_VALIDATION",
    "TERRAFORM_PLAN",
    "DOCKER",
    "DOCKER_BUILD",
]

# phases_state ``extra`` keys treated as INPUTS to the phase (vs outputs).
_INPUT_KEYS = (
    "plan_id",
    "current_phase",
    "validation_status",
    "used_llm",
    "fallback_used",
    "generation_mode",
    "build_number",
    "image_tag",
    "file_count",
    "stream_key",
    "job_id",
)

# Build-related artifact types that must be DB-backed (no disk-only files).
_BUILD_ARTIFACT_TYPES = {"docker", "terraform", "kubernetes", "cicd"}

# Normalized status reported for a Terraform phase that has not executed yet.
# The three terraform outcome keys are ALWAYS present in the /debug view so an
# operator never has to infer "did validation run?" from a missing dict entry.
_TF_NOT_RUN = "not_run"


def _to_dt(value: Any) -> Optional[datetime]:
    """Best-effort parse of an ISO string / passthrough of a datetime.

    Always returns a timezone-AWARE datetime (naive values are assumed UTC) so
    timestamps from different sources — tz-aware ``updated_at`` ISO strings vs a
    possibly-naive DB ``created_at`` — can be compared and subtracted safely.
    """
    dt: Optional[datetime] = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso(value: Any) -> Optional[str]:
    dt = _to_dt(value)
    return dt.isoformat() if dt else None


class WorkflowTraceService:
    # ── Live trace materialisation (read-only projection of phases_state) ─────

    @staticmethod
    def sync_from_workflow(db: Session, workflow: Workflow) -> List[WorkflowExecutionTrace]:
        """Materialise/refresh ``source='live'`` trace rows from phases_state.

        Idempotent: re-running updates existing (workflow, phase, live) rows in
        place rather than appending. Returns the ordered live trace rows.
        """
        phases: Dict[str, dict] = dict(workflow.phases_state or {})
        if not phases:
            return []

        wf_created = _to_dt(getattr(workflow, "created_at", None))

        # Order phases chronologically by their recorded update time, breaking
        # ties with the canonical phase order.
        def _sort_key(item):
            name, entry = item
            ended = _to_dt((entry or {}).get("updated_at"))
            order = _PHASE_ORDER.index(name) if name in _PHASE_ORDER else len(_PHASE_ORDER)
            return (ended or datetime.max.replace(tzinfo=timezone.utc), order)

        ordered = sorted(phases.items(), key=_sort_key)

        existing = {
            t.phase: t
            for t in db.query(WorkflowExecutionTrace)
            .filter(
                WorkflowExecutionTrace.workflow_id == workflow.id,
                WorkflowExecutionTrace.source == "live",
            )
            .all()
        }

        rows: List[WorkflowExecutionTrace] = []
        prev_end: Optional[datetime] = None
        for seq, (phase, entry) in enumerate(ordered):
            entry = entry or {}
            status = entry.get("status", "unknown")
            ended = _to_dt(entry.get("updated_at"))
            started = prev_end or wf_created
            # Guard against clock skew / out-of-order seed data: a derived start
            # must never be after the phase's recorded end.
            if started and ended and started > ended:
                started = ended
            prev_end = ended or prev_end

            duration_ms: Optional[int] = None
            if started and ended and ended >= started:
                duration_ms = int((ended - started).total_seconds() * 1000)

            extra = {k: v for k, v in entry.items() if k not in ("status", "updated_at")}
            inputs = {k: extra[k] for k in _INPUT_KEYS if k in extra}
            artifacts_produced: List[dict] = []
            if extra.get("artifact_id"):
                artifacts_produced.append({"artifact_id": extra["artifact_id"]})
            if extra.get("image_tag"):
                artifacts_produced.append({"image_tag": extra["image_tag"]})
            failure = extra.get("failure_classification")

            row = existing.get(phase)
            if row is None:
                row = WorkflowExecutionTrace(
                    workflow_id=workflow.id,
                    project_id=workflow.project_id,
                    phase=phase,
                    source="live",
                )
                db.add(row)
            row.status = status
            row.sequence = seq
            row.started_at = started
            row.ended_at = ended
            row.duration_ms = duration_ms
            row.inputs = inputs
            row.artifacts_produced = artifacts_produced
            row.failure_classification = failure
            row.detail = extra
            rows.append(row)

        db.commit()
        return rows

    # ── Replay trace recording ───────────────────────────────────────────────

    @staticmethod
    def record_replay_step(
        db: Session,
        *,
        workflow: Workflow,
        phase: str,
        status: str,
        started_at: Optional[datetime] = None,
        ended_at: Optional[datetime] = None,
        inputs: Optional[dict] = None,
        artifacts_produced: Optional[List[dict]] = None,
        failure_classification: Optional[str] = None,
        detail: Optional[dict] = None,
        commit: bool = True,
    ) -> WorkflowExecutionTrace:
        """Append a ``source='replay'`` trace row for one replayed step."""
        started_at = started_at or datetime.now(timezone.utc)
        duration_ms: Optional[int] = None
        if started_at and ended_at and ended_at >= started_at:
            duration_ms = int((ended_at - started_at).total_seconds() * 1000)

        # Sequence after the current max for this workflow.
        max_seq = (
            db.query(WorkflowExecutionTrace.sequence)
            .filter(WorkflowExecutionTrace.workflow_id == workflow.id)
            .order_by(WorkflowExecutionTrace.sequence.desc())
            .first()
        )
        next_seq = (max_seq[0] + 1) if max_seq and max_seq[0] is not None else 0

        row = WorkflowExecutionTrace(
            workflow_id=workflow.id,
            project_id=workflow.project_id,
            phase=phase,
            status=status,
            source="replay",
            sequence=next_seq,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            inputs=dict(inputs or {}),
            artifacts_produced=list(artifacts_produced or []),
            failure_classification=failure_classification,
            detail=dict(detail or {}),
        )
        db.add(row)
        if commit:
            db.commit()
            db.refresh(row)
        return row

    # ── Reads ─────────────────────────────────────────────────────────────────

    @staticmethod
    def get_trace(db: Session, workflow_id: str) -> List[WorkflowExecutionTrace]:
        return (
            db.query(WorkflowExecutionTrace)
            .filter(WorkflowExecutionTrace.workflow_id == workflow_id)
            .order_by(
                WorkflowExecutionTrace.sequence.asc(),
                WorkflowExecutionTrace.created_at.asc(),
            )
            .all()
        )

    @staticmethod
    def _trace_to_dict(row: WorkflowExecutionTrace) -> dict:
        return {
            "id": row.id,
            "phase": row.phase,
            "status": row.status,
            "source": row.source,
            "sequence": row.sequence,
            "started_at": _iso(row.started_at),
            "ended_at": _iso(row.ended_at),
            "duration_ms": row.duration_ms,
            "inputs": dict(row.inputs or {}),
            "artifacts_produced": list(row.artifacts_produced or []),
            "failure_classification": row.failure_classification,
            "detail": dict(row.detail or {}),
        }

    # ── Terraform outcome visibility ──────────────────────────────────────────

    @staticmethod
    def derive_terraform_status(phases_state: Optional[dict]) -> dict:
        """Project the three Terraform outcome statuses out of phases_state.

        The authoritative truth lives in ``Workflow.phases_state`` under the
        per-phase ``TERRAFORM_GENERATION`` / ``TERRAFORM_VALIDATION`` /
        ``TERRAFORM_PLAN`` entries (written by the engine — NOT mutated here).
        This is a pure read-time normalisation that GUARANTEES all three status
        keys are present even when a phase never ran — a degraded or failed
        generation can stop the pipeline before validate/plan, leaving those
        entries absent. Rather than report "missing", we report ``not_run`` so
        the outcome is always explicit.

        The validation status falls back to the generation phase's *inline*
        ``validation_status`` (e.g. ``degraded`` when the provider registry was
        unreachable during generation) when the dedicated validation phase has
        not executed, so an environment outage is never silently invisible.
        """
        phases = phases_state or {}
        gen = phases.get("TERRAFORM_GENERATION") or {}
        val = phases.get("TERRAFORM_VALIDATION") or {}
        plan = phases.get("TERRAFORM_PLAN") or {}

        gen_status = gen.get("status") or _TF_NOT_RUN
        val_status = val.get("status") or gen.get("validation_status") or _TF_NOT_RUN
        plan_status = plan.get("status") or _TF_NOT_RUN

        # Aggregate the failure classification across the terraform phases — the
        # most specific (validation/plan) wins over the generation-time one.
        failure_classification = (
            val.get("failure_classification")
            or plan.get("failure_classification")
            or gen.get("failure_classification")
        )
        return {
            "terraform_generation_status": gen_status,
            "terraform_validation_status": val_status,
            "terraform_plan_status": plan_status,
            "terraform_failure_classification": failure_classification,
        }

    # ── Artifact completeness audit ───────────────────────────────────────────

    @staticmethod
    def audit_artifact_completeness(
        db: Session,
        *,
        project_id: str,
        task_state: Optional[dict],
    ) -> dict:
        """Report any build-related file present in state but NOT DB-backed.

        ``expected`` = classifiable build inputs found in the orchestrator state
        (Dockerfile, compose, env, .tf, k8s, cicd). ``persisted`` = matching
        ``Artifact`` rows. ``missing`` should be EMPTY — anything in it is a file
        that exists only on disk / in scratch, which this phase aims to eliminate.
        """
        state = task_state or {}
        state_files = extract_artifacts_from_state(state)
        expected: List[dict] = []
        for name in sorted(state_files):
            kind = classify_artifact(name)
            if kind in _BUILD_ARTIFACT_TYPES:
                expected.append({"subtype": name, "type": kind})

        persisted_rows = (
            db.query(Artifact)
            .filter(Artifact.project_id == project_id)
            .all()
        )
        persisted_keys = {(r.artifact_type, r.artifact_subtype) for r in persisted_rows}

        missing = [
            e for e in expected if (e["type"], e["subtype"]) not in persisted_keys
        ]

        # Explicit invariant: completeness can NEVER be true while terraform
        # build inputs exist in state but no terraform artifact is DB-backed.
        # This guards against the classification gap that previously let
        # terraform vanish from the DB while this audit still reported complete
        # (the audit shares classify_artifact, so a key it cannot classify is
        # excluded from `expected` — the explicit terraform count closes that).
        tf_expected = [e for e in expected if e["type"] == "terraform"]
        tf_persisted = sum(1 for r in persisted_rows if r.artifact_type == "terraform")
        terraform_complete = (not tf_expected) or (tf_persisted > 0)

        complete = (len(missing) == 0) and terraform_complete

        # Flatten the missing inputs into operator-friendly shapes so the /debug
        # endpoint can render "what is missing" without re-deriving it: a plain
        # list of subtype keys, and the same grouped by artifact type (so a
        # missing terraform key stands out from a missing docker key).
        missing_keys = [e["subtype"] for e in missing]
        missing_by_type: Dict[str, List[str]] = {}
        for e in missing:
            missing_by_type.setdefault(e["type"], []).append(e["subtype"])

        return {
            "expected_build_inputs": expected,
            "persisted_count": len(persisted_rows),
            "persisted_terraform_count": tf_persisted,
            "expected_terraform_count": len(tf_expected),
            "terraform_complete": terraform_complete,
            "missing": missing,
            "missing_keys": missing_keys,
            "missing_by_type": missing_by_type,
            "complete": complete,
        }

    # ── Full /debug payload ───────────────────────────────────────────────────

    @staticmethod
    def build_debug_payload(
        db: Session,
        *,
        workflow: Workflow,
        task_state: Optional[dict] = None,
    ) -> dict:
        """Assemble the unified observability view for ``GET .../debug``."""
        # Materialise the live trace from the authoritative phases_state first.
        WorkflowTraceService.sync_from_workflow(db, workflow)
        trace_rows = WorkflowTraceService.get_trace(db, workflow.id)

        # Ordered phase timeline (live rows) — the human-readable progression.
        timeline = [
            {
                "phase": r.phase,
                "status": r.status,
                "source": r.source,
                "started_at": _iso(r.started_at),
                "ended_at": _iso(r.ended_at),
                "duration_ms": r.duration_ms,
                "failure_classification": r.failure_classification,
            }
            for r in trace_rows
        ]

        # Artifacts list (DB-backed, the single source of truth for files).
        artifacts = (
            db.query(Artifact)
            .filter(Artifact.project_id == workflow.project_id)
            .order_by(Artifact.artifact_type, Artifact.artifact_subtype)
            .all()
        )
        artifacts_payload = [
            {
                "id": a.id,
                "type": a.artifact_type,
                "subtype": a.artifact_subtype,
                "version": a.version,
                "content_hash": a.content_hash,
                "validation_status": a.validation_status,
                "approval_state": a.approval_state,
                "workflow_id": a.workflow_id,
            }
            for a in artifacts
        ]

        # Failure classifications collected across the run (deduped, ordered).
        failures: List[dict] = []
        seen = set()
        for r in trace_rows:
            if r.failure_classification and (r.phase, r.failure_classification) not in seen:
                seen.add((r.phase, r.failure_classification))
                failures.append(
                    {
                        "phase": r.phase,
                        "classification": r.failure_classification,
                        "source": r.source,
                        "status": r.status,
                    }
                )

        completeness = WorkflowTraceService.audit_artifact_completeness(
            db, project_id=workflow.project_id, task_state=task_state,
        )

        # Always-present, normalized Terraform outcome statuses (generation /
        # validation / plan) derived from the authoritative phases_state — even
        # when degraded or never run. Carries the aggregated failure
        # classification so the terraform leg's health is visible at a glance.
        terraform_status = WorkflowTraceService.derive_terraform_status(
            workflow.phases_state
        )

        # Surface a degraded/failed terraform classification in the deduped
        # failure list even when no trace row carried it (e.g. a generation that
        # recorded an inline degraded validation_status without a separate
        # validation phase). Keeps /debug's failure view complete.
        tf_failure = terraform_status.get("terraform_failure_classification")
        if tf_failure and not any(
            f.get("classification") == tf_failure for f in failures
        ):
            failures.append(
                {
                    "phase": "TERRAFORM",
                    "classification": tf_failure,
                    "source": "derived",
                    "status": terraform_status.get("terraform_validation_status"),
                }
            )

        return {
            "workflow_id": workflow.id,
            "project_id": workflow.project_id,
            "status": workflow.status,
            "current_phase": workflow.current_phase,
            "phase_timeline": timeline,
            "terraform_status": terraform_status,
            "artifacts": artifacts_payload,
            "failure_classifications": failures,
            "execution_trace": [
                WorkflowTraceService._trace_to_dict(r) for r in trace_rows
            ],
            "artifact_completeness": completeness,
        }
