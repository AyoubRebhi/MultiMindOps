from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enumerations exposed to the frontend ────────────────────────────────────

ProjectRole = Literal["OWNER", "DEVELOPER", "CLOUD_ARCHITECT", "ADMIN", "VIEWER"]
ProjectStatus = Literal["draft", "active", "archived", "failed"]
StrategyTier = Literal["minimal", "balanced", "robust"]
ArchitectureType = Literal[
    "monolith", "microservices", "serverless", "static_site", "data_pipeline", "other"
]


# ─── Project ─────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    repository_url: Optional[str] = None
    architecture_type: Optional[ArchitectureType] = None
    application_profile: Optional[str] = None
    default_strategy_tier: StrategyTier = "balanced"


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    repository_url: Optional[str] = None
    architecture_type: Optional[ArchitectureType] = None
    application_profile: Optional[str] = None
    default_strategy_tier: Optional[StrategyTier] = None
    current_status: Optional[ProjectStatus] = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    name: str
    description: Optional[str] = None
    repository_url: Optional[str] = None
    architecture_type: Optional[str] = None
    application_profile: Optional[str] = None
    default_strategy_tier: Optional[str] = None
    current_status: str
    project_metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime


# ─── Workflow ────────────────────────────────────────────────────────────────

class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    started_by: Optional[str] = None
    current_phase: Optional[str] = None
    status: str
    execution_mode: str
    phases_state: Dict[str, Any] = {}
    error_message: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None
    updated_at: datetime


# ─── Artifact ────────────────────────────────────────────────────────────────

class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    workflow_id: Optional[str] = None
    artifact_type: str
    artifact_subtype: str
    content: str
    validation_status: str
    generated_by_agent: Optional[str] = None
    approved_by: Optional[str] = None
    version: int
    artifact_metadata: Dict[str, Any] = {}
    created_at: datetime
    updated_at: datetime


class ArtifactVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_id: str
    version: int
    content: str
    validation_results: Dict[str, Any] = {}
    generated_by: Optional[str] = None
    workflow_id: Optional[str] = None
    created_at: datetime


# ─── Member ──────────────────────────────────────────────────────────────────

class ProjectMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    user_id: str
    role: str
    created_at: datetime


# ─── Aggregated project detail payload ───────────────────────────────────────

class ProjectDetailResponse(ProjectResponse):
    members: List[ProjectMemberResponse] = []
    workflows: List[WorkflowResponse] = []
    artifact_count: int = 0


# ─── Workflow execution requests ─────────────────────────────────────────────

class StartWorkflowRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    # Phase 2 always runs the full architecture-decision path; future phases
    # may set execution_mode to 'phase' or 'replay'.
    execution_mode: Literal["full", "phase", "replay"] = "full"


class SelectPlanRequest(BaseModel):
    plan_id: str = Field(..., min_length=1)


PhaseName = Literal["DOCKER", "TERRAFORM", "KUBERNETES", "CICD"]


class WorkflowStartResponse(BaseModel):
    workflow_id: str
    task_id: str
    project_id: str
    current_phase: str
    status: str
    plan: Any = None
    architecture_decision: Any = None
    logs: List[Any] = []


class WorkflowPhaseRunResponse(BaseModel):
    workflow_id: str
    task_id: str
    current_phase: str
    status: str
    phases_state: Dict[str, Any] = {}
    persisted_artifact_ids: List[str] = []
    logs: List[Any] = []


# ─── Artifact + version detail payloads ──────────────────────────────────────

class ArtifactDetailResponse(ArtifactResponse):
    versions: List["ArtifactVersionResponse"] = []


ArtifactDetailResponse.model_rebuild()
