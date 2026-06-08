"""
Docker phase resilience — the DOCKER phase must NEVER fail on LLM problems.

Simulates a total LLM outage (every ``chat_json`` call raises) and asserts:

  * ``InfrastructureAgent.run`` does NOT raise.
  * A non-empty Dockerfile is always produced.
  * The phase-completion contract metadata is present and correct
    (``used_llm`` / ``fallback_used`` / ``generation_mode``).
  * ``OrchestratorAgent.run_docker_phase`` completes (``docker_completed``)
    and stamps ``state["docker_phase"]`` with the contract.
"""

from __future__ import annotations

import pytest


class _DeadLLM:
    """An LLM whose every call fails — models a fully exhausted provider chain."""

    single_request_mode = False

    def chat_json(self, *args, **kwargs):
        raise RuntimeError("429 rate-limited: all providers exhausted")


@pytest.fixture
def dead_llm_agent(monkeypatch):
    from backend.app.services.llm.provider_factory import ProviderFactory

    monkeypatch.setattr(ProviderFactory, "for_agent", classmethod(lambda cls, *a, **k: _DeadLLM()))

    from backend.app.agents.infrastructure_agent import InfrastructureAgent

    return InfrastructureAgent(prompt_template="You generate Docker artifacts.")


def _python_plan() -> dict:
    return {
        "steps": [{"description": "Containerize FastAPI service"}],
        "required_artifacts": ["Dockerfile"],
        "approved_artifacts": ["Dockerfile"],
        "estimated_complexity": "low",
    }


def _python_context() -> dict:
    return {
        "known_files": ["requirements.txt", "app.py"],
        "runtime": {
            "languages": ["python"],
            "frameworks": ["fastapi"],
            "dependency_files": ["requirements.txt"],
        },
        "services": [
            {
                "name": "api",
                "type": "backend",
                "language": "python",
                "framework": "fastapi",
                "port": 8000,
                "run_command": "uvicorn app:app --host 0.0.0.0 --port 8000",
            }
        ],
    }


def test_run_never_raises_and_always_yields_dockerfile(dead_llm_agent):
    result = dead_llm_agent.run(
        prompt="Containerize this FastAPI app",
        plan=_python_plan(),
        infrastructure_context=_python_context(),
        approved_artifacts=["Dockerfile"],
    )

    dockerfile = (result.get("artifacts") or {}).get("dockerfile", "")
    assert dockerfile.strip(), "DOCKER phase must always produce a Dockerfile"
    assert "FROM" in dockerfile, "Dockerfile must contain a base image"

    # Contract metadata present and consistent with a total LLM outage.
    assert result["used_llm"] is False
    assert result["fallback_used"] is True
    assert result["generation_mode"] in {"degraded", "deterministic", "emergency_fallback"}


def test_orchestrator_docker_phase_completes_with_fallback(dead_llm_agent, monkeypatch):
    from backend.app.agents.orchestrator_agent import OrchestratorAgent

    orch = OrchestratorAgent()
    # Reuse the dead-LLM agent so the orchestrator's Docker node also degrades.
    orch.infrastructure_agent = dead_llm_agent

    prior_state = {
        "prompt": "Containerize this FastAPI app",
        "plan": _python_plan(),
        "agent_context": {"infrastructure_context": _python_context()},
        "current_phase": "planning_complete",
    }

    state = orch.run_docker_phase(prior_state)

    assert state["current_phase"] == "docker_completed"
    docker_phase = state.get("docker_phase") or {}
    assert docker_phase.get("status") == "completed_with_fallback"
    assert docker_phase.get("used_llm") is False
    assert docker_phase.get("fallback_used") is True
    assert (state.get("infra") or {}).get("artifacts", {}).get("dockerfile", "").strip()


def test_minimal_safe_dockerfile_covers_languages(dead_llm_agent):
    py = dead_llm_agent._minimal_safe_dockerfile({"main_service": {"language": "python", "port": 8000}})
    java = dead_llm_agent._minimal_safe_dockerfile({"main_service": {"language": "java", "port": 8080}})
    node = dead_llm_agent._minimal_safe_dockerfile({"main_service": {"language": "node", "port": 3000}})
    empty = dead_llm_agent._minimal_safe_dockerfile(None)

    assert "python:3.11-slim" in py and "EXPOSE 8000" in py
    assert "eclipse-temurin" in java and "EXPOSE 8080" in java
    assert "node:20-slim" in node and "EXPOSE 3000" in node
    assert "FROM" in empty  # context-free default never empty
