"""
PrebuildGate contract — blocked builds must surface as a structured HTTP 422,
never a silent 200. Also covers the template validator's structured output and
the generation-step token sanitization.
"""

from __future__ import annotations

import json
import types

import pytest


# ── Template validator structured contract ────────────────────────────────────

def test_template_validator_reports_structured_reason_and_details():
    from backend.app.services.artifact_generation.validators.template_artifact_validator import (
        TemplateArtifactValidator,
    )

    result = TemplateArtifactValidator().validate(
        {"dockerfile": "FROM python:3.11-slim\nEXPOSE {{ port }}\n"}
    )
    payload = result.to_dict()

    assert payload["valid"] is False
    assert payload["reason"] == "UNRESOLVED_TEMPLATE_TOKEN"
    assert payload["details"] == ["dockerfile"]
    assert payload["issue_count"] >= 1


def test_template_validator_clean_artifact_is_valid():
    from backend.app.services.artifact_generation.validators.template_artifact_validator import (
        TemplateArtifactValidator,
    )

    result = TemplateArtifactValidator().validate(
        {"dockerfile": "FROM python:3.11-slim\nEXPOSE 8000\n"}
    )
    payload = result.to_dict()
    assert payload["valid"] is True
    assert payload["reason"] is None
    assert payload["details"] == []


# ── PrebuildGate → HTTP 422 structured block ──────────────────────────────────

@pytest.fixture
def fake_task():
    return types.SimpleNamespace(id="task-123", project_id="proj-1", workflow_id="wf-1")


def test_gate_blocks_unresolved_token_with_http_422(monkeypatch, fake_task):
    from backend.app.api.routes import execution
    from backend.app.services.core.task_service import TaskService

    # _block_build persists state — make that a no-op for the unit test.
    monkeypatch.setattr(TaskService, "save_workflow_state", lambda *a, **k: None)

    state: dict = {"current_phase": "docker_completed"}
    artifacts = {"dockerfile": "FROM python:3.11-slim\nEXPOSE {{ port }}\n"}

    response = execution._enforce_prebuild_validation_gate(
        db=None, task=fake_task, state=state, artifacts=artifacts,
    )

    assert response is not None, "gate must block an unresolved-token Dockerfile"
    assert response.status_code == 422

    body = json.loads(response.body)
    assert body["phase"] == "DOCKER"
    assert body["status"] == "blocked"
    assert body["reason"] == "UNRESOLVED_TEMPLATE_TOKEN"
    assert "dockerfile" in body["details"]
    assert body["failure_kind"] == "template_validation"
    # State was routed to human review, NOT silently dropped.
    assert state["current_phase"] == "human_review_required"


def test_gate_passes_clean_dockerfile_without_known_files(monkeypatch, fake_task):
    from backend.app.api.routes import execution
    from backend.app.services.core.task_service import TaskService

    monkeypatch.setattr(TaskService, "save_workflow_state", lambda *a, **k: None)

    state: dict = {"current_phase": "docker_completed"}
    # Clean, exec-form Dockerfile; no known_files so Layer C is skipped.
    artifacts = {
        "dockerfile": (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            "EXPOSE 8000\n"
            'CMD ["python", "app.py"]\n'
        )
    }

    response = execution._enforce_prebuild_validation_gate(
        db=None, task=fake_task, state=state, artifacts=artifacts,
    )
    assert response is None, "a clean Dockerfile must pass the gate (enqueue proceeds)"


# ── Generation-step sanitization ──────────────────────────────────────────────

def test_sanitizer_strips_unresolved_token_lines():
    from backend.app.services.llm.provider_factory import ProviderFactory

    # Construct the agent with a no-op LLM so __init__ does not need API keys.
    class _NoLLM:
        single_request_mode = False

        def chat_json(self, *a, **k):
            raise RuntimeError("offline")

    import backend.app.agents.infrastructure_agent as ia

    orig = ProviderFactory.for_agent
    ProviderFactory.for_agent = classmethod(lambda cls, *a, **k: _NoLLM())  # type: ignore
    try:
        agent = ia.InfrastructureAgent(prompt_template="x")
    finally:
        ProviderFactory.for_agent = orig  # type: ignore

    dirty = {
        "dockerfile": (
            "FROM python:3.11-slim\n"
            "EXPOSE {{ port }}\n"
            'CMD ["python", "app.py"]\n'
        )
    }
    sanitized, changed, removed = agent._sanitize_unresolved_templates(dirty)

    assert changed is True
    assert "{{" not in sanitized["dockerfile"]
    assert "FROM python:3.11-slim" in sanitized["dockerfile"]
    assert 'CMD ["python", "app.py"]' in sanitized["dockerfile"]
    assert removed and "dockerfile:2" in removed[0]
