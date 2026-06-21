"""
Tests for centralized AWS resource-name sanitization (TASK 1).

Covers the failure ``terraform plan`` surfaced — UUID project IDs (~36 chars)
made ``"${project_name}-alb"`` / ``"-tg"`` overflow AWS's 32-char ALB/Target-
Group ceiling — at three levels:

  1. the pure helper (sanitize_aws_name / sanitize_resource_name)
  2. the variable context (_build_resource_names) for a UUID project
  3. the rendered templates (every constrained name fits its ceiling)
"""

from __future__ import annotations

import re

import pytest

from backend.app.schemas.blueprint import parse_blueprint
from backend.app.services.terraform_generation import TerraformTemplateRenderer
from backend.app.services.terraform_generation.utils.naming import (
    AWS_NAME_LIMITS,
    sanitize_aws_name,
    sanitize_resource_name,
)
from backend.app.services.terraform_generation.utils.variable_context import (
    _build_resource_names,
)

# A realistic offender: a project UUID (36 chars including dashes).
UUID_PROJECT = "d052a0f7-144f-4f90-9bf8-43e53dd685d1"

_VALID_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _assert_valid(name: str, max_length: int) -> None:
    assert name, "name must be non-empty"
    assert len(name) <= max_length, f"{name!r} exceeds {max_length}"
    assert _VALID_NAME_RE.match(name), f"{name!r} is not a valid AWS name"
    assert not name.endswith("-"), f"{name!r} ends with a hyphen"
    assert "--" not in name, f"{name!r} has consecutive hyphens"


# ── Helper: the documented example ───────────────────────────────────────────


def test_example_uuid_alb_fits_32() -> None:
    """The exact case from the task: sanitize(uuid, '-alb', 32) <= 32."""
    name = sanitize_aws_name("d052a-f714-4f90-9bf8-43e53dd685d", "-alb", 32)
    _assert_valid(name, 32)
    assert name.endswith("-alb")


def test_suffix_is_always_preserved_within_ceiling() -> None:
    for suffix in ("-alb", "-tg", "-ecs-task-execution", "-db"):
        name = sanitize_aws_name(UUID_PROJECT, suffix, 32)
        _assert_valid(name, 32)
        assert name.endswith(suffix), f"{name!r} dropped suffix {suffix!r}"


def test_short_base_is_not_hashed() -> None:
    """A base that already fits keeps its readable form (no hash noise)."""
    assert sanitize_aws_name("myapp", "-alb", 32) == "myapp-alb"
    assert sanitize_resource_name("myapp", 32) == "myapp"


def test_truncation_preserves_uniqueness() -> None:
    """Two distinct long bases that share a long prefix must not collide."""
    a = "my-really-long-project-name-prod-alpha"
    b = "my-really-long-project-name-prod-bravo"
    na = sanitize_aws_name(a, "-alb", 32)
    nb = sanitize_aws_name(b, "-alb", 32)
    _assert_valid(na, 32)
    _assert_valid(nb, 32)
    assert na != nb, "truncated names collided — uniqueness not preserved"


def test_deterministic() -> None:
    assert sanitize_aws_name(UUID_PROJECT, "-alb", 32) == sanitize_aws_name(
        UUID_PROJECT, "-alb", 32
    )


def test_leading_digit_and_garbage_are_coerced() -> None:
    _assert_valid(sanitize_aws_name("123-456-789", "-alb", 32), 32)
    _assert_valid(sanitize_aws_name("!!!", "-alb", 32, fallback="app"), 32)
    # Nothing usable in base OR suffix → fallback, still valid.
    assert sanitize_resource_name("", 32, fallback="devsecops") == "devsecops"


def test_uppercase_is_lowercased() -> None:
    assert sanitize_aws_name("MyApp", "-ALB", 32) == "myapp-alb"


# ── Variable context: every derived name fits its resource ceiling ───────────

# Map each context key to the resource ceiling it must respect.
_NAME_KEY_LIMITS = {
    "alb_name": AWS_NAME_LIMITS["alb"],
    "target_group_name": AWS_NAME_LIMITS["target_group"],
    "ecr_repository_name": AWS_NAME_LIMITS["ecr_repository"],
    "ecs_cluster_name": AWS_NAME_LIMITS["ecs_cluster"],
    "ecs_service_name": AWS_NAME_LIMITS["ecs_service"],
    "ecs_task_family": AWS_NAME_LIMITS["ecs_task_family"],
    "ecs_task_execution_role_name": AWS_NAME_LIMITS["iam_role"],
    "rds_identifier": AWS_NAME_LIMITS["rds_instance"],
    "db_subnet_group_name": AWS_NAME_LIMITS["db_subnet_group"],
    "eks_cluster_name": AWS_NAME_LIMITS["eks_cluster"],
    "eks_cluster_role_name": AWS_NAME_LIMITS["iam_role"],
    "eks_node_role_name": AWS_NAME_LIMITS["iam_role"],
    "eks_node_group_name": AWS_NAME_LIMITS["eks_node_group"],
    "lambda_function_name": AWS_NAME_LIMITS["lambda_function"],
    "lambda_role_name": AWS_NAME_LIMITS["iam_role"],
    "apigw_name": AWS_NAME_LIMITS["apigateway"],
    "lambda_code_bucket_name": AWS_NAME_LIMITS["s3_bucket"],
}


def test_build_resource_names_all_within_limits_for_uuid_project() -> None:
    # _build_resource_names receives the already-sanitized 32-char project name.
    from backend.app.services.terraform_generation.utils.variable_context import (
        _normalize_project_name,
    )

    project = _normalize_project_name(UUID_PROJECT, None)
    names = _build_resource_names(project)
    assert set(_NAME_KEY_LIMITS).issubset(names), "missing a derived name key"
    for key, limit in _NAME_KEY_LIMITS.items():
        _assert_valid(names[key], limit)


# ── Rendered templates: constrained names fit + old overflow pattern gone ────


def _blueprint(arch: str, tier: str = "balanced"):
    base = {
        "monolith": {
            "compute": {"type": "ECS", "instance_type": "t3.medium"},
            "database": {"engine": "PostgreSQL", "deployment": "RDS Multi-AZ"},
            "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
            "scaling": {"strategy": "vertical+horizontal", "auto_scaling": True},
            "storage": {"object_storage": "S3", "block_storage": "EBS"},
        },
        "microservices": {
            "compute": {"type": "EKS", "node_type": "t3.medium", "min_nodes": 2, "max_nodes": 5},
            "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
            "scaling": {"strategy": "horizontal", "auto_scaling": True},
            "storage": {"object_storage": "S3"},
        },
        "serverless": {
            "compute": {"type": "Lambda", "runtime": "managed"},
            "networking": {"vpc": False, "multi_az": True, "load_balancer": "API Gateway"},
            "scaling": {"strategy": "fully_managed", "auto_scaling": True},
            "storage": {"object_storage": "S3"},
        },
    }[arch]
    return parse_blueprint({**base, "architecture_style": arch, "aws_region": "us-east-1", "strategy_tier": tier})


def _resource_arg(main_tf: str, resource_type: str, arg: str = "name") -> str | None:
    """Extract a top-level resource's ``arg = "literal"`` value (None if absent).

    The templates emit flat resources whose closing brace sits at column 0, so a
    non-greedy match up to ``\\n}`` captures exactly one resource block.
    """
    block = re.search(
        r'resource\s+"' + re.escape(resource_type) + r'"\s+"[^"]+"\s*\{(.*?)\n\}',
        main_tf,
        re.DOTALL,
    )
    if not block:
        return None
    m = re.search(arg + r'\s*=\s*"([^"$]+)"', block.group(1))
    return m.group(1) if m else None


# Per-architecture: (resource_type, arg, ceiling) for the length-constrained
# names. Each must be a literal (no `${var...}` overflow) within its ceiling.
_RENDER_EXPECTATIONS = {
    ("monolith", "low_cost"): [
        ("aws_lb", "name", AWS_NAME_LIMITS["alb"]),
        ("aws_lb_target_group", "name", AWS_NAME_LIMITS["target_group"]),
        ("aws_ecr_repository", "name", AWS_NAME_LIMITS["ecr_repository"]),
        ("aws_ecs_cluster", "name", AWS_NAME_LIMITS["ecs_cluster"]),
        ("aws_iam_role", "name", AWS_NAME_LIMITS["iam_role"]),
        ("aws_ecs_service", "name", AWS_NAME_LIMITS["ecs_service"]),
    ],
    ("monolith", "balanced"): [
        ("aws_lb", "name", AWS_NAME_LIMITS["alb"]),
        ("aws_lb_target_group", "name", AWS_NAME_LIMITS["target_group"]),
        ("aws_db_instance", "identifier", AWS_NAME_LIMITS["rds_instance"]),
        ("aws_db_subnet_group", "name", AWS_NAME_LIMITS["db_subnet_group"]),
    ],
    ("microservices", "balanced"): [
        ("aws_eks_cluster", "name", AWS_NAME_LIMITS["eks_cluster"]),
        ("aws_eks_node_group", "node_group_name", AWS_NAME_LIMITS["eks_node_group"]),
        ("aws_ecr_repository", "name", AWS_NAME_LIMITS["ecr_repository"]),
    ],
    ("serverless", "balanced"): [
        ("aws_lambda_function", "function_name", AWS_NAME_LIMITS["lambda_function"]),
        ("aws_s3_bucket", "bucket", AWS_NAME_LIMITS["s3_bucket"]),
        ("aws_apigatewayv2_api", "name", AWS_NAME_LIMITS["apigateway"]),
    ],
}


@pytest.mark.parametrize("arch,tier", list(_RENDER_EXPECTATIONS))
def test_rendered_constrained_names_fit_for_uuid_project(arch, tier) -> None:
    renderer = TerraformTemplateRenderer()
    # task_id is the UUID — the worst case that triggered the plan failure.
    main_tf = renderer.render(
        _blueprint(arch, tier), task_id=UUID_PROJECT
    ).artifacts["terraform_main"]

    # The overflow-prone HCL suffixing of project_name must be gone for the
    # 32-char-ceiling ALB / Target Group.
    assert '"${var.project_name}-alb"' not in main_tf
    assert '"${var.project_name}-tg"' not in main_tf

    for resource_type, arg, ceiling in _RENDER_EXPECTATIONS[(arch, tier)]:
        value = _resource_arg(main_tf, resource_type, arg)
        assert value is not None, f"{resource_type}.{arg} not found in rendered main.tf"
        assert "${" not in value, f"{resource_type}.{arg} still interpolates a variable"
        _assert_valid(value, ceiling)
