"""Project-scoped execution-jobs API.

Endpoints
---------
GET    /api/projects/{project_id}/jobs                 list recent jobs
GET    /api/projects/{project_id}/jobs/{job_id}        get one job
POST   /api/projects/{project_id}/jobs/{job_id}/cancel request cancellation

Authorization
-------------
* Reads (list/get) require any project member (DEVELOPER+/VIEWER).
* Cancel requires DEVELOPER+ — stopping a running build/apply is a
  state-changing action, not a read.

Cross-project safety: every handler verifies ``job.project_id`` matches the
``project_id`` in the path and 404s otherwise, so a job id from another
tenant is never addressable through this project's URL.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.authorization import (
    require_project_contributor,
    require_project_member,
)
from backend.app.core.security import get_current_user, get_db
from backend.app.models.execution_job import ExecutionJob
from backend.app.models.project import ProjectMember
from backend.app.models.user import User
from backend.app.schemas.jobs import JobCancelResponse, JobResponse
from backend.app.services.execution.job_service import JobService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/projects/{project_id}/jobs",
    tags=["Execution Jobs"],
)


def _load_job_or_404(db: Session, project_id: str, job_id: str) -> ExecutionJob:
    """Load a job, enforcing it belongs to the path's project.

    404 (not 403) when the job exists but in another project — same
    non-disclosure rule as the rest of the project-scoped surface.
    """
    job = JobService.get(db, job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("", response_model=list[JobResponse])
def list_jobs(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_member),
):
    return JobService.list_for_project(db, project_id)


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_member),
):
    return _load_job_or_404(db, project_id, job_id)


@router.post("/{job_id}/cancel", response_model=JobCancelResponse)
def cancel_job(
    project_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),
):
    """Request cancellation of a job.

    * A pending job is cancelled immediately (it never runs).
    * A running job is flagged; the worker observes the flag, stops the
      handler, and finalises the job as cancelled. The response returns
      the status AT THE MOMENT OF THE REQUEST ('running' for the flagged
      case) — clients poll GET to observe the eventual 'cancelled'.
    * A terminal job is returned unchanged (idempotent).
    """
    # 404s if the job is in another project — checked BEFORE we touch it.
    _load_job_or_404(db, project_id, job_id)

    new_status = JobService.request_cancel(db, job_id)
    if new_status is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if new_status == "cancelled":
        message = "Job cancelled."
    elif new_status == "running":
        message = "Cancellation requested — worker will stop the job shortly."
    else:
        message = f"Job is already {new_status}; nothing to cancel."

    return JobCancelResponse(id=job_id, status=new_status, message=message)
