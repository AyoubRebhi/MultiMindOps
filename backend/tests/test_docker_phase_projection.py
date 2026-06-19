"""Unit tests for ``DockerPhaseProjectionService`` — the read-only projection
behind ``GET /api/projects/{pid}/workflows/{wid}/docker``.

The projection must FAITHFULLY reshape already-persisted DOCKER-phase state
(generated artifacts + generation metadata + inline validation + corrector
analysis + the DB-backed Dockerfile row) WITHOUT re-running anything. These
tests pin that contract against an in-memory SQLite DB.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.models.artifact import Artifact
from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.services.core.docker_phase_projection_service import (
    DockerPhaseProjectionService,
)

_ORIGINAL_DOCKERFILE = """\
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /app .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

_CORRECTED_DOCKERFILE = _ORIGINAL_DOCKERFILE.replace(
    "RUN pip install -r requirements.txt",
    "RUN pip install --no-cache-dir -r requirements.txt",
)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (User, Project, Workflow, Task, Artifact):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _workflow(phase="DOCKER", docker_status="completed"):
    return Workflow(
        id="wf1",
        project_id="p1",
        started_by="eng1",
        current_phase=phase,
        status="running",
        phases_state={"DOCKER": {"status": docker_status}} if docker_status else {},
    )


def _generated_state(*, validation=None, corrector=None, edited_content=None):
    state = {
        "infra": {
            "artifacts": {"dockerfile": _ORIGINAL_DOCKERFILE, "dockerignore": "*.pyc"},
            "infrastructure_generation": {
                "generation_metadata": {
                    "strategy": "multi_stage",
                    "framework": "fastapi",
                    "language": "python",
                    "blueprint_id": "python_fastapi_multi_stage_1",
                },
                "validation": validation
                or {"valid": True, "errors": [], "warnings": [], "recommendations": []},
            },
            "validation_summary": {"status": "passed", "issues": []},
            "used_llm": True,
            "fallback_used": False,
            "generation_mode": "llm",
        },
        "context_used": {
            "project_type": "web_service",
            "main_service": "api",
            "services": [
                {"name": "api", "framework": "fastapi", "type": "web", "port": 8000}
            ],
            "runtime": {"languages": ["python"], "frameworks": ["fastapi"]},
        },
        "docker_phase": {
            "used_llm": True,
            "fallback_used": False,
            "generation_mode": "llm",
            "status": "completed",
        },
    }
    if edited_content is not None:
        # The editable layer lives under "infrastructure" (NOT "infra"); a user/
        # corrector edit there must win over the generated string.
        state["infrastructure"] = {
            "artifacts": {
                "dockerfile": {
                    "current_content": edited_content,
                    "original_content": _ORIGINAL_DOCKERFILE,
                    "generated_content": _ORIGINAL_DOCKERFILE,
                }
            }
        }
    if corrector is not None:
        state["execution"] = {"corrector": corrector}
    return state


# ── Not generated yet ────────────────────────────────────────────────────────

def test_not_generated_projects_empty_but_well_formed(db):
    wf = _workflow(phase="PLAN_SELECTED", docker_status=None)
    task = Task(id="t1", project_id="p1", workflow_id="wf1", prompt="x", workflow_state={})
    db.add(task); db.commit()

    out = DockerPhaseProjectionService.build(db, project_id="p1", workflow=wf, task=task)

    assert out.generated is False
    assert out.dockerfile is None
    assert out.docker_phase_status is None
    assert out.validation.status == "not_run"
    assert out.corrector.available is False
    assert out.metadata.base_image is None


def test_no_task_does_not_raise(db):
    wf = _workflow(phase="PLAN_SELECTED", docker_status=None)
    out = DockerPhaseProjectionService.build(db, project_id="p1", workflow=wf, task=None)
    assert out.generated is False
    assert out.task_id is None


# ── Generated: metadata + dockerfile + approval ──────────────────────────────

def test_generated_projects_dockerfile_and_metadata(db):
    wf = _workflow()
    task = Task(
        id="t1", project_id="p1", workflow_id="wf1", prompt="x",
        workflow_state=_generated_state(),
    )
    db.add(task)
    db.add(Artifact(
        id="a1", project_id="p1", workflow_id="wf1",
        artifact_type="docker", artifact_subtype="dockerfile",
        content=_ORIGINAL_DOCKERFILE, version=2,
        approval_state="approved", validation_status="passed",
    ))
    db.commit()

    out = DockerPhaseProjectionService.build(db, project_id="p1", workflow=wf, task=task)

    assert out.generated is True
    assert out.task_id == "t1"
    assert out.docker_phase_status == "completed"
    # Dockerfile + approval provenance from the DB row.
    assert out.dockerfile is not None
    assert out.dockerfile.approval_state == "approved"
    assert out.dockerfile.version == 2
    assert out.dockerfile.edited is False
    # Metadata read straight from generation state / Dockerfile parsing.
    assert out.metadata.base_image == "python:3.12-slim"  # last FROM (runtime stage)
    assert out.metadata.port == "8000"                     # EXPOSE
    assert out.metadata.build_strategy == "multi_stage"
    assert out.metadata.detected_runtime == "fastapi"
    assert out.metadata.container_type == "web_service"
    assert out.metadata.generation_mode == "llm"
    assert out.has_dockerignore is True
    assert out.has_compose is False


# ── Validation findings split ────────────────────────────────────────────────

def test_validation_errors_and_warnings_split(db):
    validation = {
        "valid": False,
        "errors": [{"rule": "from_missing", "message": "No FROM", "severity": "error"}],
        "warnings": [{"rule": "latest_tag", "message": "Avoid :latest", "severity": "warning"}],
        "recommendations": [{"rule": "user", "message": "Add USER", "severity": "info"}],
    }
    wf = _workflow()
    task = Task(
        id="t1", project_id="p1", workflow_id="wf1", prompt="x",
        workflow_state=_generated_state(validation=validation),
    )
    db.add(task); db.commit()

    out = DockerPhaseProjectionService.build(db, project_id="p1", workflow=wf, task=task)

    assert out.validation.status == "failed"
    assert out.validation.valid is False
    assert len(out.validation.errors) == 1
    assert out.validation.errors[0].rule == "from_missing"
    assert len(out.validation.warnings) == 1
    assert len(out.validation.recommendations) == 1


# ── Corrector: corrected file derived from an applied edit ───────────────────

def test_corrector_surfaces_analysis_and_corrected_file(db):
    corrector = {
        "status": "completed",
        "retry_count": 1,
        "max_retries": 3,
        "analysis": {
            "status": "analyzed",
            "root_cause": "Missing build dependency",
            "error_type": "dependency_error",
            "confidence": 0.9,
            "fixes": [{"severity": "high", "description": "pin deps"}],
        },
    }
    wf = _workflow()
    task = Task(
        id="t1", project_id="p1", workflow_id="wf1", prompt="x",
        workflow_state=_generated_state(
            corrector=corrector, edited_content=_CORRECTED_DOCKERFILE
        ),
    )
    db.add(task); db.commit()

    out = DockerPhaseProjectionService.build(db, project_id="p1", workflow=wf, task=task)

    assert out.corrector.available is True
    assert out.corrector.status == "completed"
    assert out.corrector.retry_count == 1
    assert out.corrector.analysis["root_cause"] == "Missing build dependency"
    # The applied edit diverges from the generated original → that's the
    # "corrected" Dockerfile shown side-by-side.
    assert out.corrector.corrected_dockerfile == _CORRECTED_DOCKERFILE
    # And the live Dockerfile reflects the edit.
    assert out.dockerfile.edited is True
    assert "--no-cache-dir" in out.dockerfile.content


def test_corrector_without_edit_has_no_corrected_file(db):
    corrector = {
        "status": "completed",
        "retry_count": 0,
        "max_retries": 3,
        "analysis": {"status": "analyzed", "root_cause": "x", "error_type": "unknown_failure", "confidence": 0.5, "fixes": []},
    }
    wf = _workflow()
    task = Task(
        id="t1", project_id="p1", workflow_id="wf1", prompt="x",
        workflow_state=_generated_state(corrector=corrector),
    )
    db.add(task); db.commit()

    out = DockerPhaseProjectionService.build(db, project_id="p1", workflow=wf, task=task)

    assert out.corrector.available is True
    assert out.corrector.corrected_dockerfile is None  # nothing changed yet
