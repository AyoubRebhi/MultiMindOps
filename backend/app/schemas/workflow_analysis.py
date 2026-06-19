"""Workflow Analysis phase — aggregated response schema.

Powers the single request the Analysis phase makes:

    GET /api/workflows/{workflow_id}/analysis  ->  WorkflowAnalysisResponse

The Analysis phase is ONE phase with FIVE sections (not five phases). The
frontend makes exactly one call and distributes the result to the five panels:

    customer_portal · code_analysis · architecture_intelligence ·
    infrastructure_recommendations · security_containerization

Every field is assembled READ-ONLY from data the project-bootstrap pipeline
already persisted (``ProjectContext`` digests + the backing task's transformed
security block, via ``ProjectAnalysisService``). Nothing here re-runs an agent
or calls an LLM. All sub-objects are optional/defaulted so a still-analyzing or
genuinely-empty repository renders without throwing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


# ─── Small reusable value objects ─────────────────────────────────────────────

class TechItem(BaseModel):
    name: str
    version: Optional[str] = None


class RepositoryInsight(BaseModel):
    label: str
    value: str
    ok: Optional[bool] = None


class InfraRecommendation(BaseModel):
    service: str
    reason: str = ""


class SecurityFinding(BaseModel):
    severity: str = "low"
    title: str = "Security finding"
    description: str = ""
    category: Optional[str] = None


# ─── Section DTOs ──────────────────────────────────────────────────────────────

class ProjectInfo(BaseModel):
    id: str
    name: str
    repository_url: Optional[str] = None
    branch: Optional[str] = None
    logo_icon: str = "fa-cube"
    brand_icon: bool = False


class CustomerPortalSection(BaseModel):
    """Business-readable project summary (Phase 3). No new AI agent."""

    project_name: Optional[str] = None
    repository_url: Optional[str] = None
    application_purpose: Optional[str] = None
    application_type: Optional[str] = None
    architecture_pattern: Optional[str] = None
    workload_profile: Optional[str] = None
    statefulness: Optional[str] = None
    scalability_level: Optional[str] = None


class CodeAnalysisSection(BaseModel):
    """Detected stack from the existing Analysis Agent outputs (Phase 4)."""

    languages: List[TechItem] = []
    frameworks: List[TechItem] = []
    libraries: List[TechItem] = []
    package_managers: List[str] = []
    build_tools: List[str] = []
    repository_insights: List[RepositoryInsight] = []


class ArchitectureIntelligenceSection(BaseModel):
    """Architecture conclusions reused from existing analysis (Phase 5)."""

    architecture_type: Optional[str] = None
    architecture_pattern: Optional[str] = None
    application_profile: Optional[Dict[str, Any]] = None
    detected_services: List[str] = []
    entry_points: List[str] = []
    deployment_recommendations: List[str] = []
    observations: List[str] = []


class InfrastructureRecommendationsSection(BaseModel):
    """Deterministic cloud building blocks derived from analysis (Phase 6).

    No new AI agent — rule-based mapping of architecture pattern + detected
    stack/services to AWS services.
    """

    aws_services: List[InfraRecommendation] = []
    compute: List[InfraRecommendation] = []
    storage: List[InfraRecommendation] = []
    networking: List[InfraRecommendation] = []
    observability: List[InfraRecommendation] = []


class SecuritySubsection(BaseModel):
    score: Optional[int] = None
    grade: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    counts: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    findings: List[SecurityFinding] = []
    recommendations: List[str] = []


class ContainerizationSubsection(BaseModel):
    docker_suitability: Optional[str] = None
    findings: List[str] = []
    image_strategy: List[str] = []
    notes: Optional[str] = None


class SecurityContainerizationSection(BaseModel):
    """Existing Security Guard results + derived containerization readiness."""

    security: SecuritySubsection = SecuritySubsection()
    containerization: ContainerizationSubsection = ContainerizationSubsection()


# ─── Top-level aggregated response ─────────────────────────────────────────────

WorkflowAnalysisStatus = Literal["RUNNING", "DONE", "FAILED"]


class WorkflowAnalysisResponse(BaseModel):
    # Optional because the same payload is served project-scoped (the
    # /projects/{id}/workflow-analysis projection) where there is no single
    # owning workflow id.
    workflow_id: Optional[str] = None
    project_id: str
    project_info: ProjectInfo
    customer_portal: CustomerPortalSection = CustomerPortalSection()
    code_analysis: CodeAnalysisSection = CodeAnalysisSection()
    architecture_intelligence: ArchitectureIntelligenceSection = ArchitectureIntelligenceSection()
    infrastructure_recommendations: InfrastructureRecommendationsSection = (
        InfrastructureRecommendationsSection()
    )
    security_containerization: SecurityContainerizationSection = SecurityContainerizationSection()
    status: WorkflowAnalysisStatus = "DONE"
    last_updated: Optional[datetime] = None
