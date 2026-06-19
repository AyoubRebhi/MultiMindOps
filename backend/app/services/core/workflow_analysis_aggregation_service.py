"""WorkflowAnalysisAggregationService.

Read-only assembler for the Analysis phase. Resolves a workflow → its project,
then composes the FIVE Analysis-phase sections from data the project-bootstrap
pipeline already persisted — it NEVER re-runs an agent, calls an LLM, or mutates
state.

Data sources (all existing):
  * ``ProjectAnalysisService.build_payload`` — codebase analysis + security +
    application profile (from ``ProjectContext`` digests and the backing task's
    transformed security block).
  * ``Project`` row — name, repository URL, description.
  * ``InfraRecommendationService`` — deterministic AWS recommendation rules.

The five sections map 1:1 to the frontend panels:
  customer_portal · code_analysis · architecture_intelligence ·
  infrastructure_recommendations · security_containerization
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.workflow import Workflow
from backend.app.schemas.workflow_analysis import (
    ArchitectureIntelligenceSection,
    CodeAnalysisSection,
    ContainerizationSubsection,
    CustomerPortalSection,
    InfraRecommendation,
    InfrastructureRecommendationsSection,
    ProjectInfo,
    RepositoryInsight,
    SecurityContainerizationSection,
    SecurityFinding,
    SecuritySubsection,
    TechItem,
    WorkflowAnalysisResponse,
)
from backend.app.services.core.infra_recommendation_service import (
    InfraRecommendationService,
)
from backend.app.services.core.project_analysis_service import ProjectAnalysisService

logger = logging.getLogger(__name__)

# Primary language → Font Awesome brand icon for the project header.
_LANGUAGE_ICONS: Dict[str, tuple[str, bool]] = {
    "python": ("fa-python", True),
    "javascript": ("fa-js", True),
    "typescript": ("fa-js", True),
    "java": ("fa-java", True),
    "go": ("fa-golang", True),
    "golang": ("fa-golang", True),
    "php": ("fa-php", True),
    "ruby": ("fa-gem", False),
    "rust": ("fa-rust", True),
    "node": ("fa-node-js", True),
}

# Image-strategy hint per primary language (deterministic, reuses analysis only).
_IMAGE_STRATEGY: Dict[str, List[str]] = {
    "python": [
        "Multi-stage build on python:3.x-slim",
        "Install dependencies in a builder stage, copy only the venv",
    ],
    "javascript": [
        "node:20-alpine runtime image",
        "Build with a builder stage; ship only production node_modules",
    ],
    "typescript": [
        "node:20-alpine runtime after a TypeScript build stage",
        "Compile in the builder; copy only dist/ + production deps",
    ],
    "java": [
        "Multi-stage build: Maven/Gradle builder → eclipse-temurin JRE runtime",
        "Run the fat JAR on a slim JRE base image",
    ],
    "go": [
        "Static binary built in golang:alpine, shipped on a distroless/scratch base",
        "No runtime dependencies — minimal final image",
    ],
}


class WorkflowAnalysisAggregationService:
    """Build the aggregated Analysis-phase payload for a workflow (read-only)."""

    @staticmethod
    def build(db: Session, workflow: Workflow) -> WorkflowAnalysisResponse:
        """Workflow-scoped entry point — resolve the project and delegate.

        Both the workflow-scoped (``/workflows/{id}/analysis``) and the
        project-scoped (``/projects/{id}/workflow-analysis``) surfaces funnel
        into :meth:`build_for_project`, so they read the EXACT same persisted
        analysis source (``ProjectAnalysisService.build_payload``).
        """
        project: Optional[Project] = workflow.project
        if project is None:
            project = db.query(Project).filter(Project.id == workflow.project_id).first()

        # No project → degrade to an empty (but valid) RUNNING shell rather than
        # raising; the caller already verified the workflow exists + is visible.
        if project is None:
            return WorkflowAnalysisResponse(
                workflow_id=workflow.id,
                project_id=workflow.project_id,
                project_info=ProjectInfo(id=workflow.project_id, name="Unknown project"),
                status="RUNNING",
                last_updated=workflow.updated_at,
            )

        return WorkflowAnalysisAggregationService.build_for_project(
            db,
            project,
            workflow_id=workflow.id,
            last_updated=workflow.updated_at or project.updated_at,
        )

    @staticmethod
    def build_for_project(
        db: Session,
        project: Project,
        *,
        workflow_id: Optional[str] = None,
        last_updated=None,
    ) -> WorkflowAnalysisResponse:
        """Project-scoped builder — the single source of the 5-section payload.

        This is a READ-ONLY projection of the SAME data the Project Details page
        reads (``ProjectAnalysisService.build_payload``): codebase analysis +
        security + application profile that the bootstrap pipeline already
        persisted. It never re-runs analysis, calls an LLM, or writes records.
        """
        payload = ProjectAnalysisService.build_payload(db, project)
        stats: Dict[str, Any] = payload.get("stats") or {}
        profile: Dict[str, Any] = stats.get("application_profile") or {}

        languages: List[str] = payload.get("languages") or []
        frameworks: List[str] = payload.get("frameworks") or []
        dependencies: List[str] = payload.get("dependencies") or []
        build_systems: List[str] = stats.get("build_systems") or []
        services_raw: List[Any] = payload.get("services") or []
        detected_services: List[str] = WorkflowAnalysisAggregationService._service_names(
            services_raw, profile,
        )

        infra = InfraRecommendationService.recommend(
            architecture_pattern=profile.get("architecture_pattern") or project.architecture_type,
            application_type=profile.get("application_type") or project.application_profile,
            languages=languages,
            frameworks=frameworks,
            services=services_raw,
            dependencies=dependencies + build_systems,
        )

        return WorkflowAnalysisResponse(
            workflow_id=workflow_id,
            project_id=project.id,
            project_info=WorkflowAnalysisAggregationService._project_info(project, payload),
            customer_portal=WorkflowAnalysisAggregationService._customer_portal(
                project, payload, profile, frameworks, languages,
            ),
            code_analysis=WorkflowAnalysisAggregationService._code_analysis(
                payload, stats, languages, frameworks, dependencies, build_systems,
            ),
            architecture_intelligence=WorkflowAnalysisAggregationService._architecture(
                project, profile, detected_services, infra,
            ),
            infrastructure_recommendations=WorkflowAnalysisAggregationService._infrastructure(infra),
            security_containerization=WorkflowAnalysisAggregationService._security_containerization(
                payload, stats, languages,
            ),
            status=WorkflowAnalysisAggregationService._status(project, payload),
            last_updated=last_updated or project.updated_at,
        )

    # ── Section 1 — Customer Portal ──────────────────────────────────────────

    @staticmethod
    def _customer_portal(
        project: Project,
        payload: Dict[str, Any],
        profile: Dict[str, Any],
        frameworks: List[str],
        languages: List[str],
    ) -> CustomerPortalSection:
        app_type = profile.get("application_type") or project.application_profile
        headline = project.description
        if not headline:
            tech = (frameworks[0] if frameworks else None) or (languages[0] if languages else None)
            base = (app_type or "application").replace("_", " ")
            headline = f"A {base}" + (f" built with {tech}." if tech else ".")
        return CustomerPortalSection(
            project_name=project.name,
            repository_url=project.repository_url,
            application_purpose=headline,
            application_type=app_type,
            architecture_pattern=profile.get("architecture_pattern") or project.architecture_type,
            workload_profile=profile.get("workload_profile"),
            statefulness=profile.get("statefulness"),
            scalability_level=profile.get("scalability_level"),
        )

    # ── Section 2 — Code Analysis ────────────────────────────────────────────

    @staticmethod
    def _code_analysis(
        payload: Dict[str, Any],
        stats: Dict[str, Any],
        languages: List[str],
        frameworks: List[str],
        dependencies: List[str],
        build_systems: List[str],
    ) -> CodeAnalysisSection:
        package_managers = build_systems or dependencies
        return CodeAnalysisSection(
            languages=[TechItem(name=str(x)) for x in languages],
            frameworks=[TechItem(name=str(x)) for x in frameworks],
            libraries=[],
            package_managers=[str(x) for x in package_managers],
            build_tools=[str(x) for x in (stats.get("devops_tools") or [])],
            repository_insights=WorkflowAnalysisAggregationService._insights(stats),
        )

    @staticmethod
    def _insights(stats: Dict[str, Any]) -> List[RepositoryInsight]:
        out: List[RepositoryInsight] = []
        if stats.get("project_type"):
            out.append(RepositoryInsight(label="Project Type", value=str(stats["project_type"])))
        if stats.get("service_count") is not None:
            out.append(RepositoryInsight(label="Services", value=str(stats["service_count"])))
        if stats.get("lines_of_code") is not None:
            out.append(RepositoryInsight(label="Lines of Code", value=f"{stats['lines_of_code']:,}"))
        if stats.get("has_dockerfile") is not None:
            ok = bool(stats["has_dockerfile"])
            out.append(RepositoryInsight(label="Dockerfile", value="Present" if ok else "Absent", ok=ok))
        if stats.get("has_compose") is not None:
            ok = bool(stats["has_compose"])
            out.append(RepositoryInsight(label="Compose", value="Present" if ok else "Absent", ok=ok))
        if stats.get("has_ci") is not None:
            ok = bool(stats["has_ci"])
            out.append(RepositoryInsight(label="CI/CD", value="Configured" if ok else "None", ok=ok))
        return out

    # ── Section 3 — Architecture Intelligence ────────────────────────────────

    @staticmethod
    def _architecture(
        project: Project,
        profile: Dict[str, Any],
        detected_services: List[str],
        infra: Dict[str, Any],
    ) -> ArchitectureIntelligenceSection:
        observations: List[str] = []
        if profile.get("workload_profile"):
            observations.append(f"Workload profile: {profile['workload_profile']}.")
        if profile.get("statefulness"):
            observations.append(f"Statefulness: {profile['statefulness']}.")
        if profile.get("scalability_level"):
            observations.append(f"Target scalability: {profile['scalability_level']}.")
        if detected_services:
            observations.append(
                f"{len(detected_services)} service(s) detected: {', '.join(detected_services[:6])}."
            )
        return ArchitectureIntelligenceSection(
            architecture_type=project.architecture_type or profile.get("application_type"),
            architecture_pattern=profile.get("architecture_pattern"),
            application_profile=profile or None,
            detected_services=detected_services,
            entry_points=[str(e) for e in (profile.get("entrypoints") or [])],
            deployment_recommendations=list(infra.get("deployment_notes") or []),
            observations=observations,
        )

    # ── Section 4 — Infrastructure Recommendations ───────────────────────────

    @staticmethod
    def _infrastructure(infra: Dict[str, Any]) -> InfrastructureRecommendationsSection:
        def conv(items: List[Dict[str, str]]) -> List[InfraRecommendation]:
            return [InfraRecommendation(service=i["service"], reason=i.get("reason", "")) for i in items]

        return InfrastructureRecommendationsSection(
            aws_services=conv(infra.get("aws_services") or []),
            compute=conv(infra.get("compute") or []),
            storage=conv(infra.get("storage") or []),
            networking=conv(infra.get("networking") or []),
            observability=conv(infra.get("observability") or []),
        )

    # ── Section 5 — Security & Containerization ──────────────────────────────

    @staticmethod
    def _security_containerization(
        payload: Dict[str, Any],
        stats: Dict[str, Any],
        languages: List[str],
    ) -> SecurityContainerizationSection:
        raw_sec = payload.get("security") or {}
        counts = raw_sec.get("counts") or {"critical": 0, "high": 0, "medium": 0, "low": 0}
        findings = [
            SecurityFinding(
                severity=f.get("severity") or "low",
                title=f.get("title") or "Security finding",
                description=f.get("description") or "",
                category=f.get("category"),
            )
            for f in (raw_sec.get("findings") or [])
        ]
        security = SecuritySubsection(
            score=raw_sec.get("score"),
            grade=raw_sec.get("grade"),
            status=raw_sec.get("status"),
            summary=raw_sec.get("summary"),
            counts=counts,
            findings=findings,
            recommendations=[str(r) for r in (raw_sec.get("recommendations") or [])],
        )

        containerization = WorkflowAnalysisAggregationService._containerization(stats, languages)
        return SecurityContainerizationSection(security=security, containerization=containerization)

    @staticmethod
    def _containerization(stats: Dict[str, Any], languages: List[str]) -> ContainerizationSubsection:
        has_dockerfile = bool(stats.get("has_dockerfile"))
        has_compose = bool(stats.get("has_compose"))
        service_count = stats.get("service_count") or 0

        findings: List[str] = []
        if has_dockerfile:
            findings.append("Existing Dockerfile detected — it will be validated and hardened.")
        else:
            findings.append("No Dockerfile present — one will be generated for this stack.")
        if has_compose:
            findings.append("docker-compose detected — multi-service topology available for reference.")
        if isinstance(service_count, int) and service_count > 1:
            findings.append(f"{service_count} services detected — each can be containerized independently.")

        primary = (languages[0].lower() if languages else "")
        image_strategy = _IMAGE_STRATEGY.get(primary, [
            "Multi-stage build to keep the final image small",
            "Pin a slim, security-patched base image",
        ])

        suitability = "Ready" if has_dockerfile else "Recommended"
        return ContainerizationSubsection(
            docker_suitability=suitability,
            findings=findings,
            image_strategy=image_strategy,
            notes="Run as a non-root user and add a container HEALTHCHECK.",
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _project_info(project: Project, payload: Dict[str, Any]) -> ProjectInfo:
        languages = payload.get("languages") or []
        icon, brand = "fa-cube", False
        if languages:
            icon, brand = _LANGUAGE_ICONS.get(str(languages[0]).lower(), ("fa-cube", False))
        return ProjectInfo(
            id=project.id,
            name=project.name,
            repository_url=project.repository_url,
            logo_icon=icon,
            brand_icon=brand,
        )

    @staticmethod
    def _service_names(services_raw: List[Any], profile: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        for svc in services_raw:
            if isinstance(svc, str):
                names.append(svc)
            elif isinstance(svc, dict):
                name = svc.get("name") or svc.get("type") or svc.get("technology")
                if name:
                    names.append(str(name))
        # Fall back to / augment with the profile's detected_services list.
        for svc in profile.get("detected_services") or []:
            if isinstance(svc, str) and svc not in names:
                names.append(svc)
        return names

    @staticmethod
    def _status(project: Project, payload: Dict[str, Any]) -> str:
        bootstrap = (project.bootstrap_status or "").lower()
        if bootstrap == "failed":
            return "FAILED"
        if bootstrap in ("ready", "context_building"):
            return "DONE"
        if bootstrap in ("pending", "analyzing"):
            return "RUNNING"
        # Unknown/legacy: trust whether analysis actually produced data.
        return "DONE" if payload.get("analysis_available") else "RUNNING"
