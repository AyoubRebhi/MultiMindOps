"""
Output-hardening pass — unit coverage for:

  • Terraform name sanitization  (sanitize_terraform_name)
  • Dockerfile HEALTHCHECK repair (normalize_healthcheck / validate_healthcheck)
  • The Python fallback Dockerfile emits a parseable HEALTHCHECK

These are deterministic, dependency-free checks: no LLM, no Docker, no network.
"""
from __future__ import annotations

import re

import pytest

from backend.app.services.terraform_generation.utils.variable_context import (
    sanitize_terraform_name,
    build_variable_context,
)
from backend.app.services.infrastructure.dockerfile_healthcheck import (
    normalize_healthcheck,
    validate_healthcheck,
)
from backend.app.schemas.blueprint import parse_blueprint


# AWS-safe: starts with a letter, only [a-z0-9-], ≤ 32 chars.
_AWS_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


# ── TASK 1: sanitize_terraform_name ──────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "My_Cool_App",                 # underscores + uppercase
        "123-numbers-first",           # leading digits
        "---weird---",                 # leading/trailing hyphens
        "a..b..c",                     # illegal chars → consecutive hyphens
        "UPPER",                       # all caps
        "spring_boot__demo--service",  # double separators
        "x" * 80,                      # over length
        "9",                           # single digit (nothing valid survives)
        "",                            # empty
        None,                          # missing
        "café-déjà",                   # non-ascii
    ],
)
def test_sanitize_always_produces_aws_safe_name(raw):
    name = sanitize_terraform_name(raw)
    assert _AWS_NAME_RE.match(name), f"{raw!r} → {name!r} is not AWS-safe"
    assert "--" not in name, "RDS rejects consecutive hyphens"
    assert not name.endswith("-")
    assert len(name) <= 32


def test_sanitize_preserves_clean_names():
    assert sanitize_terraform_name("golden") == "golden"
    assert sanitize_terraform_name("my-app") == "my-app"


def test_sanitize_starts_with_letter_after_stripping_digits():
    assert sanitize_terraform_name("42-the-answer") == "the-answer"


def test_sanitize_truncates_without_trailing_hyphen():
    raw = "abcdefghij-" * 5  # 55 chars, hyphen every 10
    out = sanitize_terraform_name(raw)
    assert len(out) <= 32
    assert not out.endswith("-")


def test_alb_and_rds_derived_names_are_compliant():
    """ALB '${name}-alb' and RDS '${name}-db' must stay valid."""
    name = sanitize_terraform_name("My_Service!!")
    assert re.match(r"^[a-z][a-z0-9-]*$", f"{name}-alb")
    assert re.match(r"^[a-z][a-z0-9-]*$", f"{name}-db")


def test_variable_context_applies_sanitization():
    bp = parse_blueprint({
        "compute": {"type": "ECS", "instance_type": "t3.small"},
        "networking": {"vpc": True, "multi_az": False, "load_balancer": "ALB"},
        "scaling": {"strategy": "vertical", "auto_scaling": False},
        "storage": {"object_storage": "S3"},
        "architecture_style": "monolith",
        "aws_region": "us-east-1",
        "strategy_tier": "balanced",
    })
    ctx = build_variable_context(bp, project_name="My_Bad__Name--123")
    assert _AWS_NAME_RE.match(ctx["project_name"])


# ── TASK 2: HEALTHCHECK normalization + validation ───────────────────────────


_BROKEN = (
    "FROM python:3.11-slim\n"
    "EXPOSE 8000\n"
    "HEALTHCHECK --interval=30s --timeout=5s --retries=3 \\nCMD curl -f http://localhost:8000/ || exit 1\n"
    'CMD ["python", "app.py"]\n'
)


def test_normalize_repairs_literal_newline_in_healthcheck():
    fixed, repairs = normalize_healthcheck(_BROKEN)
    assert repairs, "expected a repair to be recorded"
    # The literal escape is gone and the instruction is a single valid line.
    assert "\\n" not in fixed.split("HEALTHCHECK", 1)[1].splitlines()[0]
    assert "HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl" in fixed
    # And the repaired content now validates clean.
    assert validate_healthcheck(fixed) == []


def test_validate_flags_broken_healthcheck():
    issues = validate_healthcheck(_BROKEN)
    assert any("literal escape" in i for i in issues)


def test_validate_flags_unitless_duration():
    df = "HEALTHCHECK --interval=30 --timeout=5s CMD curl -f http://localhost/ || exit 1\n"
    issues = validate_healthcheck(df)
    assert any("time unit" in i for i in issues)


def test_validate_flags_missing_cmd():
    df = "HEALTHCHECK --interval=30s --timeout=5s --retries=3\n"
    issues = validate_healthcheck(df)
    assert any("missing a CMD" in i for i in issues)


def test_well_formed_multiline_healthcheck_is_untouched():
    good = (
        "FROM python:3.11-slim\n"
        "HEALTHCHECK --interval=30s --timeout=5s --retries=3 \\\n"
        "  CMD curl -f http://localhost:8000/docs || exit 1\n"
        'CMD ["python", "app.py"]\n'
    )
    fixed, repairs = normalize_healthcheck(good)
    assert repairs == []
    assert fixed == good.rstrip("\n") or fixed == good or fixed.startswith("FROM")
    assert validate_healthcheck(good) == []


def test_normalize_is_noop_without_healthcheck():
    df = "FROM python:3.11-slim\nCMD [\"python\", \"app.py\"]\n"
    fixed, repairs = normalize_healthcheck(df)
    assert fixed == df and repairs == []


# ── TASK 2: Python fallback Dockerfile emits a valid HEALTHCHECK ─────────────


def test_python_fallback_dockerfile_has_valid_single_line_healthcheck():
    from backend.app.services.infrastructure.infrastructure_artifact_builder_service import (
        InfrastructureArtifactBuilderService,
    )
    builder = InfrastructureArtifactBuilderService()
    mapped = {
        "artifact_expectations": {"needs_dockerfile": True},
        "main_service": {"language": "python", "port": 8000, "run_command": "python app.py"},
        "runtime": {"dependency_files": ["requirements.txt"]},
        "build_context": ".",
    }
    df = builder.build_dockerfile(mapped)
    assert "HEALTHCHECK" in df
    # No external-tool dependency and no literal-escape corruption.
    assert validate_healthcheck(df) == []
    assert "curl" not in df and "wget" not in df
