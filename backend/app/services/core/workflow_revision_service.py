"""WorkflowRevisionService — iterative re-design of a completed workflow.

This service makes a workflow *revisable*: an engineer can go back to a phase
that already completed, regenerate it, and have every phase that DEPENDS on its
output marked stale so it is re-run against the new artifacts. It is the engine
side of the "workflow revision" feature (the frontend phase navigator + the
Regenerate button + the dependency warning).

It composes AROUND the existing engine; it does not reimplement phase execution:

* :meth:`regenerate_phase` re-runs ONE completed phase through the unchanged
  :meth:`WorkflowOrchestrationService.run_phase` (which creates the next
  ``ArtifactVersion`` via the content-hash upsert — the previous artifact bytes
  are NEVER deleted, only superseded by a newer version), then marks the
  transitive downstream phases ``invalidated`` and records a revision-history
  entry.
* :meth:`downstream_phases` is the authoritative dependency closure.
* the revision history is stored in the otherwise-unused ``Workflow.logs``
  JSONB column, so there is NO database migration.

Design rules honoured (see the feature spec):

  * No artifact deletion — regeneration appends an ``ArtifactVersion``; the
    superseded version stays in the history table.
  * No database migration — per-phase revision/invalidation metadata lives in
    ``Workflow.phases_state`` (free-form JSONB) and the revision log lives in
    ``Workflow.logs`` (free-form JSONB list).
  * No workflow restart — only the targeted phase is re-run; ``start_workflow``
    is never called.
  * No background jobs — only the INLINE generation phases are regeneratable
    (Docker / Terraform generation / GitHub Actions); the durable
    validate/plan jobs are left to their own re-run buttons.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow

logger = logging.getLogger(__name__)


# Canonical lifecycle order — used to present the downstream closure and the
# phase navigator in a stable, human-readable left-to-right order. Mirrors the
# engine's own progression (see WorkflowOrchestrationService) plus the read-only
# observation tail.
CANONICAL_PHASE_ORDER: List[str] = [
    "ANALYSIS",
    "ARCHITECTURE_DECISION",
    "PLAN_SELECTED",
    "DOCKER",
    "DOCKER_BUILD",
    "TERRAFORM_GENERATION",
    "TERRAFORM_VALIDATION",
    "TERRAFORM_PLAN",
    "GITHUB_ACTIONS_GENERATION",
    "REPOSITORY_INSTALLATION",
    "WORKFLOW_MONITORING",
]
_ORDER_INDEX = {name: i for i, name in enumerate(CANONICAL_PHASE_ORDER)}

# Direct dependency edges: ``phase -> phases that CONSUME its output``. The
# transitive closure of these edges is what gets invalidated when ``phase`` is
# regenerated. Kept in lock-step with the frontend ``PHASE_DEPENDENTS`` map
# (frontend/src/utils/constants.js) and with the engine's prerequisite gate
# (WorkflowOrchestrationService._enforce_prerequisites).
PHASE_DEPENDENTS: Dict[str, List[str]] = {
    "PLAN_SELECTED": ["DOCKER", "TERRAFORM_GENERATION"],
    "DOCKER": ["DOCKER_BUILD", "GITHUB_ACTIONS_GENERATION"],
    "TERRAFORM_GENERATION": [
        "TERRAFORM_VALIDATION",
        "TERRAFORM_PLAN",
        "GITHUB_ACTIONS_GENERATION",
    ],
    "TERRAFORM_VALIDATION": ["TERRAFORM_PLAN"],
    "GITHUB_ACTIONS_GENERATION": ["REPOSITORY_INSTALLATION"],
    "REPOSITORY_INSTALLATION": ["WORKFLOW_MONITORING"],
}

# Phases a user may regenerate through this service. Restricted to the INLINE
# generation phases (no durable background job is spawned) — exactly the phases
# that own a regeneratable artifact. The terraform validate/plan phases re-run
# via their own streamed-job buttons, not here.
REGENERATABLE_PHASES = {
    "DOCKER",
    "TERRAFORM_GENERATION",
    "GITHUB_ACTIONS_GENERATION",
}

# Phase statuses that mean a phase has produced output (so it can be regenerated)
# — mirrors WorkflowOrchestrationService's completed set.
_COMPLETED_PHASE_STATUSES = {
    "completed",
    "completed_with_fallback",
    "completed_no_files",
}
# A phase is regeneratable when it is completed OR was invalidated by an earlier
# upstream revision (re-running it brings it current AND re-invalidates its own
# downstream).
_REVISABLE_FROM_STATUSES = _COMPLETED_PHASE_STATUSES | {"invalidated"}

# Status stamped on a phase whose upstream input was regenerated. It is NOT a
# completed status, so the listing/progress math stops counting it as done and
# the prerequisite gate forces it to be re-run before anything downstream of it.
INVALIDATED_STATUS = "invalidated"

# Artifact types each generation phase OWNS — used to snapshot version numbers
# before/after a regeneration so the revision record can report exactly which
# artifact versions were superseded.
_PHASE_ARTIFACT_TYPES: Dict[str, Tuple[str, ...]] = {
    "DOCKER": ("docker",),
    "TERRAFORM_GENERATION": ("terraform",),
    "GITHUB_ACTIONS_GENERATION": ("github_actions",),
}

# Revision-history entries are tagged with this event key inside Workflow.logs
# so they can be filtered out from any other (future) log usage.
_REVISION_EVENT = "phase_revision"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowRevisionService:
    # ─── Dependency graph ────────────────────────────────────────────────────

    @staticmethod
    def downstream_phases(phase: str) -> List[str]:
        """Transitive closure of phases that depend on ``phase``'s output.

        Breadth-first over :data:`PHASE_DEPENDENTS`, returned in canonical
        lifecycle order. Excludes ``phase`` itself. Deterministic and acyclic
        (the lifecycle is a DAG).
        """
        phase = phase.upper()
        seen: set[str] = set()
        queue = deque(PHASE_DEPENDENTS.get(phase, []))
        while queue:
            nxt = queue.popleft()
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.extend(PHASE_DEPENDENTS.get(nxt, []))
        return sorted(seen, key=lambda n: _ORDER_INDEX.get(n, len(CANONICAL_PHASE_ORDER)))

    @staticmethod
    def impacted_phases(workflow: Workflow, phase: str) -> List[str]:
        """Downstream phases that are ACTUALLY recorded on this run.

        The dependency warning shown before a regeneration should list only the
        phases this workflow has actually reached — a downstream phase that was
        never run has no output to invalidate. Filters
        :meth:`downstream_phases` to those present in ``phases_state`` and not
        already invalidated.
        """
        phases = workflow.phases_state or {}
        out: List[str] = []
        for name in WorkflowRevisionService.downstream_phases(phase):
            entry = phases.get(name)
            if isinstance(entry, dict) and entry.get("status") != INVALIDATED_STATUS:
                out.append(name)
        return out

    # ─── Public entry point ──────────────────────────────────────────────────

    @staticmethod
    def regenerate_phase(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Task,
        phase: str,
        user_id: Optional[str] = None,
    ) -> dict:
        """Regenerate one completed phase and invalidate everything downstream.

        Steps (matching the feature spec's example "Regenerate TERRAFORM"):
          1. snapshot the owned artifact versions (to report what gets superseded),
          2. re-run the phase via the unchanged engine (creates the next
             ``ArtifactVersion`` — e.g. Terraform v2 — without deleting v1),
          3. bump the phase's ``revision`` counter, mark the transitive downstream
             phases ``invalidated`` (e.g. GITHUB_ACTIONS / INSTALLATION /
             MONITORING), point ``current_phase`` back at the regenerated phase,
             and append a revision-history entry.

        Raises ``ValueError`` (→ HTTP 400) when ``phase`` is not regeneratable or
        has not produced output yet. Returns a summary dict for the API layer.
        """
        # Imported lazily to avoid any import-time coupling with the engine that
        # this service composes around.
        from backend.app.services.core.workflow_orchestration_service import (
            WorkflowOrchestrationService,
        )

        phase = phase.upper()
        if phase not in REGENERATABLE_PHASES:
            raise ValueError(
                f"Phase '{phase}' cannot be regenerated. Regeneratable phases: "
                + ", ".join(sorted(REGENERATABLE_PHASES))
                + "."
            )

        prior_entry = (workflow.phases_state or {}).get(phase) or {}
        prior_status = prior_entry.get("status")
        if prior_status not in _REVISABLE_FROM_STATUSES:
            raise ValueError(
                f"Cannot regenerate {phase}: it has not completed yet "
                f"(current status: {prior_status or 'not started'})."
            )

        before = WorkflowRevisionService._snapshot_phase_artifacts(db, project.id, phase)

        # Re-run the phase through the canonical engine. This commits the new
        # artifact version + the refreshed phase record (status reset to its
        # completed verdict, clearing any prior `invalidated` marker).
        state, persisted_ids = WorkflowOrchestrationService.run_phase(
            db, project=project, workflow=workflow, task=task, phase=phase,
        )
        db.refresh(workflow)

        run_status = ((workflow.phases_state or {}).get(phase) or {}).get("status")
        if run_status not in _COMPLETED_PHASE_STATUSES:
            # The regeneration did not produce a fresh, usable output (e.g. a
            # GitHub Actions validation failure). Do NOT bump the revision or
            # invalidate downstream — the previous output is still the current
            # artifact. Surface the run result so the UI can show the error.
            logger.info(
                "[WorkflowRevision] regenerate %s for workflow=%s did not complete "
                "(status=%s) — no downstream invalidation",
                phase, workflow.id, run_status,
            )
            return {
                "workflow_id": workflow.id,
                "task_id": task.id,
                "phase": phase,
                "revised": False,
                "revision": int(prior_entry.get("revision") or 1),
                "current_phase": workflow.current_phase or phase,
                "status": workflow.status,
                "phases_state": dict(workflow.phases_state or {}),
                "invalidated_phases": [],
                "superseded_artifacts": {},
                "persisted_artifact_ids": list(persisted_ids),
                "logs": state.get("logs", []),
            }

        after = WorkflowRevisionService._snapshot_phase_artifacts(db, project.id, phase)
        superseded = WorkflowRevisionService._diff_versions(before, after)

        revision = WorkflowRevisionService._apply_revision(
            workflow,
            phase=phase,
            prior_revision=int(prior_entry.get("revision") or 1),
            superseded=superseded,
            user_id=user_id,
        )
        invalidated = revision["invalidated_phases"]

        db.commit()
        db.refresh(workflow)

        logger.info(
            "[WorkflowRevision] regenerated %s → revision %d for workflow=%s; "
            "invalidated downstream=%s superseded=%s",
            phase, revision["revision"], workflow.id, invalidated,
            list(superseded.keys()),
        )
        return {
            "workflow_id": workflow.id,
            "task_id": task.id,
            "phase": phase,
            "revised": True,
            "revision": revision["revision"],
            "current_phase": workflow.current_phase or phase,
            "status": workflow.status,
            "phases_state": dict(workflow.phases_state or {}),
            "invalidated_phases": invalidated,
            "superseded_artifacts": superseded,
            "persisted_artifact_ids": list(persisted_ids),
            "logs": state.get("logs", []),
        }

    # ─── State mutation (pure, testable without the engine) ──────────────────

    @staticmethod
    def _apply_revision(
        workflow: Workflow,
        *,
        phase: str,
        prior_revision: int,
        superseded: Dict[str, dict],
        user_id: Optional[str],
    ) -> dict:
        """Stamp the new revision, invalidate downstream, record the history.

        Does NOT commit — the caller owns the transaction. Reassigns
        ``phases_state`` / ``logs`` wholesale so the SQLAlchemy mutable-JSON
        tracking fires (nested in-place mutation would not be detected).
        """
        new_revision = prior_revision + 1
        now = _utcnow_iso()

        # 1. Stamp the regenerated phase with its new revision and clear any
        #    invalidation markers it may have carried (it is now current).
        phases = dict(workflow.phases_state or {})
        entry = dict(phases.get(phase) or {})
        entry["revision"] = new_revision
        entry["last_revised_at"] = now
        entry["last_revised_by"] = user_id
        for stale in ("previous_status", "invalidated_by", "invalidated_at", "invalidation_reason"):
            entry.pop(stale, None)
        phases[phase] = entry
        workflow.phases_state = phases

        # 2. Invalidate the transitive downstream phases.
        invalidated = WorkflowRevisionService._invalidate_downstream(
            workflow, phase, user_id=user_id, at=now,
        )

        # 3. The regenerated phase is the active one again; if anything
        #    downstream was invalidated the run is no longer terminal.
        workflow.current_phase = phase
        if invalidated:
            workflow.status = "running"
            workflow.finished_at = None

        # 4. Append the revision-history entry (in Workflow.logs — no migration).
        WorkflowRevisionService._record_revision(
            workflow,
            phase=phase,
            revision=new_revision,
            invalidated=invalidated,
            superseded=superseded,
            user_id=user_id,
            at=now,
        )
        return {"revision": new_revision, "invalidated_phases": invalidated}

    @staticmethod
    def _invalidate_downstream(
        workflow: Workflow,
        phase: str,
        *,
        user_id: Optional[str],
        at: Optional[str] = None,
    ) -> List[str]:
        """Mark every recorded downstream phase ``invalidated``.

        Preserves the pre-invalidation status in ``previous_status`` so the UI
        can show "was completed → now stale". Idempotent: a phase already
        invalidated is left untouched (its original ``previous_status`` and
        ``invalidated_by`` are not overwritten). Returns the phases it changed,
        in canonical order.
        """
        at = at or _utcnow_iso()
        phases = dict(workflow.phases_state or {})
        changed: List[str] = []
        for name in WorkflowRevisionService.downstream_phases(phase):
            entry = phases.get(name)
            if not isinstance(entry, dict):
                continue
            if entry.get("status") == INVALIDATED_STATUS:
                continue
            new_entry = dict(entry)
            new_entry["previous_status"] = entry.get("status")
            new_entry["status"] = INVALIDATED_STATUS
            new_entry["invalidated_by"] = phase
            new_entry["invalidated_at"] = at
            new_entry["invalidation_reason"] = (
                f"Upstream phase {phase} was regenerated; this output is stale "
                "and must be re-run."
            )
            phases[name] = new_entry
            changed.append(name)
        if changed:
            workflow.phases_state = phases
        return changed

    # ─── Revision history (stored in Workflow.logs) ──────────────────────────

    @staticmethod
    def _record_revision(
        workflow: Workflow,
        *,
        phase: str,
        revision: int,
        invalidated: List[str],
        superseded: Dict[str, dict],
        user_id: Optional[str],
        at: Optional[str] = None,
    ) -> dict:
        """Append one immutable revision-history entry to ``Workflow.logs``."""
        record = {
            "event": _REVISION_EVENT,
            "phase": phase,
            "revision": revision,
            "invalidated_phases": list(invalidated),
            "superseded_artifacts": dict(superseded),
            "revised_by": user_id,
            "revised_at": at or _utcnow_iso(),
        }
        workflow.logs = list(workflow.logs or []) + [record]
        return record

    @staticmethod
    def get_revision_history(workflow: Workflow) -> List[dict]:
        """Return the revision-history entries, newest first."""
        entries = [
            e
            for e in (workflow.logs or [])
            if isinstance(e, dict) and e.get("event") == _REVISION_EVENT
        ]
        return list(reversed(entries))

    @staticmethod
    def build_history_payload(workflow: Workflow) -> dict:
        """Assemble the ``GET .../revisions`` response shape."""
        return {
            "workflow_id": workflow.id,
            "current_phase": workflow.current_phase,
            "status": workflow.status,
            "revisions": WorkflowRevisionService.get_revision_history(workflow),
        }

    # ─── Artifact version snapshots ──────────────────────────────────────────

    @staticmethod
    def _snapshot_phase_artifacts(
        db: Session, project_id: str, phase: str,
    ) -> Dict[str, int]:
        """Map ``"{type}/{subtype}" -> current version`` for a phase's artifacts."""
        types = _PHASE_ARTIFACT_TYPES.get(phase, ())
        if not types:
            return {}
        rows = (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.artifact_type.in_(types),
            )
            .all()
        )
        return {
            f"{r.artifact_type}/{r.artifact_subtype}": int(r.version or 1)
            for r in rows
        }

    @staticmethod
    def _diff_versions(
        before: Dict[str, int], after: Dict[str, int],
    ) -> Dict[str, dict]:
        """Return artifacts whose version increased (the superseded ones).

        ``{ "terraform/terraform_main": {"from": 1, "to": 2}, ... }``. Only keys
        present before with a higher version after are included — a brand-new
        artifact has nothing to supersede, and an unchanged one (content-hash
        no-op upsert) keeps its version and is omitted.
        """
        superseded: Dict[str, dict] = {}
        for key, new_version in after.items():
            old_version = before.get(key)
            if old_version is not None and new_version > old_version:
                superseded[key] = {"from": old_version, "to": new_version}
        return superseded
