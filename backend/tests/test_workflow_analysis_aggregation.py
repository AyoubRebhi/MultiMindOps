"""Unit tests for WorkflowAnalysisAggregationService.

Exercises the section mapping + status derivation in isolation: the upstream
``ProjectAnalysisService.build_payload`` is patched to a fixed payload so the
assertions target the NEW aggregation/mapping logic (not ProjectAnalysisService,
which has its own coverage). Transient ORM objects are used — no DB needed
because ``build_payload`` is stubbed and the project is attached directly.
"""

from __future__ import annotations

from unittest.mock import patch

from backend.app.models.project import Project
from backend.app.models.workflow import Workflow
from backend.app.services.core.project_analysis_service import ProjectAnalysisService
from backend.app.services.core.workflow_analysis_aggregation_service import (
    WorkflowAnalysisAggregationService,
)

_PAYLOAD = {
    "project_id": "p1",
    "bootstrap_status": "ready",
    "bootstrap_error": None,
    "analysis_available": True,
    "language": "Java",
    "languages": ["Java"],
    "framework": "Spring Boot",
    "frameworks": ["Spring Boot"],
    "runtime": "java_17",
    "dependencies": ["Maven"],
    "services": [{"name": "postgres", "type": "database"}],
    "stats": {
        "project_type": "backend_service",
        "service_count": 1,
        "lines_of_code": 12000,
        "has_dockerfile": True,
        "has_compose": True,
        "has_ci": False,
        "build_systems": ["Maven"],
        "devops_tools": ["Docker", "Docker Compose"],
        "application_profile": {
            "application_type": "monolith",
            "architecture_pattern": "layered",
            "workload_profile": "io_bound",
            "statefulness": "stateful",
            "scalability_level": "medium",
            "entrypoints": ["src/main/java/App.java"],
            "detected_services": ["postgres"],
        },
    },
    "security": {
        "score": 82,
        "grade": "B",
        "status": "pass",
        "summary": "No critical issues found.",
        "counts": {"critical": 0, "high": 1, "medium": 2, "low": 3},
        "findings": [
            {
                "severity": "high",
                "title": "Hardcoded secret",
                "description": "API key committed to source.",
                "category": "secrets",
            }
        ],
        "recommendations": ["Rotate the committed key"],
    },
}


def _build(payload=None, **project_overrides):
    project = Project(
        id="p1",
        owner_id="eng1",
        name="Shop API",
        description="Online store backend service.",
        repository_url="https://github.com/acme/shop",
        bootstrap_status=project_overrides.pop("bootstrap_status", "ready"),
        **project_overrides,
    )
    workflow = Workflow(
        id="wf1",
        project_id="p1",
        started_by="eng1",
        current_phase="ARCHITECTURE_DECISION",
        status="awaiting_input",
    )
    workflow.project = project
    with patch.object(ProjectAnalysisService, "build_payload", return_value=payload or _PAYLOAD):
        return WorkflowAnalysisAggregationService.build(db=None, workflow=workflow)


def test_customer_portal_section():
    resp = _build()
    cp = resp.customer_portal
    assert cp.project_name == "Shop API"
    assert cp.repository_url == "https://github.com/acme/shop"
    assert cp.application_purpose == "Online store backend service."
    assert cp.application_type == "monolith"
    assert cp.architecture_pattern == "layered"
    assert cp.workload_profile == "io_bound"
    assert cp.statefulness == "stateful"
    assert cp.scalability_level == "medium"


def test_code_analysis_section():
    resp = _build()
    code = resp.code_analysis
    assert [t.name for t in code.languages] == ["Java"]
    assert [t.name for t in code.frameworks] == ["Spring Boot"]
    assert "Maven" in code.package_managers
    labels = {i.label: i for i in code.repository_insights}
    assert labels["Dockerfile"].ok is True
    assert labels["CI/CD"].ok is False
    assert labels["Project Type"].value == "backend_service"


def test_architecture_intelligence_section():
    resp = _build()
    arch = resp.architecture_intelligence
    assert arch.architecture_pattern == "layered"
    assert "postgres" in arch.detected_services
    assert arch.entry_points == ["src/main/java/App.java"]
    assert arch.deployment_recommendations  # non-empty deployment notes
    assert arch.application_profile["scalability_level"] == "medium"


def test_infrastructure_section_is_derived():
    resp = _build()
    infra = resp.infrastructure_recommendations
    assert "ECS Fargate" in {r.service for r in infra.compute}
    assert "RDS (PostgreSQL)" in {r.service for r in infra.storage}
    assert "Application Load Balancer" in {r.service for r in infra.networking}


def test_security_and_containerization_section():
    resp = _build()
    sec = resp.security_containerization.security
    assert sec.score == 82
    assert sec.grade == "B"
    assert sec.counts["high"] == 1
    assert len(sec.findings) == 1
    assert sec.findings[0].title == "Hardcoded secret"

    cont = resp.security_containerization.containerization
    assert cont.docker_suitability == "Ready"  # Dockerfile present
    assert any("python" not in s.lower() for s in cont.image_strategy)
    # Java image strategy mentions a JRE runtime.
    assert any("JRE" in s or "temurin" in s.lower() for s in cont.image_strategy)


def test_status_done_when_bootstrap_ready():
    assert _build().status == "DONE"


def test_status_running_when_still_analyzing():
    payload = dict(_PAYLOAD, bootstrap_status="analyzing", analysis_available=False)
    resp = _build(payload=payload, bootstrap_status="analyzing")
    assert resp.status == "RUNNING"


def test_status_failed_when_bootstrap_failed():
    resp = _build(bootstrap_status="failed")
    assert resp.status == "FAILED"


def test_project_info_picks_language_brand_icon():
    resp = _build()
    assert resp.project_info.logo_icon == "fa-java"
    assert resp.project_info.brand_icon is True


def test_build_for_project_is_a_read_only_projection():
    """The project-scoped projection reads the SAME source and yields the same
    sections — just without a single owning workflow id. This is what powers
    /projects/{id}/workflow-analysis (the fix for the mock-data bug)."""
    project = Project(
        id="p1", owner_id="eng1", name="Shop API",
        description="Online store backend service.",
        repository_url="https://github.com/acme/shop", bootstrap_status="ready",
    )
    with patch.object(ProjectAnalysisService, "build_payload", return_value=_PAYLOAD):
        resp = WorkflowAnalysisAggregationService.build_for_project(db=None, project=project)

    assert resp.workflow_id is None  # project-scoped: no owning workflow
    assert resp.project_id == "p1"
    # Same persisted data surfaces as the workflow-scoped build.
    assert resp.customer_portal.application_type == "monolith"
    assert [t.name for t in resp.code_analysis.languages] == ["Java"]
    assert "RDS (PostgreSQL)" in {r.service for r in resp.infrastructure_recommendations.storage}
    assert resp.security_containerization.security.score == 82
    assert resp.status == "DONE"
