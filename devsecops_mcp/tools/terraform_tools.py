"""
Terraform HCL validation, fix suggestion, and code generation tools.
Used by the MCP server as callable tools for the ReAct loop.
"""

from __future__ import annotations

import re
from typing import Any


def validate_hcl(hcl: str) -> dict[str, Any]:
    """Validate Terraform HCL code for syntax errors, security issues, and best practice violations."""
    if not hcl or not hcl.strip():
        return {
            "valid": False,
            "score": 0,
            "issues": ["Empty HCL content provided"],
            "warnings": [],
            "summary": "Invalid — empty input",
        }

    issues: list[str] = []
    warnings: list[str] = []

    # ── Try python-hcl2 structural parse if available ──────────────────────────
    try:
        import hcl2  # type: ignore
        import io
        hcl2.load(io.StringIO(hcl))
    except ImportError:
        pass  # python-hcl2 not installed — fall through to regex checks
    except Exception as exc:
        issues.append(f"HCL parse error: {str(exc)}")

    # ── Brace balance ─────────────────────────────────────────────────────────
    open_b = hcl.count("{")
    close_b = hcl.count("}")
    if open_b != close_b:
        issues.append(
            f"Unbalanced braces: {open_b} opening '{{' vs {close_b} closing '}}' — "
            f"{'add ' + str(open_b - close_b) + ' closing brace(s)' if open_b > close_b else 'remove ' + str(close_b - open_b) + ' closing brace(s)'}"
        )

    # ── Kubernetes DSL contamination ──────────────────────────────────────────
    k8s_markers = [
        ("apiVersion:", "apiVersion YAML directive"),
        ("kind: Deployment", "Kubernetes Deployment manifest"),
        ("kind: Service", "Kubernetes Service manifest"),
        ("kind: Pod", "Kubernetes Pod manifest"),
        ("kind: ConfigMap", "Kubernetes ConfigMap manifest"),
        ("kind: Ingress", "Kubernetes Ingress manifest"),
    ]
    for marker, label in k8s_markers:
        if marker in hcl:
            issues.append(
                f"DSL contamination: {label} found inside HCL — "
                "Kubernetes YAML must NOT be embedded in .tf files"
            )

    # ── Hardcoded secrets ─────────────────────────────────────────────────────
    secret_patterns = [
        (r'access_key\s*=\s*"[A-Z0-9]{20}"', "Hardcoded AWS access key"),
        (r'secret_key\s*=\s*"[^$\{][^"]{15,}"', "Hardcoded AWS secret key"),
        (r'(?i)password\s*=\s*"[^$\{][^"]{4,}"', "Possible hardcoded password"),
        (r'(?i)token\s*=\s*"[^$\{][^"]{10,}"', "Possible hardcoded token"),
    ]
    for pattern, label in secret_patterns:
        if re.search(pattern, hcl):
            issues.append(
                f"Security: {label} detected — use AWS Secrets Manager, "
                "SSM Parameter Store, or Terraform sensitive variables"
            )

    # ── Hardcoded AWS account IDs ─────────────────────────────────────────────
    account_id_pattern = re.compile(r'(?<!\d)\d{12}(?!\d)')
    if account_id_pattern.search(hcl):
        warnings.append(
            "Possible hardcoded AWS account ID detected — "
            "use data.aws_caller_identity.current.account_id instead"
        )

    # ── Hardcoded region ─────────────────────────────────────────────────────
    hardcoded_regions = re.findall(
        r'"(us-east-1|us-west-2|eu-west-1|eu-central-1|ap-southeast-1|ap-northeast-1)"',
        hcl,
    )
    # Only warn if region is hardcoded outside a variable default
    if hardcoded_regions and 'variable "aws_region"' not in hcl and "var.aws_region" not in hcl:
        warnings.append(
            f"Hardcoded AWS region(s) {hardcoded_regions[:2]} — "
            "use var.aws_region for portability"
        )

    # ── Missing recommended outputs ───────────────────────────────────────────
    if "output" in hcl or "resource" in hcl:
        recommended_outputs = [
            "cluster_endpoint",
            "cluster_name",
            "load_balancer_dns",
            "ecr_repository_url",
        ]
        found_outputs = re.findall(r'output\s+"(\w+)"', hcl)
        if "terraform_outputs" in hcl.lower() or "outputs.tf" in hcl.lower():
            for req in recommended_outputs:
                if req not in hcl and req not in found_outputs:
                    warnings.append(f"Missing recommended output: '{req}'")

    # ── Terraform block / provider ────────────────────────────────────────────
    has_resource = bool(re.search(r'^resource\s+"aws_', hcl, re.MULTILINE))
    has_provider = 'provider "aws"' in hcl or "required_providers" in hcl
    if has_resource and not has_provider:
        warnings.append(
            "AWS resources defined but no provider block found — "
            "ensure providers.tf includes the 'aws' provider configuration"
        )

    # ── Score calculation ─────────────────────────────────────────────────────
    score = 100 - (len(issues) * 20) - (len(warnings) * 5)
    score = max(0, min(100, score))

    return {
        "valid": len(issues) == 0,
        "score": score,
        "issues": issues,
        "warnings": warnings,
        "summary": (
            f"{'Valid' if not issues else 'Invalid'} — "
            f"{len(issues)} error(s), {len(warnings)} warning(s), score={score}/100"
        ),
    }


def suggest_fixes(hcl: str) -> dict[str, Any]:
    """Analyze HCL code and return structured, actionable fix recommendations."""
    validation = validate_hcl(hcl)
    fixes: list[dict[str, Any]] = []

    for issue in validation["issues"]:
        if "Unbalanced braces" in issue:
            open_b = hcl.count("{")
            close_b = hcl.count("}")
            diff = abs(open_b - close_b)
            fixes.append({
                "severity": "error",
                "issue": issue,
                "fix": (
                    f"Add {diff} closing brace(s) at the appropriate location"
                    if open_b > close_b
                    else f"Remove {diff} extra closing brace(s)"
                ),
                "example": "}" * diff if open_b > close_b else "# Remove extra closing braces",
            })

        elif "DSL contamination" in issue:
            fixes.append({
                "severity": "error",
                "issue": issue,
                "fix": (
                    "Remove all Kubernetes YAML from .tf files. "
                    "Place Kubernetes manifests in kubernetes/deployment.yaml, "
                    "kubernetes/service.yaml, etc."
                ),
                "example": (
                    "# kubernetes/deployment.yaml  ← Kubernetes YAML goes here\n"
                    "# terraform/eks.tf            ← Only HCL goes here"
                ),
            })

        elif "Hardcoded AWS access key" in issue or "secret key" in issue.lower():
            fixes.append({
                "severity": "critical",
                "issue": issue,
                "fix": (
                    "Remove AWS credentials from Terraform files. "
                    "Use IAM instance roles, IRSA, or environment variables instead"
                ),
                "example": (
                    "# provider.tf — do NOT set access_key / secret_key\n"
                    'provider "aws" {\n'
                    "  region = var.aws_region\n"
                    "  # Credentials from IAM role or AWS_ACCESS_KEY_ID env var\n"
                    "}"
                ),
            })

        elif "Possible hardcoded password" in issue:
            fixes.append({
                "severity": "error",
                "issue": issue,
                "fix": "Use AWS Secrets Manager or SSM Parameter Store for database passwords",
                "example": (
                    'data "aws_secretsmanager_secret_version" "db_password" {\n'
                    '  secret_id = "${var.project_name}/db-password"\n'
                    "}\n\n"
                    "# Reference: jsondecode(data.aws_secretsmanager_secret_version.db_password.secret_string)[\"password\"]"
                ),
            })

    for warning in validation["warnings"]:
        if "account ID" in warning:
            fixes.append({
                "severity": "warning",
                "issue": warning,
                "fix": "Use the aws_caller_identity data source to get the account ID dynamically",
                "example": (
                    'data "aws_caller_identity" "current" {}\n\n'
                    "# Usage: data.aws_caller_identity.current.account_id"
                ),
            })

        elif "Hardcoded AWS region" in warning:
            fixes.append({
                "severity": "warning",
                "issue": warning,
                "fix": "Extract AWS region to a variable",
                "example": (
                    'variable "aws_region" {\n'
                    '  description = "AWS region for all resources"\n'
                    '  type        = string\n'
                    '  default     = "us-east-1"\n'
                    "}"
                ),
            })

        elif "Missing recommended output" in warning:
            output_name = ""
            match = re.search(r"'(\w+)'", warning)
            if match:
                output_name = match.group(1)
            if output_name:
                output_source = _get_output_source_example(output_name)
                fixes.append({
                    "severity": "warning",
                    "issue": warning,
                    "fix": f"Add output block for '{output_name}' in outputs.tf",
                    "example": (
                        f'output "{output_name}" {{\n'
                        f'  description = "..."\n'
                        f'  value       = {output_source}\n'
                        f"}}"
                    ),
                })

    return {
        "original_validation": validation,
        "fixes": fixes,
        "fix_count": len(fixes),
        "has_critical": any(f["severity"] == "critical" for f in fixes),
    }


def explain_terraform_resource(resource_name: str, data: dict[str, Any]) -> str:
    """Format a Terraform resource schema into a structured explanation string."""
    lines = [
        f"=== TERRAFORM RESOURCE: {resource_name} ===",
        "",
        f"Category: {data.get('category', 'unknown')}",
        "",
        "Description:",
        data.get("description", "No description available"),
        "",
    ]

    use_cases = data.get("use_cases", [])
    if use_cases:
        lines.append("Use Cases:")
        for uc in use_cases:
            lines.append(f"  • {uc}")
        lines.append("")

    args = data.get("arguments", {})
    required = args.get("required", [])
    optional = args.get("optional", [])

    if required:
        lines.append("Required Arguments:")
        for arg in required:
            default = f" (default: {arg['default']})" if "default" in arg else ""
            lines.append(f"  ✦ {arg['name']} ({arg.get('type', 'any')}){default}")
            lines.append(f"    {arg.get('description', '')}")
        lines.append("")

    if optional:
        lines.append("Key Optional Arguments:")
        for arg in optional[:8]:
            default = f" (default: {arg['default']})" if "default" in arg else ""
            lines.append(f"  ○ {arg['name']} ({arg.get('type', 'any')}){default}")
            lines.append(f"    {arg.get('description', '')}")
        lines.append("")

    example = data.get("example_hcl") or data.get("minimal_example", "")
    if example:
        lines.append("Example HCL:")
        lines.append("```hcl")
        lines.append(example)
        lines.append("```")
        lines.append("")

    best_practices = data.get("best_practices", [])
    if best_practices:
        lines.append("Best Practices:")
        for bp in best_practices:
            lines.append(f"  ✓ {bp}")
        lines.append("")

    security_notes = data.get("security_notes", [])
    if security_notes:
        lines.append("Security Notes:")
        for note in security_notes:
            lines.append(f"  ⚠ {note}")
        lines.append("")

    common_errors = data.get("common_errors", [])
    if common_errors:
        lines.append("Common Errors & Fixes:")
        for err in common_errors:
            lines.append(f"  ✗ Error: {err.get('error', '')}")
            lines.append(f"    Fix:   {err.get('fix', '')}")
        lines.append("")

    related = data.get("related_resources", [])
    if related:
        lines.append(f"Related Resources: {', '.join(related)}")

    return "\n".join(lines)


def _get_output_source_example(output_name: str) -> str:
    mapping = {
        "cluster_endpoint": "aws_eks_cluster.main.endpoint",
        "cluster_name": "aws_eks_cluster.main.name",
        "load_balancer_dns": "aws_lb.main.dns_name",
        "ecr_repository_url": "aws_ecr_repository.app.repository_url",
        "vpc_id": "aws_vpc.main.id",
        "vpc_cidr": "aws_vpc.main.cidr_block",
    }
    return mapping.get(output_name, f"<resource>.<name>.{output_name}")
