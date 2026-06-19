"""WorkflowListingService — read-only, role-aware workflow summaries.

Powers the platform-wide ``GET /api/workflows`` page. Strictly read-only: it
joins workflow rows to their project + owner and rolls up phase progress; it
never mutates workflow state.

Visibility rule (the single source of truth for the Workflows page):

* ``ADMIN``           → every workflow on the platform (monitoring view).
* anyone else (the    → only workflows the caller personally launched, i.e.
  ``DEVOPS_ENGINEER``)   ``Workflow.started_by == user.id``.

The role read here is the GLOBAL workspace role (``User.role``), NOT the
project-scoped ``ProjectMember.role`` — the business rule is "an engineer sees
the runs they started", independent of project membership.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.schemas.workflow import WorkflowSummary

logger = logging.getLogger(__name__)

# Phase statuses in ``phases_state`` that count as "done". Mirrors the completed
# set used by WorkflowOrchestrationService._enforce_prerequisites so progress
# math here agrees with the engine's own notion of a finished phase.
_COMPLETED_PHASE_STATUSES = {
    "completed",
    "completed_with_fallback",
    "completed_no_files",
}


class WorkflowListingService:
    @staticmethod
    def list_for_user(db: Session, user: User) -> List[WorkflowSummary]:
        """Return role-scoped workflow summaries, newest-updated first.

        ADMIN gets every workflow; everyone else gets only the workflows whose
        ``started_by`` matches their own id.
        """
        is_admin = (getattr(user, "role", "") or "").upper() == "ADMIN"

        # LEFT joins so a workflow still lists even if its project row is gone
        # (shouldn't happen — CASCADE — but defensive) or its owner was deleted
        # (started_by is ON DELETE SET NULL → NULL owner is expected).
        query = (
            db.query(
                Workflow,
                Project.name.label("project_name"),
                User.display_name.label("owner_name"),
                User.email.label("owner_email"),
            )
            .outerjoin(Project, Project.id == Workflow.project_id)
            .outerjoin(User, User.id == Workflow.started_by)
        )

        if not is_admin:
            # DEVOPS_ENGINEER: only the runs they launched.
            query = query.filter(Workflow.started_by == user.id)

        rows = query.order_by(Workflow.updated_at.desc()).all()

        summaries: List[WorkflowSummary] = []
        for workflow, project_name, owner_name, owner_email in rows:
            completed, total = WorkflowListingService._phase_progress(workflow)
            summaries.append(
                WorkflowSummary(
                    id=workflow.id,
                    project_id=workflow.project_id,
                    project_name=project_name,
                    started_by_id=workflow.started_by,
                    # Prefer a display name; fall back to email so the UI never
                    # shows a blank owner for accounts without a display name.
                    started_by_name=(owner_name or owner_email),
                    status=workflow.status,
                    current_phase=workflow.current_phase,
                    completed_phases=completed,
                    total_phases=total,
                    created_at=workflow.created_at,
                    updated_at=workflow.updated_at,
                )
            )

        logger.info(
            "[Workflows] listed %d workflow(s) for user=%s role=%s (admin=%s)",
            len(summaries), user.id, getattr(user, "role", None), is_admin,
        )
        return summaries

    @staticmethod
    def get_for_user(db: Session, user: User, workflow_id: str) -> Optional[Workflow]:
        """Return a single workflow IFF the caller is allowed to see it.

        ADMIN may open any workflow; a DEVOPS_ENGINEER may only open one they
        launched. Returns ``None`` when the workflow does not exist OR is not
        visible to the caller — the route maps both to a 404 so existence is
        never leaked across owners (an engineer can't probe other users' runs).
        """
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if workflow is None:
            return None
        is_admin = (getattr(user, "role", "") or "").upper() == "ADMIN"
        if is_admin or workflow.started_by == user.id:
            return workflow
        return None

    @staticmethod
    def summarize(db: Session, workflow: Workflow) -> WorkflowSummary:
        """Build a single WorkflowSummary (same shape/rules as the list rows)."""
        project = (
            db.query(Project).filter(Project.id == workflow.project_id).first()
        )
        owner = (
            db.query(User).filter(User.id == workflow.started_by).first()
            if workflow.started_by
            else None
        )
        completed, total = WorkflowListingService._phase_progress(workflow)
        return WorkflowSummary(
            id=workflow.id,
            project_id=workflow.project_id,
            project_name=(project.name if project else None),
            started_by_id=workflow.started_by,
            started_by_name=((owner.display_name or owner.email) if owner else None),
            status=workflow.status,
            current_phase=workflow.current_phase,
            completed_phases=completed,
            total_phases=total,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
        )

    @staticmethod
    def _phase_progress(workflow: Workflow) -> tuple[int, int]:
        """Derive (completed_phases, total_phases) from ``phases_state``.

        ``total`` is the number of phases this run has actually recorded
        (touched), not a fixed canonical denominator — a docker-only run that
        never enters the Terraform sub-phases should not report progress out of
        a phantom total. ``completed`` is how many of those touched phases
        reached a completed state.
        """
        phases = workflow.phases_state or {}
        if not isinstance(phases, dict):
            return 0, 0
        total = len(phases)
        completed = sum(
            1
            for entry in phases.values()
            if isinstance(entry, dict)
            and entry.get("status") in _COMPLETED_PHASE_STATUSES
        )
        return completed, total
