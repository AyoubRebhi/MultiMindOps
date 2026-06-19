"""Platform-wide workflow listing API.

A single read-only endpoint powering the Workflows page:

    GET /api/workflows   role-aware list of workflow run summaries

Visibility is enforced server-side by ``WorkflowListingService`` (the frontend
role gating is UX only):

* ``ADMIN``           — every workflow on the platform (monitoring view).
* ``DEVOPS_ENGINEER`` — only the workflows the caller launched.

This is intentionally separate from the project-scoped
``GET /api/projects/{id}/workflows`` (which lists by project membership). Here
the axis is the *caller's* relationship to the run (owner vs. admin), matching
the Workflows-page business rules.

Read endpoints only:

    GET /api/workflows                       role-aware list of summaries
    GET /api/workflows/{id}                  one summary (resume: status + phase)
    GET /api/workflows/{id}/analysis         aggregated Analysis-phase payload

No mutation surface lives here — admins are read-only and engineers execute
phases through the project-scoped router. The Analysis-phase aggregation is
strictly read-only (it never re-runs analysis or calls an LLM).
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.security import get_current_user, get_db
from backend.app.models.user import User
from backend.app.schemas.workflow import WorkflowSummary
from backend.app.schemas.workflow_analysis import WorkflowAnalysisResponse
from backend.app.services.core.workflow_analysis_aggregation_service import (
    WorkflowAnalysisAggregationService,
)
from backend.app.services.core.workflow_listing_service import WorkflowListingService

router = APIRouter(prefix="/api/workflows", tags=["Workflows"])


@router.get("", response_model=List[WorkflowSummary])
def list_workflows(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List workflow summaries visible to the caller.

    ADMIN sees all workflows; a DEVOPS_ENGINEER sees only the workflows they
    started. Read-only — returns lightweight summaries (identity + ownership +
    progress), never phase payloads or artifacts.
    """
    return WorkflowListingService.list_for_user(db, current_user)


@router.get("/{workflow_id}", response_model=WorkflowSummary)
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return one workflow summary so the UI can resume from its saved phase.

    The frontend reads ``status`` + ``current_phase`` to route to the correct
    phase page WITHOUT restarting the workflow or re-running any phase.
    404 when the workflow does not exist or is not visible to the caller (an
    engineer can only open the workflows they launched).
    """
    workflow = WorkflowListingService.get_for_user(db, current_user, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowListingService.summarize(db, workflow)


@router.get("/{workflow_id}/analysis", response_model=WorkflowAnalysisResponse)
def get_workflow_analysis(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Aggregated Analysis-phase payload (the FIVE sections) in ONE response.

    Read-only — assembled from data the bootstrap pipeline already persisted
    (codebase analysis + security + application profile). Never re-runs an
    agent or calls an LLM. 404 when the workflow is not visible to the caller.
    """
    workflow = WorkflowListingService.get_for_user(db, current_user, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowAnalysisAggregationService.build(db, workflow)
