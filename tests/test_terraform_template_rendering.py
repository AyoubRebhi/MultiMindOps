"""
Tests for the deterministic Terraform template engine.

These tests do not require the terraform / tfsec / checkov binaries — every
external tool is gracefully skipped by TerraformValidator. They cover:

* renderer template selection
* variable injection
* missing-variable detection
* strategy/template compatibility
* hcl2 syntax validation
* deterministic output equality
* multi-AZ + region propagation
* invalid architecture rejection
"""

from __future__ import annotations

import pytest

from backend.app.schemas.blueprint import InfrastructureBlueprint, parse_blueprint
from backend.app.services.terraform_generation import (
    TerraformTemplateRenderer,
    TerraformValidator,
)
from backend.app.services.terraform_generation.renderers.template_renderer import (
    MissingTemplateVariableError,
    TemplateCompatibilityError,
    TemplateSelectionError,
)


# ── Blueprint helpers ─────────────────────────────────────────────────────────


def _monolith_balanced() -> InfrastructureBlueprint:
    return parse_blueprint({
        "compute": {"type": "ECS", "instance_type": "t3.medium"},
        "database": {"engine": "PostgreSQL", "deployment": "RDS Multi-AZ"},
        "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
        "scaling": {"strategy": "vertical+horizontal", "auto_scaling": True},
        "storage": {"object_storage": "S3", "block_storage": "EBS"},
        "architecture_style": "monolith",
        "aws_region": "us-east-1",
        "strategy_tier": "balanced",
    })


def _monolith_low_cost() -> InfrastructureBlueprint:
    return parse_blueprint({
        "compute": {"type": "ECS", "instance_type": "t3.small"},
        "networking": {"vpc": True, "multi_az": False, "load_balancer": "ALB"},
        "scaling": {"strategy": "vertical", "auto_scaling": False},
        "storage": {"object_storage": "S3"},
        "architecture_style": "monolith",
        "aws_region": "us-east-1",
        "strategy_tier": "low_cost",
    })


def _microservices_balanced() -> InfrastructureBlueprint:
    return parse_blueprint({
        "compute": {
            "type": "EKS",
            "node_type": "t3.medium",
            "min_nodes": 2,
            "max_nodes": 5,
        },
        "database": {"engine": "PostgreSQL", "deployment": "RDS Multi-AZ"},
        "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
        "scaling": {"strategy": "horizontal", "auto_scaling": True},
        "storage": {"object_storage": "S3"},
        "architecture_style": "microservices",
        "aws_region": "eu-west-1",
        "strategy_tier": "balanced",
    })


def _serverless_balanced() -> InfrastructureBlueprint:
    return parse_blueprint({
        "compute": {"type": "Lambda", "runtime": "managed"},
        "networking": {"vpc": False, "multi_az": True, "load_balancer": "API Gateway"},
        "scaling": {"strategy": "fully_managed", "auto_scaling": True},
        "storage": {"object_storage": "S3"},
        "architecture_style": "serverless",
        "aws_region": "us-east-1",
        "strategy_tier": "balanced",
    })


# ── Renderer: template selection & rendering ─────────────────────────────────


def test_renderer_monolith_balanced_produces_all_files() -> None:
    renderer = TerraformTemplateRenderer()
    result = renderer.render(_monolith_balanced(), task_id="task-test-001")
    expected_keys = {
        "terraform_providers",
        "terraform_main",
        "terraform_variables",
        "terraform_tfvars",
        "terraform_outputs",
        "terraform_backend",
    }
    assert set(result.artifacts.keys()) == expected_keys
    for key, content in result.artifacts.items():
        assert content.strip(), f"Empty artifact: {key}"


def test_renderer_metadata_includes_strategy_and_family() -> None:
    renderer = TerraformTemplateRenderer()
    result = renderer.render(_monolith_balanced(), task_id="t1")
    assert result.metadata["artifact_type"] == "terraform"
    assert result.metadata["template_family"] == "monolith"
    assert result.metadata["strategy_tier"] == "balanced"
    assert result.metadata["render_mode"] == "deterministic_template"
    assert result.metadata["generated_by"] == "TerraformTemplateRenderer"


def test_renderer_microservices_emits_eks_resources() -> None:
    renderer = TerraformTemplateRenderer()
    result = renderer.render(_microservices_balanced(), task_id="t1")
    main_tf = result.artifacts["terraform_main"]
    assert "aws_eks_cluster" in main_tf
    assert "aws_eks_node_group" in main_tf
    # Variables file references node sizing
    assert "node_instance_type" in result.artifacts["terraform_variables"]


def test_renderer_serverless_emits_lambda_and_apigw() -> None:
    renderer = TerraformTemplateRenderer()
    result = renderer.render(_serverless_balanced(), task_id="t1")
    main_tf = result.artifacts["terraform_main"]
    assert "aws_lambda_function" in main_tf
    assert "aws_apigatewayv2_api" in main_tf


def test_renderer_outputs_contain_required_four_contract_keys() -> None:
    renderer = TerraformTemplateRenderer()
    for bp in (_monolith_balanced(), _microservices_balanced(), _serverless_balanced()):
        outputs = renderer.render(bp, task_id="t1").artifacts["terraform_outputs"]
        for required in ("cluster_endpoint", "cluster_name", "load_balancer_dns", "ecr_repository_url"):
            assert f'output "{required}"' in outputs, (
                f"{required} missing for {bp.architecture_style}/{bp.strategy_tier}"
            )


# ── Variable injection & deterministic output ────────────────────────────────


def test_tfvars_contains_blueprint_values() -> None:
    renderer = TerraformTemplateRenderer()
    bp = _microservices_balanced()
    tfvars = renderer.render(bp, task_id="t1").artifacts["terraform_tfvars"]
    assert 'aws_region           = "eu-west-1"' in tfvars
    assert 'strategy_tier        = "balanced"' in tfvars
    assert 'node_instance_type   = "t3.medium"' in tfvars
    assert "min_nodes            = 2" in tfvars
    assert "max_nodes            = 5" in tfvars


def test_rendering_is_deterministic_across_calls() -> None:
    """Same blueprint + task_id ⇒ byte-identical artifacts."""
    renderer = TerraformTemplateRenderer()
    bp = _monolith_balanced()
    r1 = renderer.render(bp, task_id="task-abc")
    r2 = renderer.render(bp, task_id="task-abc")
    assert r1.artifacts == r2.artifacts


def test_multi_az_propagation_renders_two_subnets() -> None:
    renderer = TerraformTemplateRenderer()
    tfvars = renderer.render(_monolith_balanced(), task_id="t1").artifacts["terraform_tfvars"]
    # Multi-AZ ⇒ exactly two public subnet CIDRs
    assert '["10.0.0.0/24", "10.0.1.0/24"]' in tfvars


def test_single_az_renders_one_subnet_for_low_cost() -> None:
    renderer = TerraformTemplateRenderer()
    tfvars = renderer.render(_monolith_low_cost(), task_id="t1").artifacts["terraform_tfvars"]
    assert '["10.0.0.0/24"]' in tfvars


def test_aws_region_propagation() -> None:
    renderer = TerraformTemplateRenderer()
    # Different region pinned in blueprint surfaces in tfvars
    tfvars = renderer.render(_microservices_balanced(), task_id="t1").artifacts["terraform_tfvars"]
    assert 'aws_region           = "eu-west-1"' in tfvars


# ── Template compatibility errors ────────────────────────────────────────────


def test_high_performance_without_multi_az_rejected() -> None:
    """Schema allows it (Pydantic doesn't cross-validate), renderer rejects it."""
    bp = parse_blueprint({
        "compute": {"type": "ECS", "instance_type": "m5.large"},
        "networking": {"vpc": True, "multi_az": False, "load_balancer": "ALB"},
        "scaling": {"strategy": "horizontal", "auto_scaling": True},
        "storage": {"object_storage": "S3"},
        "architecture_style": "monolith",
        "aws_region": "us-east-1",
        "strategy_tier": "high_performance",
    })
    # high_performance template does not exist yet — we expect the renderer
    # to bail with TemplateSelectionError OR TemplateCompatibilityError. Either
    # is correct; both prevent a non-multi-AZ high_performance deploy.
    renderer = TerraformTemplateRenderer()
    with pytest.raises((TemplateCompatibilityError, TemplateSelectionError)):
        renderer.render(bp, task_id="t1")


def test_missing_template_set_raises_selection_error() -> None:
    """high_performance templates not yet implemented — must raise loudly."""
    bp = parse_blueprint({
        "compute": {"type": "ECS", "instance_type": "m5.large"},
        "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
        "scaling": {"strategy": "horizontal", "auto_scaling": True},
        "storage": {"object_storage": "S3"},
        "architecture_style": "monolith",
        "aws_region": "us-east-1",
        "strategy_tier": "high_performance",
    })
    renderer = TerraformTemplateRenderer()
    with pytest.raises(TemplateSelectionError) as exc:
        renderer.render(bp, task_id="t1")
    assert "high_performance" in str(exc.value) or "monolith" in str(exc.value)


def test_renderer_lists_available_template_sets_on_missing() -> None:
    bp = parse_blueprint({
        "compute": {"type": "EKS", "node_type": "t3.medium", "min_nodes": 2, "max_nodes": 5},
        "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
        "scaling": {"strategy": "horizontal", "auto_scaling": True},
        "storage": {"object_storage": "S3"},
        "architecture_style": "microservices",
        "aws_region": "us-east-1",
        "strategy_tier": "low_cost",  # not yet implemented
    })
    renderer = TerraformTemplateRenderer()
    with pytest.raises(TemplateSelectionError) as exc:
        renderer.render(bp, task_id="t1")
    assert "available" in exc.value.metadata


# ── Validation pipeline (graceful tool detection) ────────────────────────────


def test_validator_runs_with_no_external_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    On a developer workstation without terraform / tfsec / checkov binaries
    installed, the pipeline must still complete and report `skipped` for
    each unavailable validator — not crash, not report false success.
    """
    renderer = TerraformTemplateRenderer()
    artifacts = renderer.render(_monolith_balanced(), task_id="t1").artifacts

    # Force subprocess validators to be skipped to keep the test hermetic.
    validator = TerraformValidator(skip_subprocess_validators=True)
    result = validator.validate(artifacts)

    # hcl2_parse may or may not be available; both are fine for this test.
    assert result.validators_run.get("terraform_fmt") == "skipped"
    assert result.validators_run.get("terraform_init") == "skipped"
    assert result.validators_run.get("terraform_validate") == "skipped"
    assert result.validators_run.get("tfsec") == "skipped"
    assert result.validators_run.get("checkov") == "skipped"
    # No issues raised → not blocking
    assert not result.is_blocking


def test_validator_blocks_on_broken_hcl() -> None:
    """A deliberately broken artifact should fail hcl2 parsing if available."""
    try:
        import hcl2  # noqa: F401  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("python-hcl2 not installed in this environment")

    broken = {
        "terraform_main": 'resource "aws_vpc" "x" { cidr_block = "10.0.0.0/16"',  # missing closing brace
    }
    validator = TerraformValidator(skip_subprocess_validators=True)
    result = validator.validate(broken)
    assert result.status == "failed"
    assert result.is_blocking


# ── Three strategies produce three different outputs ─────────────────────────


def test_three_strategies_produce_distinct_rendered_outputs() -> None:
    """The whole reason this stack exists — strategies must diverge."""
    renderer = TerraformTemplateRenderer()
    low = renderer.render(_monolith_low_cost(), task_id="t1").artifacts["terraform_tfvars"]
    bal = renderer.render(_monolith_balanced(), task_id="t1").artifacts["terraform_tfvars"]

    assert low != bal
    # low_cost is single-AZ, balanced is multi-AZ
    assert low.count("10.0.") < bal.count("10.0.")


def test_serverless_outputs_provide_empty_ecr_for_contract_compatibility() -> None:
    renderer = TerraformTemplateRenderer()
    outputs = renderer.render(_serverless_balanced(), task_id="t1").artifacts["terraform_outputs"]
    # ecr_repository_url is required by the contract even when serverless
    # doesn't need ECR — it must be present with an empty string value.
    assert 'output "ecr_repository_url"' in outputs
    assert 'value       = ""' in outputs


# ── Backend.tf is always deterministic ───────────────────────────────────────


def test_backend_tf_is_always_machine_emitted() -> None:
    renderer = TerraformTemplateRenderer()
    result = renderer.render(_monolith_balanced(), task_id="task-xyz-7")
    backend = result.artifacts["terraform_backend"]
    # Either a real backend (when env vars set) or the explicit placeholder —
    # never an LLM-produced HCL block.
    assert "AUTO-GENERATED" in backend or "placeholder" in backend


# ── Missing template variable detection ──────────────────────────────────────


def test_missing_template_variable_raises(tmp_path) -> None:
    """
    Render against a temp template that references an undeclared variable.
    StrictUndefined must raise MissingTemplateVariableError.
    """
    arch_dir = tmp_path / "monolith" / "balanced"
    arch_dir.mkdir(parents=True)
    # Minimal template set, with main.tf referencing a non-existent variable.
    (arch_dir / "providers.tf.j2").write_text("# providers\n")
    (arch_dir / "variables.tf.j2").write_text("# vars\n")
    (arch_dir / "terraform.tfvars.j2").write_text("# tfvars\n")
    (arch_dir / "main.tf.j2").write_text('resource "x" "y" { foo = "{{ never_declared }}" }\n')
    (arch_dir / "outputs.tf.j2").write_text("# outputs\n")

    renderer = TerraformTemplateRenderer(templates_root=tmp_path)
    with pytest.raises(MissingTemplateVariableError) as exc:
        renderer.render(_monolith_balanced(), task_id="t1")
    assert "never_declared" in str(exc.value) or "never_declared" in str(exc.value.metadata)
