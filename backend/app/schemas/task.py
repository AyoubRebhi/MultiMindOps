from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


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
    status: str
    plan: Optional[Any] = None
    repository_security: Optional[Any] = None
    repo_summary: Optional[Any] = None
    logs: List[Any] = []


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
