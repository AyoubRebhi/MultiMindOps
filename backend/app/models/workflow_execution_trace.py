"""WorkflowExecutionTrace — append-only observability record per workflow phase.

This is an OBSERVABILITY table, not part of the workflow state model. The
authoritative phase record remains ``Workflow.phases_state``; this table is a
materialised, ordered, queryable trace built FROM that state (``source='live'``)
plus the deterministic replay path (``source='replay'``). Nothing in the
orchestration/state machine reads from it — removing it would not change workflow
behaviour, only observability.

One row per (workflow, phase, source). It records what the spec requires:
phase start/end timestamps, the inputs used, the artifacts produced, and the
failure classification (if any).
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.sql import func

from backend.app.database.base import Base


# JSONB on Postgres, JSON on SQLite (tests). Fresh instance per column — the
# mutable extension keys listeners by the type instance, so sharing one between
# a MutableDict and a MutableList column breaks coercion (see models/workflow.py).
def _json_variant():
    return JSONB().with_variant(JSON(), "sqlite")


class WorkflowExecutionTrace(Base):
    __tablename__ = "workflow_execution_traces"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id = Column(
        String, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(String, nullable=True, index=True)

    # Phase key (matches Workflow.phases_state keys: ANALYSIS, PLAN_SELECTED,
    # TERRAFORM_GENERATION/VALIDATION/PLAN, DOCKER, DOCKER_BUILD, ...).
    phase = Column(String, nullable=False)
    # Mirrors the phase status (completed | failed | running | awaiting_input | ...).
    status = Column(String, nullable=False, default="unknown")
    # 'live'  → materialised from Workflow.phases_state (the real run)
    # 'replay'→ recorded by the deterministic replay path
    source = Column(String, nullable=False, default="live")
    # Ordering hint within the workflow (chronological).
    sequence = Column(Integer, nullable=False, default=0)

    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)

    # Inputs consumed by the phase (artifact ids/hashes, plan_id, image_tag, …).
    inputs = Column(MutableDict.as_mutable(_json_variant()), nullable=False, default=dict)
    # Artifacts produced (list of {type, subtype, version, hash} or ids).
    artifacts_produced = Column(MutableList.as_mutable(_json_variant()), nullable=False, default=list)
    # NETWORK_ERROR | PROVIDER_FETCH_FAILED | VALIDATION_FAILED | None.
    failure_classification = Column(String, nullable=True)
    # Free-form phase detail (the phases_state ``extra`` snapshot, replay notes).
    detail = Column(MutableDict.as_mutable(_json_variant()), nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
