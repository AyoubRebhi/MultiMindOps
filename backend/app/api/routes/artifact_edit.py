"""
Editable artifact persistence endpoints.

GET  /api/tasks/{task_id}/artifacts          — fetch current artifacts + metadata
PATCH /api/tasks/{task_id}/artifacts         — persist user-edited content
POST /api/tasks/{task_id}/artifacts/reset    — reset one artifact to generated content
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.database.session import SessionLocal
from backend.app.services.core.artifact_service import ArtifactService
from backend.app.services.core.task_service import TaskService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Artifact Edit"])

# Canonical path — keep in sync with frontend artifactsRoute()
ARTIFACTS_BASE_ROUTE = "/api/tasks/{task_id}/artifacts"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class PatchArtifactsRequest(BaseModel):
    dockerfile: str | None = None
    dockerignore: str | None = None
    docker_compose: str | None = None
    env_example: str | None = None


class ResetArtifactRequest(BaseModel):
    artifact_type: str


# ── GET /api/tasks/{task_id}/artifacts ───────────────────────────────────────

@router.get("/api/tasks/{task_id}/artifacts")
def get_artifacts(
    task_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return current artifact content and per-artifact metadata (version, timestamps)."""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    current = ArtifactService.get_all_current_artifacts(db, task)
    metadata = ArtifactService.get_artifact_metadata(db, task)

    return {
        "task_id": task_id,
        "artifacts": current,
        "metadata": metadata,
    }


# ── PATCH /api/tasks/{task_id}/artifacts ─────────────────────────────────────

@router.patch("/api/tasks/{task_id}/artifacts")
def patch_artifacts(
    task_id: str,
    body: PatchArtifactsRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Persist user-edited artifact content.

    Only provided fields are updated — omitted fields are left unchanged.
    Each saved artifact gets its version incremented and last_modified_by = "user".
    """
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates: dict[str, str] = {
        k: v for k, v in body.model_dump().items() if v is not None
    }
    if not updates:
        raise HTTPException(status_code=422, detail="No artifact content provided")

    saved = ArtifactService.save_many_artifacts(db, task, updates, modified_by="user")

    logger.info(
        "[ArtifactEdit] PATCH saved %d artifacts for task=%s: %s",
        len(saved), task_id, list(saved.keys()),
    )
    return {
        "task_id": task_id,
        "saved": list(saved.keys()),
        "versions": {k: v.get("version") for k, v in saved.items()},
    }


# ── POST /api/tasks/{task_id}/artifacts/reset ────────────────────────────────

@router.post("/api/tasks/{task_id}/artifacts/reset")
def reset_artifact(
    task_id: str,
    body: ResetArtifactRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Restore current_content to the immutable generated_content for one artifact."""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    result = ArtifactService.reset_artifact(db, task, body.artifact_type)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Artifact '{body.artifact_type}' not found in editable layer",
        )

    logger.info(
        "[ArtifactEdit] Reset artifact=%s for task=%s → version=%d",
        body.artifact_type, task_id, result.get("version"),
    )
    return {
        "task_id": task_id,
        "artifact_type": body.artifact_type,
        "version": result.get("version"),
        "reset_to": "generated_content",
    }
