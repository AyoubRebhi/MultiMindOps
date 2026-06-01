"""ReleaseService — assemble + evaluate immutable release candidates.

A ``ReleaseCandidate`` is the unit of approval-bound execution. It captures
the EXACT artifact set (type, subtype, version, content_hash, approval state
at snapshot time) that an executor will consume. The candidate is the
contract between governance and execution:

* ``create_candidate`` freezes the current live artifacts into snapshots.
* ``evaluate`` re-checks the live artifacts against the snapshots + the
  per-target required-types list; returns an ``ExecutableDecision`` with the
  reasons it is (or is not) safe to execute.
* ``approve`` / ``reject`` / ``mark_executed`` / ``mark_superseded`` move
  the candidate through its lifecycle.

The evaluation runs at TWO moments:

1. At approval time — so an approver only sees "executable" when every
   constituent is approved.
2. At execution time — re-runs the same check against the live artifact
   rows. If anything drifted between approval and apply (the audit's
   stale-approval risk), the gate refuses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.release import ReleaseArtifactSnapshot, ReleaseCandidate

logger = logging.getLogger(__name__)


# Required artifact types per release target. A terraform_apply that doesn't
# carry a snapshot of artifact_type='terraform' is invalid by construction.
# Extend this map when new release targets land (e.g. helm_install).
REQUIRED_TYPES_BY_TARGET: dict[str, frozenset[str]] = {
    "terraform_apply":   frozenset({"terraform"}),
    "terraform_destroy": frozenset({"terraform"}),
    "kubernetes_deploy": frozenset({"kubernetes"}),
    "docker_build":      frozenset({"docker"}),
}


@dataclass
class ExecutableDecision:
    """Outcome of evaluating whether a candidate is safe to execute now.

    ``executable=True`` means EVERY check passed at evaluation time. The
    enforcement gate must call ``evaluate`` AGAIN just before invoking the
    executor — a candidate that was executable five minutes ago may have
    been invalidated by an artifact edit since.
    """

    executable: bool
    reasons: List[str] = field(default_factory=list)

    @property
    def primary_reason(self) -> str:
        return self.reasons[0] if self.reasons else (
            "Release candidate is executable." if self.executable
            else "Release candidate is not executable."
        )


class ReleaseError(Exception):
    """Service-level failure; routes translate to 4xx."""


class ReleaseService:
    # ── Creation ───────────────────────────────────────────────────────────

    @staticmethod
    def create_candidate(
        db: Session,
        *,
        project_id: str,
        workflow_id: Optional[str],
        target_phase: str,
        created_by: Optional[str],
        notes: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ReleaseCandidate:
        """Freeze the project's current artifacts into a new candidate.

        Captures every artifact whose ``artifact_type`` is in the required
        set for ``target_phase``. A required type that has no live artifact
        causes the candidate to be created in ``draft`` with a missing-type
        reason recorded by ``evaluate`` — the caller can still see the
        candidate and address the gap rather than getting a hard error.
        """
        required_types = REQUIRED_TYPES_BY_TARGET.get(target_phase)
        if not required_types:
            raise ReleaseError(
                f"Unknown release target_phase '{target_phase}'. Known: "
                f"{sorted(REQUIRED_TYPES_BY_TARGET)}"
            )

        candidate = ReleaseCandidate(
            project_id=project_id,
            workflow_id=workflow_id,
            target_phase=target_phase,
            status="draft",
            created_by=created_by,
            notes=notes,
            candidate_metadata=metadata or {},
        )
        db.add(candidate)
        db.flush()  # populate id for snapshot rows

        live = (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.artifact_type.in_(required_types),
            )
            .all()
        )
        for artifact in live:
            db.add(
                ReleaseArtifactSnapshot(
                    candidate_id=candidate.id,
                    artifact_id=artifact.id,
                    artifact_type=artifact.artifact_type,
                    artifact_subtype=artifact.artifact_subtype,
                    snapshot_content_hash=artifact.content_hash or "",
                    snapshot_version=artifact.version or 1,
                    snapshot_approval_state=artifact.approval_state or "pending_review",
                )
            )

        db.commit()
        db.refresh(candidate)
        logger.info(
            "[Release] candidate=%s target=%s project=%s snapshots=%d",
            candidate.id, target_phase, project_id, len(candidate.snapshots),
        )
        return candidate

    # ── Evaluation ─────────────────────────────────────────────────────────

    @staticmethod
    def evaluate(db: Session, candidate: ReleaseCandidate) -> ExecutableDecision:
        """Decide whether ``candidate`` is safe to execute RIGHT NOW.

        Checks performed (all must pass):

        1. The candidate is in ``draft`` or ``approved`` status (a
           ``rejected``/``executed``/``superseded`` candidate is terminal
           and never re-runs).
        2. Every artifact type required for ``target_phase`` is represented
           by at least one snapshot.
        3. Each live artifact behind a snapshot still exists.
        4. Each live artifact's ``content_hash`` still equals the snapshot
           hash. Drift here is the audit's "edit-after-approval" risk and
           the dominant reason to refuse execution.
        5. Each live artifact's ``approval_state`` is ``approved`` AND the
           live ``approved_content_hash`` matches the snapshot hash (the
           approval is for THIS version, not a stale one).
        """
        reasons: List[str] = []

        if candidate.status in ("rejected", "executed", "superseded"):
            return ExecutableDecision(
                executable=False,
                reasons=[
                    f"Candidate is in terminal status '{candidate.status}' "
                    "and cannot execute. Create a new candidate."
                ],
            )

        required = REQUIRED_TYPES_BY_TARGET.get(candidate.target_phase) or frozenset()
        present_types = {s.artifact_type for s in candidate.snapshots}
        missing = required - present_types
        if missing:
            reasons.append(
                f"Missing required artifact type(s) for {candidate.target_phase}: "
                f"{sorted(missing)}"
            )

        # Re-read live rows in one query so the gate is N+1-free.
        artifact_ids = [s.artifact_id for s in candidate.snapshots]
        live_rows = (
            db.query(Artifact).filter(Artifact.id.in_(artifact_ids)).all()
            if artifact_ids else []
        )
        live_by_id = {a.id: a for a in live_rows}

        for snap in candidate.snapshots:
            live = live_by_id.get(snap.artifact_id)
            label = f"{snap.artifact_type}/{snap.artifact_subtype}"

            if live is None:
                reasons.append(f"{label}: live artifact no longer exists.")
                continue

            if (live.content_hash or "") != snap.snapshot_content_hash:
                reasons.append(
                    f"{label}: content drifted since snapshot "
                    f"(snapshot {snap.snapshot_content_hash[:12]} ≠ "
                    f"live {(live.content_hash or '')[:12]}). Re-snapshot + re-approve."
                )
                continue

            state = (live.approval_state or "").lower()
            if state != "approved":
                reasons.append(f"{label}: not approved (state='{state}').")
                continue

            if (live.approved_content_hash or "") != snap.snapshot_content_hash:
                reasons.append(
                    f"{label}: approval hash does not match snapshot hash — "
                    "approval is stale, re-review required."
                )
                continue

        decision = ExecutableDecision(executable=not reasons, reasons=reasons)
        return decision

    # ── Lifecycle transitions ─────────────────────────────────────────────

    @staticmethod
    def approve(
        db: Session, candidate: ReleaseCandidate,
    ) -> ExecutableDecision:
        """Promote a draft to approved IFF evaluate() passes.

        Returns the decision so the caller (route layer) can surface the
        rejection reasons to the operator without a second query.
        """
        decision = ReleaseService.evaluate(db, candidate)
        if not decision.executable:
            return decision
        candidate.status = "approved"
        candidate.approved_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(candidate)
        logger.info("[Release] APPROVED candidate=%s", candidate.id)
        return decision

    @staticmethod
    def reject(db: Session, candidate: ReleaseCandidate) -> ReleaseCandidate:
        candidate.status = "rejected"
        db.commit()
        db.refresh(candidate)
        logger.info("[Release] REJECTED candidate=%s", candidate.id)
        return candidate

    @staticmethod
    def mark_executed(db: Session, candidate: ReleaseCandidate) -> ReleaseCandidate:
        candidate.status = "executed"
        candidate.executed_at = datetime.now(timezone.utc)
        # Older approved candidates for the same project + target are now
        # historical — flip them to ``superseded`` so the UI surfaces the
        # one that actually ran.
        ReleaseService._mark_others_superseded(db, candidate)
        db.commit()
        db.refresh(candidate)
        logger.info("[Release] EXECUTED candidate=%s", candidate.id)
        return candidate

    @staticmethod
    def _mark_others_superseded(db: Session, executed: ReleaseCandidate) -> None:
        siblings = (
            db.query(ReleaseCandidate)
            .filter(
                ReleaseCandidate.project_id == executed.project_id,
                ReleaseCandidate.target_phase == executed.target_phase,
                ReleaseCandidate.id != executed.id,
                ReleaseCandidate.status.in_(("draft", "approved")),
            )
            .all()
        )
        for sib in siblings:
            sib.status = "superseded"

    # ── Reads ──────────────────────────────────────────────────────────────

    @staticmethod
    def get(db: Session, candidate_id: str) -> Optional[ReleaseCandidate]:
        return (
            db.query(ReleaseCandidate)
            .filter(ReleaseCandidate.id == candidate_id)
            .first()
        )

    @staticmethod
    def list_for_project(
        db: Session, project_id: str, *, limit: int = 50,
    ) -> List[ReleaseCandidate]:
        return (
            db.query(ReleaseCandidate)
            .filter(ReleaseCandidate.project_id == project_id)
            .order_by(ReleaseCandidate.created_at.desc())
            .limit(limit)
            .all()
        )


# ── Enforcement-side helper ────────────────────────────────────────────────


def require_executable_candidate(
    db: Session, candidate: ReleaseCandidate,
) -> ExecutableDecision:
    """Convenience for execution-time gating.

    Mirrors :meth:`ReleaseService.evaluate` but additionally requires that
    the candidate's STATUS is ``approved`` (not just evaluate-passing —
    formally approved by a CLOUD_ARCHITECT). Returns the decision so the
    caller logs / surfaces the reasons; raising belongs at the route layer.
    """
    decision = ReleaseService.evaluate(db, candidate)
    if decision.executable and candidate.status != "approved":
        return ExecutableDecision(
            executable=False,
            reasons=[
                f"Candidate status is '{candidate.status}', not 'approved'. "
                "Run the approval endpoint first."
            ],
        )
    return decision
