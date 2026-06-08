"""
Tests for Terraform failure classification + generation/init decoupling.

Covers:
* classify_terraform_output — raw stderr/stdout blobs.
* classify_validation_result — TerraformValidationResult routing, ensuring a
  genuine config defect is never masked as a transient network issue.
* TerraformAgent._run_deterministic — ALWAYS returns artifacts (never raises) even
  when terraform init fails because the registry is unreachable.

Hermetic: no terraform binary, no network, no heavy agent construction.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.agents.terraform_agent import TerraformAgent
from backend.app.schemas.blueprint import parse_blueprint
from backend.app.services.terraform_generation.validators import (
    NETWORK_ERROR,
    PROVIDER_FETCH_FAILED,
    VALIDATION_FAILED,
    classify_terraform_output,
    classify_validation_result,
    is_recoverable,
)
from backend.app.services.terraform_generation.validators.models import (
    TerraformSecurityIssue,
    TerraformValidationIssue,
    TerraformValidationResult,
)


# ── classify_terraform_output ────────────────────────────────────────────────

def test_classify_output_network_dial_tcp():
    text = (
        "Error: Failed to query available provider packages\n"
        "could not connect to registry.terraform.io: dial tcp: lookup "
        "registry.terraform.io: no such host"
    )
    assert classify_terraform_output(text) == NETWORK_ERROR


def test_classify_output_provider_fetch():
    text = (
        "Error: Failed to install provider\n"
        "Error while installing hashicorp/aws v5.0.0: checksum mismatch"
    )
    assert classify_terraform_output(text) == PROVIDER_FETCH_FAILED


def test_classify_output_none_when_clean():
    assert classify_terraform_output("Apply complete! Resources: 3 added.") is None
    assert classify_terraform_output("") is None
    assert classify_terraform_output(None) is None


# ── classify_validation_result ───────────────────────────────────────────────

def _result(issues=None, security=None, status="failed") -> TerraformValidationResult:
    return TerraformValidationResult(
        status=status,
        issues=issues or [],
        security_issues=security or [],
    )


def test_classify_result_network_init_failure():
    res = _result(issues=[
        TerraformValidationIssue(
            severity="error",
            source="terraform_init",
            message="terraform_init failed: dial tcp registry.terraform.io: i/o timeout",
        )
    ])
    assert classify_validation_result(res) == NETWORK_ERROR
    assert is_recoverable(NETWORK_ERROR) is True


def test_classify_result_provider_fetch_failure():
    res = _result(issues=[
        TerraformValidationIssue(
            severity="error",
            source="terraform_init",
            message="terraform_init failed: Failed to query available provider packages",
        )
    ])
    assert classify_validation_result(res) == PROVIDER_FETCH_FAILED


def test_classify_result_genuine_validate_error_wins():
    # A real `terraform validate` error must NOT be masked even if an init
    # network message is also present.
    res = _result(issues=[
        TerraformValidationIssue(
            severity="error",
            source="terraform_validate",
            message="Reference to undeclared resource",
        ),
        TerraformValidationIssue(
            severity="error",
            source="terraform_init",
            message="dial tcp: no such host",
        ),
    ])
    assert classify_validation_result(res) == VALIDATION_FAILED
    assert is_recoverable(VALIDATION_FAILED) is False


def test_classify_result_hcl_parse_error_is_validation():
    res = _result(issues=[
        TerraformValidationIssue(
            severity="error", source="hcl2_parse", message="HCL2 parse error: unexpected }",
        )
    ])
    assert classify_validation_result(res) == VALIDATION_FAILED


def test_classify_result_security_critical_is_validation():
    res = _result(
        status="failed",
        security=[
            TerraformSecurityIssue(
                severity="critical", source="tfsec", rule_id="aws-s3-no-public",
                message="public bucket",
            )
        ],
    )
    assert classify_validation_result(res) == VALIDATION_FAILED


def test_classify_result_none_when_not_blocking():
    res = _result(status="passed")
    assert classify_validation_result(res) is None


def test_classify_result_init_unknown_error_defaults_to_validation():
    # init failed with no network/provider signature → do not mask as network.
    res = _result(issues=[
        TerraformValidationIssue(
            severity="error", source="terraform_init",
            message="terraform_init failed: some unexpected backend error",
        )
    ])
    assert classify_validation_result(res) == VALIDATION_FAILED


# ── TerraformAgent._run_deterministic decoupling ─────────────────────────────

def _fake_agent(validation_result: TerraformValidationResult) -> TerraformAgent:
    """Build a TerraformAgent without its heavy __init__ (no LLM/RAG/network)."""
    agent = object.__new__(TerraformAgent)
    rendered = {
        "terraform_providers": 'provider "aws" {}',
        "terraform_vpc": 'resource "aws_vpc" "main" {}',
        "terraform_ecs": 'resource "aws_ecs_cluster" "c" {}',
        "terraform_variables": 'variable "region" {}',
        "terraform_tfvars": 'region = "us-east-1"',
        "terraform_outputs": (
            'output "cluster_endpoint" {}\noutput "cluster_name" {}\n'
            'output "load_balancer_dns" {}\noutput "ecr_repository_url" {}'
        ),
    }
    agent._renderer = SimpleNamespace(
        render=lambda **kw: SimpleNamespace(artifacts=dict(rendered), metadata={"tier": "balanced"})
    )
    agent._validator = SimpleNamespace(validate=lambda artifacts: validation_result)
    return agent


def _monolith_blueprint():
    return parse_blueprint({
        "aws_region": "us-east-1",
        "strategy_tier": "balanced",
        "architecture_style": "monolith",
        "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
        "scaling": {"strategy": "vertical+horizontal", "auto_scaling": True},
        "storage": {"object_storage": "S3"},
        "compute": {"type": "ECS", "instance_type": "t3.medium"},
        "database": {"engine": "postgres", "deployment": "RDS Multi-AZ", "read_replicas": False},
    })


def test_run_deterministic_returns_artifacts_on_network_init_failure():
    """The headline fix: registry unreachable → artifacts STILL returned."""
    res = TerraformValidationResult(
        status="failed",
        issues=[TerraformValidationIssue(
            severity="error", source="terraform_init",
            message="terraform_init failed: dial tcp registry.terraform.io: no such host",
        )],
    )
    agent = _fake_agent(res)
    out = agent._run_deterministic(
        blueprint=_monolith_blueprint(), strategy_tier="balanced",
        task_id=None, infrastructure_context=None,
    )
    # Artifacts are preserved, the workflow can continue (degraded, recoverable).
    assert out["artifacts"], "artifacts must never be discarded on init failure"
    assert "terraform_outputs" in out["artifacts"]
    assert out["validation_status"] == "degraded"
    assert out["failure_classification"] == NETWORK_ERROR


def test_run_deterministic_flags_failed_on_genuine_validation_error():
    res = TerraformValidationResult(
        status="failed",
        issues=[TerraformValidationIssue(
            severity="error", source="terraform_validate",
            message="Reference to undeclared resource aws_foo.bar",
        )],
    )
    agent = _fake_agent(res)
    out = agent._run_deterministic(
        blueprint=_monolith_blueprint(), strategy_tier="balanced",
        task_id=None, infrastructure_context=None,
    )
    # Even a genuine validation failure keeps artifacts (for inspection/retry).
    assert out["artifacts"]
    assert out["validation_status"] == "failed"
    assert out["failure_classification"] == VALIDATION_FAILED


def test_run_deterministic_passed_when_validation_ok():
    res = TerraformValidationResult(status="passed")
    agent = _fake_agent(res)
    out = agent._run_deterministic(
        blueprint=_monolith_blueprint(), strategy_tier="balanced",
        task_id=None, infrastructure_context=None,
    )
    assert out["validation_status"] == "passed"
    assert out["failure_classification"] is None


# ── OrchestratorAgent._terraform_phase_node routing ──────────────────────────

def _node_agent(tf_result: dict):
    """OrchestratorAgent shell with only a fake terraform_agent wired in."""
    from backend.app.agents.orchestrator_agent import OrchestratorAgent

    agent = object.__new__(OrchestratorAgent)
    agent.terraform_agent = SimpleNamespace(run=lambda **kw: tf_result)
    return agent


_TF_ARTIFACTS = {"terraform_providers": 'provider "aws" {}', "terraform_vpc": "x"}
_BASE_STATE = {"prompt": "deploy", "plan": {}, "agent_context": {}}


def test_node_keeps_artifacts_on_degraded_network():
    agent = _node_agent({
        "artifacts": dict(_TF_ARTIFACTS),
        "validation": {"status": "failed", "issues": [], "security_issues": []},
        "validation_status": "degraded",
        "failure_classification": NETWORK_ERROR,
        "terraform_outputs": {},
        "generated_artifacts": ["terraform/providers.tf"],
    })
    out = agent._terraform_phase_node(dict(_BASE_STATE))
    # Artifacts merged → will be persisted; workflow NOT marked failed.
    assert out["infra"]["artifacts"]["terraform_providers"]
    assert out.get("current_phase") not in ("terraform_failed", "terraform_validation_failed")
    assert out["terraform_failure_classification"] == NETWORK_ERROR


def test_node_flags_failed_on_validation_defect_but_keeps_artifacts():
    agent = _node_agent({
        "artifacts": dict(_TF_ARTIFACTS),
        "validation": {"status": "failed", "issues": [], "security_issues": []},
        "validation_status": "failed",
        "failure_classification": VALIDATION_FAILED,
        "terraform_outputs": {},
        "generated_artifacts": ["terraform/providers.tf"],
    })
    out = agent._terraform_phase_node(dict(_BASE_STATE))
    assert out["infra"]["artifacts"]["terraform_providers"]  # still kept
    assert out["current_phase"] == "terraform_validation_failed"
