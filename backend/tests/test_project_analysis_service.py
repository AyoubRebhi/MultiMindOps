"""Unit tests for ProjectAnalysisService.

Focus on the security-normalization contract the frontend depends on: the
backend GET /projects/:id/analysis security block must always expose
``score``/``grade``/``counts``/``findings``/``recommendations`` in a stable
shape, regardless of which source (workflow state vs. re-derived) produced it.
These are pure-function tests — no DB.
"""

from __future__ import annotations

from backend.app.schemas.project import ProjectAnalysisResponse
from backend.app.services.core.project_analysis_service import ProjectAnalysisService


def test_normalize_security_maps_transformer_output():
    """A SecurityScoreTransformer-shaped dict normalises cleanly."""
    raw = {
        "score": 78,
        "grade": "B",
        "status": "safe_with_warnings",
        "summary": "Looks mostly fine.",
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 0,
        "vulnerabilities": [
            {
                "severity": "high",
                "title": "Base image not pinned",
                "description": "Pin to a digest.",
                "recommendation": "Use a SHA256 digest.",
                "file": "Dockerfile",
            },
            {"severity": "medium", "title": "Dep advisory", "description": "Run npm audit fix."},
            {"severity": "medium", "title": "Runs as root", "description": "Add a non-root USER."},
        ],
        "recommendations": ["Pin the base image", "Add a non-root USER"],
    }

    out = ProjectAnalysisService._normalize_security(raw)

    assert out["score"] == 78
    assert out["grade"] == "B"
    # Counts come straight from the explicit top-level integers.
    assert out["counts"] == {"critical": 0, "high": 1, "medium": 2, "low": 0}
    assert len(out["findings"]) == 3
    first = out["findings"][0]
    assert first["severity"] == "high"
    assert first["title"] == "Base image not pinned"
    assert first["recommendation"] == "Use a SHA256 digest."
    assert out["recommendations"] == ["Pin the base image", "Add a non-root USER"]


def test_normalize_security_derives_counts_from_findings_when_absent():
    """When top-level counts are missing, they are derived from findings."""
    raw = {
        "score": 60,
        "vulnerabilities": [
            {"severity": "critical", "title": "A"},
            {"severity": "low", "title": "B"},
            {"severity": "low", "title": "C"},
        ],
    }

    out = ProjectAnalysisService._normalize_security(raw)

    assert out["counts"]["critical"] == 1
    assert out["counts"]["low"] == 2
    assert out["counts"]["high"] == 0
    # A finding with no description falls back to its title, never crashes.
    assert out["findings"][0]["description"] == "A"


def test_normalize_security_tolerates_empty_input():
    out = ProjectAnalysisService._normalize_security({})
    assert out["score"] is None
    assert out["findings"] == []
    assert out["counts"] == {"critical": 0, "high": 0, "medium": 0, "low": 0}
    assert out["recommendations"] == []


# ── application_profile normalization ────────────────────────────────────────


def test_normalize_application_profile_none_returns_none():
    """A missing profile (None) yields None — never a raw object or string."""
    assert ProjectAnalysisService._normalize_application_profile(None) is None


def test_normalize_application_profile_empty_returns_none():
    """An empty dict is treated as 'no profile'."""
    assert ProjectAnalysisService._normalize_application_profile({}) is None


def test_normalize_application_profile_full_preserves_structure():
    """A full ApplicationProfilerService dict maps field-for-field — no flattening."""
    raw = {
        "application_type": "microservices",
        "architecture_pattern": "event-driven",
        "workload_profile": "io_bound",
        "statefulness": "stateful",
        "scalability_level": "high",
        "entrypoints": ["app.py", "worker.py"],
        "detected_services": ["postgresql", "redis", "backend-api"],
    }

    out = ProjectAnalysisService._normalize_application_profile(raw)

    assert isinstance(out, dict)
    assert out["application_type"] == "microservices"
    assert out["architecture_pattern"] == "event-driven"
    assert out["workload_profile"] == "io_bound"
    assert out["statefulness"] == "stateful"
    assert out["scalability_level"] == "high"
    assert out["entrypoints"] == ["app.py", "worker.py"]
    assert out["detected_services"] == ["postgresql", "redis", "backend-api"]


def test_normalize_application_profile_coerces_messy_lists():
    """Non-list list-fields and stray None entries are sanitised, not crashed on."""
    raw = {
        "application_type": "monolith",
        "entrypoints": None,             # wrong type → []
        "detected_services": ["frontend", None, 123],  # None dropped, ints stringified
    }

    out = ProjectAnalysisService._normalize_application_profile(raw)

    assert out["entrypoints"] == []
    assert out["detected_services"] == ["frontend", "123"]


def test_analysis_response_validates_structured_profile():
    """The regression guard: a dict application_profile must pass response validation.

    This is exactly the path that previously raised ResponseValidationError — the
    backend handed FastAPI a dict where the schema declared ``str``.
    """
    profile = ProjectAnalysisService._normalize_application_profile(
        {
            "application_type": "monolith",
            "architecture_pattern": "layered",
            "workload_profile": "io_bound",
            "statefulness": "stateless",
            "scalability_level": "medium",
            "entrypoints": ["main.py"],
            "detected_services": ["backend-api"],
        }
    )

    payload = {
        "project_id": "p-123",
        "bootstrap_status": "ready",
        "bootstrap_error": None,
        "analysis_available": True,
        "language": "Python",
        "stats": {
            "project_type": "web_service",
            "application_profile": profile,
        },
        "security": None,
    }

    # Must not raise — mirrors FastAPI's response_model validation.
    model = ProjectAnalysisResponse.model_validate(payload)

    assert model.stats.application_profile is not None
    assert model.stats.application_profile.application_type == "monolith"
    assert model.stats.application_profile.entrypoints == ["main.py"]
    # Serialises back to a nested object (not a string).
    dumped = model.model_dump()
    assert dumped["stats"]["application_profile"]["scalability_level"] == "medium"


def test_analysis_response_accepts_null_profile():
    """A None profile still validates (the common 'still analyzing' case)."""
    model = ProjectAnalysisResponse.model_validate(
        {
            "project_id": "p-1",
            "bootstrap_status": "analyzing",
            "stats": {"application_profile": None},
        }
    )
    assert model.stats.application_profile is None
