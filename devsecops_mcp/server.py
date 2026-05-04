"""
DevSecOps MCP Server

Exposes structured Terraform, Kubernetes, and AWS infrastructure schemas
as MCP resources and callable tools for LLM-backed DevSecOps agents.

Transport: stdio (initial) — upgradeable to HTTP/SSE
Usage:     python -m devsecops_mcp.server   OR   python devsecops_mcp/server.py

Resources exposed:
  aws://terraform/resource/{resource_name}   — Terraform resource schema + example HCL
  aws://terraform/backend/{backend_type}     — Terraform backend configuration
  aws://terraform/catalog                    — List of available resources
  aws://kubernetes/template/{template_name}  — Kubernetes manifest template
  aws://best-practices/{category}            — AWS architecture best practices

Tools exposed:
  validate_terraform_code(hcl)              — Syntax + security validation
  suggest_terraform_fix(hcl)                — Actionable fix recommendations
  explain_resource(resource_name)            — Detailed resource explanation
  generate_minimal_example(resource_name)   — Minimal working HCL snippet
  get_architecture_template(arch_type)      — Full EKS/ECS/serverless template
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Ensure project root on path when running as __main__ ──────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Local imports ─────────────────────────────────────────────────────────────
from devsecops_mcp.resources.terraform_resources import (
    load_terraform_resource,
    list_terraform_resources,
    get_all_terraform_resources,
)
from devsecops_mcp.resources.kubernetes_resources import (
    load_kubernetes_template,
    list_kubernetes_templates,
)
from devsecops_mcp.resources.aws_resources import load_aws_best_practices
from devsecops_mcp.tools.terraform_tools import (
    validate_hcl,
    suggest_fixes,
    explain_terraform_resource,
)

# ── MCP server init ───────────────────────────────────────────────────────────
try:
    from mcp.server.fastmcp import FastMCP  # type: ignore

    mcp = FastMCP(
        "devsecops-terraform-mcp",
        instructions=(
            "Provides structured Terraform HCL schemas, Kubernetes deployment templates, "
            "and AWS Well-Architected best practices for infrastructure code generation. "
            "Resources supply high-precision, schema-level context. "
            "Tools validate code and generate working examples."
        ),
    )
    _FASTMCP_AVAILABLE = True
except ImportError:
    _FASTMCP_AVAILABLE = False
    logger.warning("FastMCP not available — falling back to low-level Server API")


# ═══════════════════════════════════════════════════════════════════════════════
#  RESOURCES
# ═══════════════════════════════════════════════════════════════════════════════

if _FASTMCP_AVAILABLE:

    @mcp.resource("aws://terraform/resource/{resource_name}")
    async def get_terraform_resource(resource_name: str) -> str:
        """Get structured Terraform resource schema, arguments, example HCL, and best practices."""
        data = load_terraform_resource(resource_name)
        if not data:
            available = list_terraform_resources()
            return json.dumps({
                "error": f"Resource '{resource_name}' not found",
                "available_resources": available,
            })
        return explain_terraform_resource(resource_name, data)

    @mcp.resource("aws://terraform/backend/{backend_type}")
    async def get_terraform_backend(backend_type: str) -> str:
        """Get Terraform backend configuration schema and examples (e.g., s3)."""
        data = load_terraform_resource(f"backend_{backend_type}")
        if not data:
            return json.dumps({"error": f"Backend type '{backend_type}' not found"})
        return explain_terraform_resource(f"backend_{backend_type}", data)

    @mcp.resource("aws://terraform/catalog")
    async def list_terraform_catalog() -> str:
        """List all available Terraform resource schemas in this MCP server."""
        resources = list_terraform_resources()
        return json.dumps({
            "count": len(resources),
            "resources": resources,
            "usage": "Call aws://terraform/resource/{resource_name} to get details",
        }, indent=2)

    @mcp.resource("aws://kubernetes/template/{template_name}")
    async def get_kubernetes_template(template_name: str) -> str:
        """Get a Kubernetes manifest template with schema and production best practices."""
        data = load_kubernetes_template(template_name)
        if not data:
            available = list_kubernetes_templates()
            return json.dumps({
                "error": f"Template '{template_name}' not found",
                "available_templates": available,
            })
        return _format_kubernetes_resource(template_name, data)

    @mcp.resource("aws://best-practices/{category}")
    async def get_aws_best_practices(category: str) -> str:
        """Get AWS Well-Architected best practices for a given category."""
        data = load_aws_best_practices(category)
        if not data:
            return json.dumps({"error": f"Category '{category}' not found"})
        return json.dumps(data, indent=2)

    # ── Tools ─────────────────────────────────────────────────────────────────

    @mcp.tool()
    async def validate_terraform_code(hcl: str) -> str:
        """
        Validate Terraform HCL code for syntax errors, security issues, and best practice violations.

        Args:
            hcl: Terraform HCL code string to validate

        Returns:
            JSON object with keys: valid, score, issues, warnings, summary
        """
        result = validate_hcl(hcl)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def suggest_terraform_fix(hcl: str) -> str:
        """
        Analyze Terraform HCL issues and return structured, actionable fix recommendations.

        Args:
            hcl: Terraform HCL code with potential issues

        Returns:
            JSON with original_validation, fixes (list of {severity, issue, fix, example}), fix_count
        """
        result = suggest_fixes(hcl)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def explain_resource(resource_name: str) -> str:
        """
        Get a detailed, LLM-optimized explanation of a Terraform AWS resource type.

        Args:
            resource_name: AWS Terraform resource type (e.g., aws_vpc, aws_iam_role, aws_eks_cluster)

        Returns:
            Formatted string with description, required/optional args, example HCL, best practices
        """
        data = load_terraform_resource(resource_name)
        if not data:
            available = list_terraform_resources()
            return json.dumps({"error": f"Resource '{resource_name}' not found", "available": available})
        return explain_terraform_resource(resource_name, data)

    @mcp.tool()
    async def generate_minimal_example(resource_name: str) -> str:
        """
        Generate a minimal but complete, working HCL example for a Terraform resource.

        Args:
            resource_name: AWS Terraform resource type (e.g., aws_vpc, aws_security_group)

        Returns:
            JSON with resource name, minimal_hcl, description, and required_args list
        """
        data = load_terraform_resource(resource_name)
        if not data:
            return json.dumps({"error": f"Resource '{resource_name}' not found"})

        return json.dumps({
            "resource": resource_name,
            "minimal_hcl": data.get("minimal_example") or data.get("example_hcl", ""),
            "description": data.get("description", ""),
            "required_args": [a["name"] for a in data.get("arguments", {}).get("required", [])],
            "category": data.get("category", ""),
        }, indent=2)

    @mcp.tool()
    async def get_architecture_template(architecture_type: str) -> str:
        """
        Get a complete Terraform architecture template with file structure guidance.

        Args:
            architecture_type: One of 'eks', 'ecs', 'serverless'

        Returns:
            JSON with architecture type, required files, resources to create, and key considerations
        """
        templates = {
            "eks": _build_eks_template_guide(),
            "ecs": _build_ecs_template_guide(),
            "serverless": _build_serverless_template_guide(),
        }

        if architecture_type not in templates:
            return json.dumps({
                "error": f"Unknown architecture type: {architecture_type}",
                "available": list(templates.keys()),
            })
        return json.dumps(templates[architecture_type], indent=2)


# ═══════════════════════════════════════════════════════════════════════════════
#  FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def _format_kubernetes_resource(name: str, data: dict[str, Any]) -> str:
    lines = [
        f"=== KUBERNETES TEMPLATE: {name.upper()} ===",
        "",
        f"API Version: {data.get('api_version', 'apps/v1')}",
        f"Kind: {data.get('kind', name.title())}",
        "",
        "Description:",
        data.get("description", ""),
        "",
    ]

    if data.get("template_yaml"):
        lines += ["Template YAML:", "```yaml", data["template_yaml"], "```", ""]

    bps = data.get("best_practices", [])
    if bps:
        lines.append("Best Practices:")
        for bp in bps:
            lines.append(f"  ✓ {bp}")
        lines.append("")

    sec = data.get("security_notes", [])
    if sec:
        lines.append("Security Notes:")
        for note in sec:
            lines.append(f"  ⚠ {note}")
        lines.append("")

    related = data.get("related_resources", [])
    if related:
        lines.append(f"Related Resources: {', '.join(related)}")

    return "\n".join(lines)


def _build_eks_template_guide() -> dict[str, Any]:
    eks_data = load_terraform_resource("aws_eks_cluster") or {}
    vpc_data = load_terraform_resource("aws_vpc") or {}
    ecr_data = load_terraform_resource("aws_ecr_repository") or {}
    alb_data = load_terraform_resource("aws_alb") or {}

    return {
        "architecture": "eks",
        "description": "Complete EKS cluster on AWS with VPC, private/public subnets, ECR, and ALB",
        "required_files": {
            "providers.tf": "AWS provider with version ~> 5.0, kubernetes provider",
            "backend.tf": "S3 remote state with DynamoDB locking",
            "vpc.tf": "VPC, public/private subnets (2 AZs min), IGW, NAT gateway, route tables",
            "security_groups.tf": "Separate SGs for ALB, EKS cluster, EKS nodes",
            "iam.tf": "EKS cluster role, node group role with required policy attachments",
            "eks.tf": "aws_eks_cluster + aws_eks_node_group (private subnets, t3.medium)",
            "ecr.tf": "aws_ecr_repository with IMMUTABLE tags and scan_on_push",
            "alb.tf": "aws_lb (public subnets), target group (ip type), HTTPS listener",
            "variables.tf": "project_name, environment, aws_region, kubernetes_version, node config",
            "terraform.tfvars": "Default values for non-sensitive variables",
            "outputs.tf": "cluster_endpoint, cluster_name, load_balancer_dns, ecr_repository_url",
        },
        "mandatory_outputs": ["cluster_endpoint", "cluster_name", "load_balancer_dns", "ecr_repository_url"],
        "key_resources": ["aws_vpc", "aws_eks_cluster", "aws_eks_node_group", "aws_ecr_repository", "aws_lb"],
        "vpc_example": vpc_data.get("example_hcl", ""),
        "eks_example": eks_data.get("example_hcl", ""),
        "ecr_example": ecr_data.get("example_hcl", ""),
        "alb_example": alb_data.get("example_hcl", ""),
        "cost_optimization": [
            "Use t3.medium nodes for dev, t3.large for prod",
            "Single NAT gateway per VPC for non-prod",
            "FARGATE_SPOT for non-critical workloads",
        ],
    }


def _build_ecs_template_guide() -> dict[str, Any]:
    ecs_data = load_terraform_resource("aws_ecs_cluster") or {}
    vpc_data = load_terraform_resource("aws_vpc") or {}

    return {
        "architecture": "ecs",
        "description": "ECS Fargate cluster with VPC, ALB, and ECR — simpler than EKS for monolithic apps",
        "required_files": {
            "providers.tf": "AWS provider with version ~> 5.0",
            "backend.tf": "S3 remote state with DynamoDB locking",
            "vpc.tf": "VPC, public/private subnets, IGW, NAT gateway",
            "security_groups.tf": "ALB SG (ports 80/443), ECS tasks SG (container port from ALB only)",
            "iam.tf": "ECS execution role (AmazonECSTaskExecutionRolePolicy), task role",
            "ecs.tf": "aws_ecs_cluster, aws_ecs_task_definition (Fargate), aws_ecs_service",
            "ecr.tf": "aws_ecr_repository with lifecycle policy",
            "alb.tf": "aws_lb, aws_lb_target_group (target_type=ip), HTTPS listener",
            "variables.tf": "project_name, environment, aws_region, container_port, task_cpu, task_memory",
            "outputs.tf": "cluster_name, load_balancer_dns, ecr_repository_url",
        },
        "mandatory_outputs": ["cluster_name", "load_balancer_dns", "ecr_repository_url"],
        "key_resources": ["aws_ecs_cluster", "aws_ecs_task_definition", "aws_ecs_service", "aws_lb", "aws_ecr_repository"],
        "ecs_example": ecs_data.get("example_hcl", ""),
        "vpc_example": vpc_data.get("example_hcl", ""),
    }


def _build_serverless_template_guide() -> dict[str, Any]:
    return {
        "architecture": "serverless",
        "description": "AWS Lambda + API Gateway serverless architecture with S3 and DynamoDB",
        "required_files": {
            "providers.tf": "AWS provider with version ~> 5.0",
            "backend.tf": "S3 remote state",
            "lambda.tf": "aws_lambda_function, aws_lambda_permission, aws_cloudwatch_log_group",
            "api_gateway.tf": "aws_api_gateway_rest_api, resources, methods, deployment, stage",
            "iam.tf": "Lambda execution role with logging permissions",
            "variables.tf": "project_name, environment, aws_region, lambda_runtime",
            "outputs.tf": "api_gateway_url, lambda_function_name",
        },
        "mandatory_outputs": ["api_gateway_url", "lambda_function_name"],
        "key_resources": ["aws_lambda_function", "aws_api_gateway_rest_api", "aws_iam_role"],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  DIRECT DATA ACCESS (no MCP overhead — used by MCPClient in same process)
# ═══════════════════════════════════════════════════════════════════════════════

def get_terraform_resource_direct(resource_name: str) -> dict[str, Any] | None:
    """Direct access to terraform resource data (no subprocess, no async)."""
    return load_terraform_resource(resource_name)


def list_terraform_resources_direct() -> list[str]:
    return list_terraform_resources()


def validate_hcl_direct(hcl: str) -> dict[str, Any]:
    return validate_hcl(hcl)


def suggest_fixes_direct(hcl: str) -> dict[str, Any]:
    return suggest_fixes(hcl)


def get_all_resources_direct() -> dict[str, dict[str, Any]]:
    return get_all_terraform_resources()


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if not _FASTMCP_AVAILABLE:
        logger.error(
            "mcp package not installed. Run: pip install mcp\n"
            "The MCP server requires the 'mcp' Python package."
        )
        sys.exit(1)

    logger.info("Starting DevSecOps MCP Server (stdio transport)")
    logger.info("Available terraform resources: %s", list_terraform_resources())
    mcp.run()


if __name__ == "__main__":
    main()
