"""Editable artifact persistence endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.authorization import (
    require_task_project_contributor,
    require_task_project_member,
)
from backend.app.core.security import get_current_user
from backend.app.database.session import SessionLocal
from backend.app.models.project import ProjectMember
from backend.app.models.task import Task
from backend.app.services.core.artifact_service import ArtifactService
from backend.app.services.core.task_service import TaskService

logger = logging.getLogger(__name__)
# Phase 1 — every artifact-edit endpoint resolves the owning project via
# task_id and runs the role gate. Read (GET) requires any member; PATCH /
# reset / apply-ai-patch require DEVELOPER+.
router = APIRouter(tags=["Artifact Edit"], dependencies=[Depends(get_current_user)])

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


@router.get("/api/tasks/{task_id}/artifacts")
def get_artifacts(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_member),
) -> dict[str, Any]:
    """Return current artifact content, comparison slots, and history."""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    metadata = ArtifactService.get_artifact_metadata(db, task)
    current = {
        key: entry.get("current_content")
        for key, entry in metadata.items()
        if isinstance(entry, dict) and entry.get("current_content")
    }
    artifact_objects = {
        key: {
            "current_content": entry.get("current_content", ""),
            "original_content": entry.get("original_content") or entry.get("generated_content") or "",
            "ai_patched_content": entry.get("ai_patched_content"),
            "version": entry.get("version", 1),
            "user_modified": bool(entry.get("user_modified")),
            "updated_at": entry.get("updated_at") or entry.get("last_modified_at"),
            "last_modified_by": entry.get("last_modified_by", "agent"),
            "checksum": entry.get("checksum"),
        }
        for key, entry in metadata.items()
        if isinstance(entry, dict)
    }

    return {
        "task_id": task_id,
        "artifacts": current,
        "metadata": metadata,
        "history": ArtifactService.get_artifact_history(db, task),
        **artifact_objects,
    }


@router.patch("/api/tasks/{task_id}/artifacts")
def patch_artifacts(
    task_id: str,
    body: PatchArtifactsRequest,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
) -> dict[str, Any]:
    """Persist user-edited artifact content."""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    updates: dict[str, str] = {
        key: value for key, value in body.model_dump().items() if value is not None
    }
    if not updates:
        raise HTTPException(status_code=422, detail="No artifact content provided")

    saved = ArtifactService.save_many_artifacts(db, task, updates, modified_by="user")

    logger.info(
        "[ArtifactEdit] PATCH saved %d artifacts for task=%s: %s",
        len(saved), task_id, list(saved.keys()),
    )
    return {
        "success": True,
        "task_id": task_id,
        "saved": list(saved.keys()),
        "versions": {key: value.get("version") for key, value in saved.items()},
    }


@router.post("/api/tasks/{task_id}/artifacts/reset")
def reset_artifact(
    task_id: str,
    body: ResetArtifactRequest,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
) -> dict[str, Any]:
    """Restore current_content to original_content for one artifact."""
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
        "[ArtifactEdit] Reset artifact=%s for task=%s version=%d",
        body.artifact_type, task_id, result.get("version"),
    )
    return {
        "success": True,
        "task_id": task_id,
        "artifact_type": body.artifact_type,
        "version": result.get("version"),
        "reset_to": "original_content",
    }


@router.post("/api/tasks/{task_id}/artifacts/apply-ai-patch")
def apply_ai_patch(
    task_id: str,
    db: Session = Depends(get_db),
    _gate: tuple[Task, ProjectMember] = Depends(require_task_project_contributor),
) -> dict[str, Any]:
    """Promote stored AI patch previews into current editable artifacts."""
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    saved = ArtifactService.apply_ai_patches(db, task)
    if not saved:
        raise HTTPException(status_code=422, detail="No AI patch proposal is available to apply")

    logger.info("[ArtifactEdit] Applied AI patches for task=%s keys=%s", task_id, list(saved))
    return {
        "success": True,
        "task_id": task_id,
        "saved": list(saved.keys()),
        "versions": {key: value.get("version") for key, value in saved.items()},
    }
