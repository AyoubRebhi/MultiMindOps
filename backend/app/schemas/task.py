from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator


class TaskCreate(BaseModel):
    prompt: str
    repo_url: str
    repository_visibility: str = "public"
    github_token: Optional[str] = None


class PlanPreviewRequest(BaseModel):
    prompt: str
    repo_url: str
    repository_visibility: str = "public"
    github_token: Optional[str] = None


class GenerateArtifactsRequest(BaseModel):
    prompt: str
    repo_url: str
    repository_visibility: str = "public"
    github_token: Optional[str] = None
    approved_artifacts: List[str] = []


class ReviewArtifactsRequest(BaseModel):
    reviewed_artifacts: Dict[str, str]
    review_notes: Optional[str] = None


class PlanPreviewResponse(BaseModel):
    task_id: str
    status: str
    requires_user_input: bool = True
    plan: Optional[Any] = None
    cost_estimation: Optional[Any] = None
    repository_security: Optional[Any] = None
    security: Optional[Any] = None
    repo_summary: Optional[Any] = None
    logs: List[Any] = []


class ValidatePlanRequest(BaseModel):
    task_id: str
    decision: Literal["approved", "rejected", "modified"]
    feedback: Optional[str] = None

    @field_validator("feedback")
    @classmethod
    def feedback_required_for_modified(cls, v: Optional[str], info: Any) -> Optional[str]:
        data = info.data if hasattr(info, "data") else {}
        if data.get("decision") == "modified" and not (v or "").strip():
            raise ValueError("feedback is required when decision is 'modified'")
        return v


class ValidatePlanResponse(BaseModel):
    task_id: str
    decision: str
    status: str
    requires_user_input: bool = False
    # Populated on "modified" — the regenerated plan awaiting next validation
    plan: Optional[Any] = None
    cost_estimation: Optional[Any] = None
    logs: List[Any] = []
    # Populated on "approved" — final generation result
    result: Optional[Any] = None
    # Populated on "rejected"
    rejection_reason: Optional[str] = None


class TaskResponse(BaseModel):
    id: str
    prompt: str
    status: str
    plan: Optional[Any] = None
    logs: List[Any] = []
    result: Optional[Any] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
