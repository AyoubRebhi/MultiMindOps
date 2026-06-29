"""Analysis-phase resilience tests for OrchestratorAgent.

These guard the fix for the bootstrap crash where a repository hit the security
gate (``cache_status=blocked``) and ``CodebaseAnalysisAgent`` legitimately
returned no ``application_profile`` — at which point ``_analyze_repository_node``
raised ``"Application profiling failed: key missing from analysis output"`` and
killed the whole project bootstrap.

The contract now: the analysis phase MUST degrade gracefully. A missing /
empty / partial / wrong-typed ``application_profile`` is repaired with safe
defaults and recorded in ``analysis_validation_errors`` — it never raises. Only
genuinely terminal states (security block, handled by the post-analysis router)
stop the pipeline, and they too return cleanly rather than crashing.

``_analyze_repository_node`` only touches ``self.codebase_agent`` and the
static ``_normalize_application_profile``, so we instantiate via
``object.__new__`` to skip the heavy ``__init__`` (LLM clients, graph compile).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.app.agents.orchestrator_agent import (
    OrchestratorAgent,
    _SAFE_PROFILE_STR_DEFAULTS,
    _SAFE_PROFILE_LIST_FIELDS,
)


# ─── _normalize_application_profile (pure, static) ───────────────────────────


def _assert_complete_profile(profile: dict) -> None:
    """Every contract field must be present after normalization."""
    for field, default in _SAFE_PROFILE_STR_DEFAULTS.items():
        assert isinstance(profile[field], str) and profile[field].strip(), field
    for field in _SAFE_PROFILE_LIST_FIELDS:
        assert isinstance(profile[field], list), field


def test_normalize_missing_profile_returns_defaults_and_one_error():
    profile, errors = OrchestratorAgent._normalize_application_profile(
        None, cache_status="blocked"
    )
    _assert_complete_profile(profile)
    assert profile["application_type"] == _SAFE_PROFILE_STR_DEFAULTS["application_type"]
    # A wholly-absent section produces exactly ONE top-level error (not one
    # per field) so the diagnostics stay readable.
    assert len(errors) == 1
    assert errors[0]["field"] == "application_profile"
    assert errors[0]["issue"] == "missing"
    assert "blocked" in errors[0]["detail"]


def test_normalize_empty_dict_is_flagged_and_filled():
    profile, errors = OrchestratorAgent._normalize_application_profile(
        {}, cache_status="reused"
    )
    _assert_complete_profile(profile)
    assert len(errors) == 1
    assert errors[0]["issue"] == "empty"


def test_normalize_wrong_type_is_coerced():
    # e.g. a malformed cache record stored a string / list instead of a dict
    for bad in ("not-a-dict", ["microservices"], 42):
        profile, errors = OrchestratorAgent._normalize_application_profile(
            bad, cache_status="fresh"
        )
        _assert_complete_profile(profile)
        assert errors[0]["issue"] == "wrong_type"


def test_normalize_partial_profile_backfills_only_missing_fields():
    partial = {"application_type": "microservices", "scalability_level": "high"}
    profile, errors = OrchestratorAgent._normalize_application_profile(
        partial, cache_status="fresh"
    )
    _assert_complete_profile(profile)
    # Provided fields are preserved verbatim …
    assert profile["application_type"] == "microservices"
    assert profile["scalability_level"] == "high"
    # … and only the genuinely missing scalar fields are reported as defaulted.
    defaulted_fields = {e["field"] for e in errors if e["issue"] == "defaulted"}
    assert defaulted_fields == {"architecture_pattern", "statefulness", "workload_profile"}


def test_normalize_blank_string_field_is_defaulted():
    profile, errors = OrchestratorAgent._normalize_application_profile(
        {
            "application_type": "   ",  # whitespace-only → blank
            "architecture_pattern": "layered",
            "statefulness": "stateful",
            "workload_profile": "io_bound",
            "scalability_level": "medium",
        },
        cache_status="fresh",
    )
    assert profile["application_type"] == _SAFE_PROFILE_STR_DEFAULTS["application_type"]
    assert any(e["field"] == "application_type" and e["issue"] == "defaulted" for e in errors)


def test_normalize_complete_profile_has_no_errors():
    complete = {
        "application_type": "monolith",
        "architecture_pattern": "mvc",
        "statefulness": "stateful",
        "workload_profile": "cpu_bound",
        "scalability_level": "low",
        "detected_services": ["postgresql"],
        "entrypoints": ["app.py"],
    }
    profile, errors = OrchestratorAgent._normalize_application_profile(
        complete, cache_status="new_analysis"
    )
    assert errors == []
    assert profile == complete


def test_normalize_repairs_wrong_typed_list_field():
    profile, errors = OrchestratorAgent._normalize_application_profile(
        {
            "application_type": "monolith",
            "architecture_pattern": "layered",
            "statefulness": "stateless",
            "workload_profile": "io_bound",
            "scalability_level": "medium",
            "detected_services": "postgresql",  # should be a list
            "entrypoints": None,
        },
        cache_status="fresh",
    )
    assert profile["detected_services"] == []
    assert profile["entrypoints"] == []


# ─── _analyze_repository_node (integration of the node, mocked agent) ────────


def _make_orchestrator(analysis_output: dict) -> OrchestratorAgent:
    """Build an OrchestratorAgent skipping the heavy __init__."""
    orch = object.__new__(OrchestratorAgent)
    orch.codebase_agent = MagicMock()
    orch.codebase_agent.run.return_value = analysis_output
    return orch


_BASE_STATE = {
    "repo_url": "https://example.com/acme/app",
    "repository_visibility": "public",
    "github_token": None,
    "uploaded_env_input": None,
    "logs": [],
}


def test_node_does_not_raise_when_profile_missing_and_records_errors():
    """The original bug: a missing application_profile must NOT crash."""
    analysis = {
        "agent": "CodebaseAnalysisAgent",
        "security": {"status": "safe"},
        "repository_analysis": {"cache_status": "reused"},
        "agent_context": {},
        "repo_path": "/tmp/clone",
        # NOTE: application_profile deliberately absent
    }
    orch = _make_orchestrator(analysis)

    result = orch._analyze_repository_node(dict(_BASE_STATE))

    profile = result["application_profile"]
    _assert_complete_profile(profile)
    errors = result["analysis_validation_errors"]
    assert errors and errors[0]["issue"] == "missing"
    # The agent_context must also carry the repaired profile for the planner.
    assert result["agent_context"]["application_profile"] == profile


def test_node_security_blocked_returns_cleanly_without_profile_warning():
    """A blocked repo legitimately has no profile — return, don't crash."""
    analysis = {
        "agent": "CodebaseAnalysisAgent",
        "security": {"status": "blocked", "blocked_reasons": ["secret leak"]},
        "repository_analysis": {"cache_status": "blocked"},
        "agent_context": None,
        "repo_path": "/tmp/clone",
    }
    orch = _make_orchestrator(analysis)

    result = orch._analyze_repository_node(dict(_BASE_STATE))

    # Security status preserved so the post-analysis router can send → finalize.
    assert result["repository_security"]["status"] == "blocked"
    # Still safe to read the profile (defaulted), but the user-facing log must
    # NOT contain the "degraded profile" warning for a blocked repo.
    _assert_complete_profile(result["application_profile"])
    messages = [entry["message"] for entry in result["logs"]]
    assert any("blocked by security gate" in m for m in messages)
    assert not any("degraded profile" in m for m in messages)


def test_node_handles_cached_incomplete_output():
    """A stale cache record predating the profile field must self-heal."""
    analysis = {
        "agent": "CodebaseAnalysisAgent",
        "security": {"status": "safe"},
        "repository_analysis": {"cache_status": "reused"},
        "agent_context": {"planner_context": {"foo": "bar"}},
        "application_profile": {"application_type": "microservices"},  # partial
        "repo_path": "/tmp/clone",
    }
    orch = _make_orchestrator(analysis)

    result = orch._analyze_repository_node(dict(_BASE_STATE))

    profile = result["application_profile"]
    _assert_complete_profile(profile)
    assert profile["application_type"] == "microservices"  # preserved
    # Degraded-profile warning surfaced for the user (non-blocked path).
    messages = [entry["message"] for entry in result["logs"]]
    assert any("degraded profile" in m for m in messages)
    # Existing agent_context keys preserved alongside the injected profile.
    assert result["agent_context"]["planner_context"] == {"foo": "bar"}


def test_node_complete_profile_records_no_validation_errors():
    analysis = {
        "agent": "CodebaseAnalysisAgent",
        "security": {"status": "safe_with_warnings"},
        "repository_analysis": {"cache_status": "new_analysis"},
        "agent_context": {},
        "application_profile": {
            "application_type": "monolith",
            "architecture_pattern": "layered",
            "statefulness": "stateless",
            "workload_profile": "io_bound",
            "scalability_level": "medium",
            "detected_services": [],
            "entrypoints": ["app.py"],
        },
        "repo_path": "/tmp/clone",
    }
    orch = _make_orchestrator(analysis)

    result = orch._analyze_repository_node(dict(_BASE_STATE))

    assert result["analysis_validation_errors"] == []
    messages = [entry["message"] for entry in result["logs"]]
    assert not any("degraded profile" in m for m in messages)
