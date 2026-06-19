"""Workflow listing schemas.

Response model for the platform-wide ``GET /api/workflows`` surface — a
READ-ONLY, lightweight summary of workflow runs used by the Workflows page.

Visibility is role-aware (enforced in
``backend/app/services/core/workflow_listing_service.py``):

* ``ADMIN``           — sees every workflow on the platform (monitoring view).
* ``DEVOPS_ENGINEER`` — sees only the workflows they personally launched
                        (``Workflow.started_by == current_user.id``).

The shape is deliberately small: identity + ownership + progress, no artifacts
or phase payloads. ``completed_phases`` / ``total_phases`` are derived from the
authoritative ``Workflow.phases_state`` (see the service) so the frontend can
render an honest progress indicator without a fixed, possibly-wrong denominator.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WorkflowSummary(BaseModel):
    id: str
    project_id: str
    # Joined from Project — may be None only if the project row vanished.
    project_name: Optional[str] = None
    # Owner of the run. ``started_by`` is nullable (ON DELETE SET NULL) so a
    # deleted user leaves the id null; the name then falls back to None.
    started_by_id: Optional[str] = None
    started_by_name: Optional[str] = None
    status: str
    current_phase: Optional[str] = None
    # Progress, derived from phases_state: completed = entries in a completed
    # state; total = phases this run has actually touched (recorded).
    completed_phases: int = 0
    total_phases: int = 0
    created_at: datetime
    updated_at: datetime
