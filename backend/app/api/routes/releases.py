"""Project-scoped release-candidate routes.

POST   /api/projects/{project_id}/releases                       create candidate
GET    /api/projects/{project_id}/releases                       list
GET    /api/projects/{project_id}/releases/{candidate_id}        get
GET    /api/projects/{project_id}/releases/{candidate_id}/evaluate  re-evaluate
POST   /api/projects/{project_id}/releases/{candidate_id}/approve   approve
POST   /api/projects/{project_id}/releases/{candidate_id}/reject    reject

Authorization
-------------
* Reads (list/get/evaluate): DEVELOPER+ — needed to render the release UI.
* Create candidate: DEVELOPER+ — anyone who can edit artifacts can prepare
  a release for review.
* Approve / reject: CLOUD_ARCHITECT+ (or OWNER/ADMIN). This is the
  governance gate the audit required — only an approver can promote a
  draft to ``approved``, which is the status the future TerraformExecutor
  will check before applying.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.authorization import (
    require_project_approver,
    require_project_contributor,
)
from backend.app.core.security import get_current_user, get_db
from backend.app.models.project import ProjectMember
from backend.app.models.release import ReleaseCandidate
from backend.app.models.user import User
from backend.app.schemas.release import (
    ReleaseCandidateCreateRequest,
    ReleaseCandidateResponse,
    ReleaseEvaluationResponse,
)
from backend.app.services.core.release_service import ReleaseError, ReleaseService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/projects/{project_id}/releases",
    tags=["Releases"],
)


def _load_or_404(db: Session, project_id: str, candidate_id: str) -> ReleaseCandidate:
    candidate = ReleaseService.get(db, candidate_id)
    if candidate is None or candidate.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Release candidate not found",
        )
    return candidate


@router.post(
    "",
    response_model=ReleaseCandidateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_release_candidate(
    project_id: str,
    payload: ReleaseCandidateCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),
):
    try:
        candidate = ReleaseService.create_candidate(
            db,
            project_id=project_id,
            workflow_id=payload.workflow_id,
            target_phase=payload.target_phase,
            created_by=current_user.id,
            notes=payload.notes,
            metadata=payload.metadata,
        )
    except ReleaseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return candidate


@router.get("", response_model=list[ReleaseCandidateResponse])
def list_release_candidates(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),
):
    return ReleaseService.list_for_project(db, project_id)


@router.get(
    "/{candidate_id}",
    response_model=ReleaseCandidateResponse,
)
def get_release_candidate(
    project_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),
):
    return _load_or_404(db, project_id, candidate_id)


@router.get(
    "/{candidate_id}/evaluate",
    response_model=ReleaseEvaluationResponse,
)
def evaluate_release_candidate(
    project_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),
):
    """Re-run the executability check against the LIVE artifact rows.

    Cheap — pure read. The UI calls this to render "OK to approve" vs.
    "drift detected — re-snapshot required" without committing any state.
    """
    candidate = _load_or_404(db, project_id, candidate_id)
    decision = ReleaseService.evaluate(db, candidate)
    return ReleaseEvaluationResponse(
        candidate_id=candidate.id,
        executable=decision.executable,
        reasons=decision.reasons,
    )


@router.post(
    "/{candidate_id}/approve",
    response_model=ReleaseEvaluationResponse,
)
def approve_release_candidate(
    project_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_approver),
):
    """Promote draft → approved IFF every constituent passes the evaluator.

    Returns the evaluation outcome — on failure, the reasons list spells
    out exactly which snapshot drifted / is unapproved, so the operator
    knows what to fix without a second roundtrip.
    """
    candidate = _load_or_404(db, project_id, candidate_id)
    decision = ReleaseService.approve(db, candidate)
    return ReleaseEvaluationResponse(
        candidate_id=candidate.id,
        executable=decision.executable,
        reasons=decision.reasons,
    )


@router.post(
    "/{candidate_id}/reject",
    response_model=ReleaseCandidateResponse,
)
def reject_release_candidate(
    project_id: str,
    candidate_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_approver),
):
    candidate = _load_or_404(db, project_id, candidate_id)
    return ReleaseService.reject(db, candidate)
