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
RepositoryVisibility = Literal["public", "private"]

# AI bootstrap state machine — kept synchronized with Project.bootstrap_status
# and ProjectBootstrapService transitions. See backend/app/services/core/
# project_bootstrap_service.py.
ProjectBootstrapStatus = Literal[
    "pending",
    "analyzing",
    "context_building",
    "ready",
    "failed",
]


# ─── Project ─────────────────────────────────────────────────────────────────
#
# The architecture_type / application_profile / default_strategy_tier fields
# are RETAINED on the API surface for backwards compatibility but the new UX
# does not expose them in the New Project form — the AI bootstrap infers them
# from repository analysis. Callers that omit them get nulls and the AI fills
# them in later.

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    repository_url: Optional[str] = None
    repository_visibility: Optional[RepositoryVisibility] = "public"
    # GitHub PAT for cloning a PRIVATE repository. WRITE-ONLY: it is consumed
    # by the create handler (encrypted into ``project_credentials`` via
    # CredentialsService before bootstrap runs) and is NEVER stored on the
    # Project row nor echoed back in any response. ``ProjectResponse`` has no
    # corresponding field, so it cannot leak. Required by the frontend only
    # when ``repository_visibility == "private"``; validated there.
    github_token: Optional[str] = Field(default=None, repr=False)
    # Legacy classifiers — optional; left in so existing API clients keep
    # working. The bootstrap pipeline writes these post-analysis when the AI
    # can infer them.
    architecture_type: Optional[ArchitectureType] = None
    application_profile: Optional[str] = None
    default_strategy_tier: Optional[StrategyTier] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    repository_url: Optional[str] = None
    repository_visibility: Optional[RepositoryVisibility] = None
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
    repository_visibility: Optional[str] = None
    architecture_type: Optional[str] = None
    application_profile: Optional[str] = None
    default_strategy_tier: Optional[str] = None
    current_status: str
    bootstrap_status: str = "pending"
    bootstrap_error: Optional[str] = None
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
    approval_state: str = "pending_review"
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


# ─── Project settings (repository + credential status) ───────────────────────
#
# The settings aggregator pairs the repository fields a user edits with a
# DECRYPT-FREE view of which DevOps credentials are configured. No secret value
# is ever included — only ``configured`` flags + non-secret AWS display
# metadata (region / account / access-key-id last-4).


class ProviderConfigured(BaseModel):
    """Minimal connected/missing flag for a provider with no extra metadata."""

    configured: bool


class ProjectCredentialStatus(BaseModel):
    github: ProviderConfigured
    aws: "AwsCredentialStatus"


class ProjectSettingsResponse(BaseModel):
    repository_url: Optional[str] = None
    repository_visibility: Optional[str] = None
    default_branch: Optional[str] = None
    credentials: ProjectCredentialStatus


class ProjectSettingsUpdateRequest(BaseModel):
    """Partial update of the project's repository settings.

    Only repository fields are here — credentials are written through the
    dedicated ``/credentials/github`` and ``/credentials/aws`` endpoints
    (stricter authz). ``default_branch`` is persisted into ``project_metadata``.
    """

    repository_url: Optional[str] = Field(default=None, max_length=2048)
    repository_visibility: Optional[RepositoryVisibility] = None
    default_branch: Optional[str] = Field(default=None, max_length=255)


# Imported at the bottom to avoid a circular import at module load: the
# credentials schema is independent and only referenced by the settings models
# above. ``model_rebuild`` resolves the forward reference once it is in scope.
from backend.app.schemas.credentials import AwsCredentialStatus  # noqa: E402

ProjectCredentialStatus.model_rebuild()


# ─── Workflow execution requests ─────────────────────────────────────────────

class StartWorkflowRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    # Phase 2 always runs the full architecture-decision path; future phases
    # may set execution_mode to 'phase' or 'replay'.
    execution_mode: Literal["full", "phase", "replay"] = "full"


class SelectPlanRequest(BaseModel):
    plan_id: str = Field(..., min_length=1)


# Canonical workflow phases. The standalone LLM-only "TERRAFORM" phase was
# collapsed into the unified TERRAFORM_GENERATION (LLM → DB → rehydrate →
# validate → plan). CI/CD and KUBERNETES are deactivated — not part of the
# supported workflow (ANALYSIS → INFRASTRUCTURE → DOCKER).
PhaseName = Literal[
    "TERRAFORM_GENERATION",
    "TERRAFORM_VALIDATION",
    "TERRAFORM_PLAN",
    "DOCKER",
    "GITHUB_ACTIONS_GENERATION",
    "REPOSITORY_INSTALLATION",
]


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


# ─── Workflow revision (regenerate a phase + invalidate downstream) ──────────
#
# Regenerating a completed phase re-runs it (creating the next ArtifactVersion —
# the previous bytes are preserved, never deleted), marks every phase that
# DEPENDS on its output ``invalidated`` so it is re-run against the new
# artifacts, and records a revision-history entry. No DB migration: per-phase
# revision/invalidation metadata lives in ``Workflow.phases_state`` and the
# revision log lives in ``Workflow.logs`` (both free-form JSONB).


class RegeneratePhaseResponse(BaseModel):
    workflow_id: str
    task_id: str
    phase: str
    # ``revised`` is False when the re-run did not produce a fresh, usable output
    # (e.g. a validation failure) — in that case nothing downstream is touched.
    revised: bool
    revision: int
    current_phase: str
    status: str
    phases_state: Dict[str, Any] = {}
    # Downstream phases marked stale by this regeneration (canonical order).
    invalidated_phases: List[str] = []
    # ``"{type}/{subtype}": {"from": v, "to": v+1}`` for each superseded artifact.
    superseded_artifacts: Dict[str, Any] = {}
    persisted_artifact_ids: List[str] = []
    logs: List[Any] = []


class WorkflowRevisionEntry(BaseModel):
    phase: str
    revision: int
    invalidated_phases: List[str] = []
    superseded_artifacts: Dict[str, Any] = {}
    revised_by: Optional[str] = None
    revised_at: Optional[str] = None


class WorkflowRevisionHistoryResponse(BaseModel):
    workflow_id: str
    current_phase: Optional[str] = None
    status: str
    # Newest revision first.
    revisions: List[WorkflowRevisionEntry] = []


# ─── Artifact + version detail payloads ──────────────────────────────────────

class ArtifactDetailResponse(ArtifactResponse):
    versions: List["ArtifactVersionResponse"] = []
    approvals: List["ArtifactApprovalResponse"] = []


# ─── ProjectContext ──────────────────────────────────────────────────────────

class ProjectContextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    context_type: str
    content: Dict[str, Any] = {}
    generated_by: Optional[str] = None
    embedding_reference: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ─── Artifact approval workflow ──────────────────────────────────────────────

ApprovalAction = Literal["approve", "reject", "request_changes"]
ApprovalState  = Literal["pending_review", "approved", "rejected", "requires_changes"]


class ArtifactApprovalCreate(BaseModel):
    action: ApprovalAction
    comment: Optional[str] = Field(None, max_length=4000)


class ArtifactApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    artifact_id: str
    approved_by: str
    action: str
    comment: Optional[str] = None
    created_at: datetime


# ─── Membership management ───────────────────────────────────────────────────

class ProjectMemberCreate(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: ProjectRole = "DEVELOPER"


class ProjectMemberUpdate(BaseModel):
    role: ProjectRole


# ─── Consolidated analysis + security results ────────────────────────────────
#
# Read-only payload assembled by ProjectAnalysisService from data the bootstrap
# pipeline already persisted (ProjectContext digests + the backing task's
# transformed security block). Powers the Analysis + Security tabs on the
# project detail page. NEVER carries any credential material.

SecuritySeverity = Literal["critical", "high", "medium", "low"]


class ProjectSecurityFinding(BaseModel):
    severity: str
    title: str
    description: str = ""
    recommendation: Optional[str] = None
    category: Optional[str] = None
    file: Optional[str] = None


class ProjectSecurityResult(BaseModel):
    score: Optional[int] = None
    grade: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    counts: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    findings: List[ProjectSecurityFinding] = []
    recommendations: List[str] = []


class ApplicationProfileResponse(BaseModel):
    """Structured application profile inferred by ``ApplicationProfilerService``.

    Mirrors the dict that service produces (heuristic + optional LLM refinement)
    and that the bootstrap pipeline persists into the ``repository_summary``
    project-context digest. Every field is optional so a partially-filled or
    legacy profile still validates.
    """

    application_type: Optional[str] = None
    architecture_pattern: Optional[str] = None
    workload_profile: Optional[str] = None
    statefulness: Optional[str] = None
    scalability_level: Optional[str] = None
    entrypoints: List[str] = []
    detected_services: List[str] = []


class ProjectAnalysisStats(BaseModel):
    project_type: Optional[str] = None
    service_count: Optional[int] = None
    lines_of_code: Optional[int] = None
    has_dockerfile: Optional[bool] = None
    has_compose: Optional[bool] = None
    has_ci: Optional[bool] = None
    build_systems: List[str] = []
    devops_tools: List[str] = []
    application_profile: Optional[ApplicationProfileResponse] = None


class ProjectAnalysisResponse(BaseModel):
    project_id: str
    bootstrap_status: str
    bootstrap_error: Optional[str] = None
    analysis_available: bool = False
    language: Optional[str] = None
    languages: List[str] = []
    framework: Optional[str] = None
    frameworks: List[str] = []
    runtime: Optional[str] = None
    dependencies: List[str] = []
    services: List[Dict[str, Any]] = []
    stats: ProjectAnalysisStats = ProjectAnalysisStats()
    security: Optional[ProjectSecurityResult] = None


ArtifactDetailResponse.model_rebuild()
