"""
Regression tests for the architecture-audit P0 findings:

* R1 — Blueprint shape drift between PlannerAgent and TerraformAgent
* R2 — plan_id / strategy_tier loss in resume_with_selected_plan

These tests must fail on the pre-refactor code and pass on the refactored code.
"""

from __future__ import annotations

import pytest

from backend.app.agents.errors import BlueprintContractError, PlanPropagationError
from backend.app.schemas.blueprint import (
    InfrastructureBlueprint,
    parse_blueprint,
)


# ── Fixtures: blueprints in the shape PlannerAgent actually emits ─────────────


def _monolith_blueprint() -> dict:
    return {
        "compute": {"type": "ECS", "instance_type": "t3.medium"},
        "database": {"engine": "PostgreSQL", "deployment": "RDS Multi-AZ"},
        "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
        "scaling": {"strategy": "vertical+horizontal", "auto_scaling": True},
        "storage": {"object_storage": "S3", "block_storage": "EBS"},
        "architecture_style": "monolith",
        "aws_region": "us-east-1",
    }


def _microservices_blueprint() -> dict:
    return {
        "compute": {
            "type": "EKS",
            "node_type": "t3.medium",
            "min_nodes": 2,
            "max_nodes": 5,
        },
        "database": {"engine": "PostgreSQL", "deployment": "RDS Multi-AZ"},
        "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
        "scaling": {"strategy": "horizontal", "auto_scaling": True},
        "storage": {"object_storage": "S3", "block_storage": "EBS"},
        "architecture_style": "microservices",
        "aws_region": "eu-west-1",
    }


def _serverless_blueprint() -> dict:
    return {
        "compute": {"type": "Lambda", "runtime": "managed"},
        "networking": {"vpc": False, "multi_az": True, "load_balancer": "API Gateway"},
        "scaling": {"strategy": "fully_managed", "auto_scaling": True},
        "storage": {"object_storage": "S3"},
        "architecture_style": "serverless",
    }


# ── R1: typed blueprint contract ──────────────────────────────────────────────


def test_monolith_blueprint_parses() -> None:
    bp = parse_blueprint(_monolith_blueprint())
    assert isinstance(bp, InfrastructureBlueprint)
    assert bp.compute.type == "ECS"
    assert bp.compute.effective_instance_type == "t3.medium"
    assert bp.networking.multi_az is True
    assert bp.is_multi_az is True
    assert bp.aws_region == "us-east-1"


def test_microservices_blueprint_parses_and_exposes_node_sizing() -> None:
    bp = parse_blueprint(_microservices_blueprint())
    assert bp.terraform_architecture_type == "eks"
    assert bp.compute.effective_instance_type == "t3.medium"
    assert bp.compute.min_nodes == 2
    assert bp.compute.max_nodes == 5


def test_serverless_blueprint_parses() -> None:
    bp = parse_blueprint(_serverless_blueprint())
    assert bp.terraform_architecture_type == "serverless"
    assert bp.compute.type == "Lambda"


def test_eks_without_min_nodes_rejected() -> None:
    """The exact silent-default bug TerraformAgent used to mask."""
    bad = _microservices_blueprint()
    bad["compute"].pop("min_nodes")
    with pytest.raises(BlueprintContractError) as exc:
        parse_blueprint(bad)
    assert "min_nodes" in str(exc.value).lower() or "min_nodes" in str(exc.value.metadata)


def test_invalid_aws_region_rejected() -> None:
    bad = _monolith_blueprint()
    bad["aws_region"] = "us_east_1"  # underscore instead of hyphen
    with pytest.raises(BlueprintContractError):
        parse_blueprint(bad)


def test_architecture_style_compute_mismatch_rejected() -> None:
    """serverless + ECS is incoherent — must be caught at the boundary."""
    bad = _serverless_blueprint()
    bad["compute"] = {"type": "ECS", "instance_type": "t3.medium"}
    with pytest.raises(BlueprintContractError):
        parse_blueprint(bad)


def test_legacy_keys_no_longer_silently_accepted() -> None:
    """
    Pre-refactor TerraformAgent read top-level ``compute_type`` and
    ``instance_type`` directly on the blueprint. The new contract requires
    these to live under ``compute.{type,instance_type}``. A payload that
    only has the legacy top-level keys must be rejected, not silently
    defaulted.
    """
    legacy = {
        "compute_type": "ECS",          # was used by TerraformAgent
        "instance_type": "t3.medium",   # was used by TerraformAgent
        "architecture_type": "monolith",
        "aws_region": "us-east-1",
    }
    with pytest.raises(BlueprintContractError):
        parse_blueprint(legacy)


# ── R2: strategy_tier propagation ────────────────────────────────────────────


def test_blueprint_carries_strategy_tier() -> None:
    raw = _monolith_blueprint()
    raw["strategy_tier"] = "high_performance"
    bp = parse_blueprint(raw)
    assert bp.strategy_tier == "high_performance"


def test_invalid_strategy_tier_rejected() -> None:
    raw = _monolith_blueprint()
    raw["strategy_tier"] = "ludicrous_speed"
    with pytest.raises(BlueprintContractError):
        parse_blueprint(raw)


def test_resume_with_selected_plan_stamps_tier_on_plan() -> None:
    """
    Direct test of the orchestrator fix. Builds a minimal state with three
    enriched plans (mirroring ArchitectureDecisionAgent output), calls
    resume_with_selected_plan, and asserts that:

    * state["plan"]["strategy_tier"] is set
    * state["plan"]["plan_id"]       is set
    * state["selected_plan_id"]      is set
    * approved_artifacts propagated  from the strategy's required_artifacts
    """
    from backend.app.agents.orchestrator_agent import OrchestratorAgent

    monolith = _monolith_blueprint()
    monolith["strategy_tier"] = "balanced"

    arch_decision = {
        "plans": [
            {
                "id": "low_cost",
                "plan": {"infrastructure_blueprint": _monolith_blueprint()},
                "monthly_cost": 30.0,
                "required_artifacts": ["terraform/providers.tf"],
            },
            {
                "id": "balanced",
                "plan": {"infrastructure_blueprint": monolith},
                "monthly_cost": 80.0,
                "required_artifacts": ["terraform/providers.tf", "Dockerfile"],
            },
            {
                "id": "high_performance",
                "plan": {"infrastructure_blueprint": _monolith_blueprint()},
                "monthly_cost": 250.0,
                "required_artifacts": ["terraform/providers.tf"],
            },
        ],
        "recommended_plan": "balanced",
    }

    orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)  # skip __init__
    # resume_with_selected_plan does not touch self, only state — safe.
    result = orchestrator.resume_with_selected_plan(
        prior_state={"architecture_decision": arch_decision, "logs": []},
        selected_plan_id="balanced",
    )

    assert result["selected_plan_id"] == "balanced"
    assert result["plan"]["plan_id"] == "balanced"
    assert result["plan"]["strategy_tier"] == "balanced"
    assert result["plan"]["approved_artifacts"] == [
        "terraform/providers.tf",
        "Dockerfile",
    ]
    assert result["approved_artifacts"] == ["terraform/providers.tf", "Dockerfile"]
    assert result["current_phase"] == "planning_complete"


def test_resume_with_unknown_plan_raises_propagation_error() -> None:
    from backend.app.agents.orchestrator_agent import OrchestratorAgent

    orchestrator = OrchestratorAgent.__new__(OrchestratorAgent)
    with pytest.raises(PlanPropagationError) as exc:
        orchestrator.resume_with_selected_plan(
            prior_state={
                "architecture_decision": {"plans": [{"id": "balanced", "plan": {}}]},
                "logs": [],
            },
            selected_plan_id="does_not_exist",
        )
    assert exc.value.code == "plan_propagation_failed"
    assert "does_not_exist" in str(exc.value)


# ── R1+R2 integration: differentiated outputs across tiers ───────────────────


def test_three_strategies_produce_distinct_compute_configs() -> None:
    """
    The whole point of low_cost / balanced / high_performance is that the
    Terraform output differs. Pre-refactor, all three tiers fed TerraformAgent
    identical default values because of R1+R2. This test pins that fixed.
    """
    low = _monolith_blueprint()
    low["compute"]["instance_type"] = "t3.small"
    low["networking"]["multi_az"] = False
    low["strategy_tier"] = "low_cost"

    balanced = _monolith_blueprint()
    balanced["strategy_tier"] = "balanced"
    # multi_az already True, t3.medium

    high = _monolith_blueprint()
    high["compute"]["instance_type"] = "m5.large"
    high["networking"]["multi_az"] = True
    high["strategy_tier"] = "high_performance"

    bp_low = parse_blueprint(low)
    bp_bal = parse_blueprint(balanced)
    bp_high = parse_blueprint(high)

    assert bp_low.compute.effective_instance_type == "t3.small"
    assert bp_bal.compute.effective_instance_type == "t3.medium"
    assert bp_high.compute.effective_instance_type == "m5.large"

    assert bp_low.is_multi_az is False
    assert bp_bal.is_multi_az is True
    assert bp_high.is_multi_az is True

    # The strategy tier survives the contract round-trip — this is the
    # field that resume_with_selected_plan used to drop.
    assert bp_low.strategy_tier == "low_cost"
    assert bp_bal.strategy_tier == "balanced"
    assert bp_high.strategy_tier == "high_performance"
