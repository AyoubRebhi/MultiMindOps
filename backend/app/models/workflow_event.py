"""Append-only workflow phase event log (Phase 5 — event-sourcing foundation).

Why this exists
---------------
``Workflow.current_phase`` is a mutable string. The audit flagged it: the
ONLY record of "did the apply complete?" is a value that any caller can
overwrite, and there is no audit trail of intermediate transitions. For
real Terraform execution that's unacceptable — we need an unforgeable
history.

A ``WorkflowPhaseEvent`` is an immutable row that records one transition:
"on this date, in this workflow, this phase moved to this status, with this
optional payload (artifact ids, plan hash, error message)". Multiple events
for the same workflow form a strict timeline; the current phase is derived
from the LATEST event, not stored as a separate truth.

Use cases
---------
* Audit ("show me when terraform_apply was approved + executed + completed").
* Replay-correctness ("the workflow is in state X because of events 1..N").
* Drift detection ("Workflow.current_phase says completed but the events
  say the apply never finished" — Phase 5 doesn't reconcile these
  automatically, but the event log makes the discrepancy visible).

Schema
------
Append-only by convention — there is no service method to UPDATE or DELETE
events. The model has no updated_at column for the same reason: a row is
either there or not, never partially changed.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql import func

from backend.app.database.base import Base


_JSON_VARIANT = JSONB().with_variant(JSON(), "sqlite")


class WorkflowPhaseEvent(Base):
    """One immutable transition in a workflow's phase timeline."""

    __tablename__ = "workflow_phase_events"
    __table_args__ = (
        # The hot read: "give me the latest events for this workflow".
        Index("ix_wfe_workflow_created", "workflow_id", "created_at"),
        Index("ix_wfe_project_created",  "project_id",  "created_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String, ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    workflow_id = Column(
        String, ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # The phase the workflow is transitioning to/within. Free-form so a new
    # phase doesn't require a migration; well-known values:
    #   ARCHITECTURE_DECISION | PLAN_SELECTED | DOCKER | TERRAFORM_PLAN |
    #   TERRAFORM_APPLY | TERRAFORM_DESTROY | KUBERNETES | CICD
    phase = Column(String, nullable=False, index=True)

    # Verb describing the transition. Standard set:
    #   started | succeeded | failed | cancelled | awaiting_input |
    #   approved | rejected | superseded
    # Free-form for the same forward-compatibility reason.
    status = Column(String, nullable=False)

    # Optional pointer to the actor that caused the event. NULL for system-
    # initiated events (reaper, scheduled re-evaluation).
    actor_user_id = Column(
        String, ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # One-line human description ("approved by alice") — drives the
    # timeline UI without forcing the frontend to compose strings from
    # phase + status + actor.
    message = Column(Text, nullable=True)

    # Optional structured payload — execution_job_id, release_candidate_id,
    # plan_hash, error class, exit_code, severity tally. Strictly metadata;
    # not a place for secrets (the standard scrub doesn't run here because
    # event payloads are never user-supplied).
    payload = Column(MutableDict.as_mutable(_JSON_VARIANT), nullable=False, default=dict)

    # Immutable timestamp — set at insert, never updated.
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
