"""Pydantic schemas for the release-candidates API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ReleaseSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    artifact_id: str
    artifact_type: str
    artifact_subtype: str
    snapshot_content_hash: str
    snapshot_version: int
    snapshot_approval_state: str
    created_at: datetime


class ReleaseCandidateCreateRequest(BaseModel):
    target_phase: str = Field(
        ...,
        examples=["terraform_apply", "kubernetes_deploy"],
        description=(
            "Which executor will consume this candidate. Drives which "
            "artifact types are required for the candidate to be executable."
        ),
    )
    workflow_id: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class ReleaseCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    workflow_id: Optional[str]
    status: str
    target_phase: str
    notes: Optional[str]
    created_by: Optional[str]
    approved_at: Optional[datetime]
    executed_at: Optional[datetime]
    candidate_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    snapshots: List[ReleaseSnapshotResponse] = Field(default_factory=list)


class ReleaseEvaluationResponse(BaseModel):
    candidate_id: str
    executable: bool
    reasons: List[str]
