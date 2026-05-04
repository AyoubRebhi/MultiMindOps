"""
Terraform Documentation Ingestion Script.

Fetches Terraform AWS provider documentation from the Terraform Registry
and converts it into structured JSON format for MCP resource storage.

Usage:
    python mcp/scripts/ingest_terraform_docs.py [--resource aws_vpc] [--all]

Sources (priority order):
  1. Terraform Registry API: https://registry.terraform.io/v2/providers/...
  2. GitHub terraform-provider-aws: raw HCL documentation
  3. Local static fallback (mcp/data/terraform/*.json)

Output:
  - mcp/data/terraform/{resource_name}.json (one file per resource)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "devsecops_mcp" / "data" / "terraform"

# ── Target resources ──────────────────────────────────────────────────────────
RESOURCES_TO_INGEST = [
    "aws_vpc",
    "aws_subnet",
    "aws_security_group",
    "aws_internet_gateway",
    "aws_nat_gateway",
    "aws_route_table",
    "aws_route_table_association",
    "aws_iam_role",
    "aws_iam_policy",
    "aws_iam_role_policy_attachment",
    "aws_eks_cluster",
    "aws_eks_node_group",
    "aws_ecs_cluster",
    "aws_ecs_task_definition",
    "aws_ecs_service",
    "aws_ecr_repository",
    "aws_ecr_lifecycle_policy",
    "aws_lb",
    "aws_lb_target_group",
    "aws_lb_listener",
    "aws_s3_bucket",
    "aws_s3_bucket_versioning",
    "aws_dynamodb_table",
    "aws_kms_key",
    "aws_cloudwatch_log_group",
    "aws_rds_instance",
    "aws_elasticache_cluster",
]

# ── Terraform Registry API ────────────────────────────────────────────────────
_REGISTRY_BASE = "https://registry.terraform.io"
_PROVIDER_SLUG = "hashicorp/aws"


def fetch_registry_docs(resource_name: str) -> dict[str, Any] | None:
    """Fetch structured data from the Terraform Registry API."""
    try:
        import httpx

        # Try alternative endpoints since the v2/provider-docs API returns 400
        # Fallback: try fetching from GitHub raw content
        content = _fetch_github_docs(resource_name)
        
        if not content:
            logger.debug("Could not fetch %s documentation", resource_name)
            return None

        return _parse_registry_markdown(resource_name, content)

    except ImportError:
        logger.warning("httpx not installed — cannot fetch from registry")
        return None
    except Exception as exc:
        logger.warning("Registry fetch failed for %s: %s", resource_name, exc)
        return None


def _fetch_github_docs(resource_name: str) -> str | None:
    """Fetch documentation from GitHub terraform-provider-aws repository."""
    try:
        import httpx
        
        # Try multiple possible GitHub paths
        github_urls = [
            # Main docs path (resource name with aws_ prefix)
            f"https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/website/docs/r/{resource_name}.html.markdown",
            # Alternative: without aws_ prefix
            f"https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/website/docs/r/{resource_name.replace('aws_', '')}.html.markdown",
            # Alternative: markdown extension
            f"https://raw.githubusercontent.com/hashicorp/terraform-provider-aws/main/website/docs/r/{resource_name}.markdown",
        ]
        
        for github_url in github_urls:
            try:
                with httpx.Client(timeout=30) as client:
                    resp = client.get(github_url, follow_redirects=True)
                    if resp.status_code == 200:
                        logger.info("Fetched %s from GitHub (%s)", resource_name, github_url)
                        return resp.text
            except Exception:
                continue
    except Exception as exc:
        logger.debug("GitHub fetch failed for %s: %s", resource_name, exc)
    
    return None


def _parse_registry_markdown(resource_name: str, markdown: str) -> dict[str, Any]:
    """Convert Terraform Registry Markdown documentation into structured JSON."""
    struct: dict[str, Any] = {
        "name": resource_name,
        "provider": "aws",
        "category": _infer_category(resource_name),
        "description": "",
        "arguments": {"required": [], "optional": []},
        "example_hcl": "",
        "minimal_example": "",
        "best_practices": [],
        "security_notes": [],
        "common_errors": [],
        "related_resources": [],
    }

    # Extract description (first paragraph after title)
    desc_match = re.search(r"^# .*?\n\n(.+?)(?:\n\n|\Z)", markdown, re.DOTALL)
    if desc_match:
        struct["description"] = desc_match.group(1).strip()[:500]

    # Extract HCL example blocks
    hcl_blocks = re.findall(r"```(?:hcl|terraform)\n(.*?)```", markdown, re.DOTALL)
    if hcl_blocks:
        struct["example_hcl"] = hcl_blocks[0].strip()
        if len(hcl_blocks) > 1:
            struct["minimal_example"] = hcl_blocks[1].strip()

    # Extract argument sections
    arg_section = re.search(
        r"## Argument Reference\s*\n(.*?)(?:## Attribute|## Import|\Z)",
        markdown,
        re.DOTALL,
    )
    if arg_section:
        arg_text = arg_section.group(1)
        required_args = re.findall(r"\* `(\w+)` - \*\*Required\*\*[.:]?\s*(.+?)(?=\n\*|$)", arg_text, re.DOTALL)
        optional_args = re.findall(r"\* `(\w+)` - \*\*Optional\*\*[.:]?\s*(.+?)(?=\n\*|$)", arg_text, re.DOTALL)

        struct["arguments"]["required"] = [
            {"name": name, "type": "any", "description": desc.strip()[:200]}
            for name, desc in required_args[:10]
        ]
        struct["arguments"]["optional"] = [
            {"name": name, "type": "any", "description": desc.strip()[:200]}
            for name, desc in optional_args[:15]
        ]

    return struct


def _infer_category(resource_name: str) -> str:
    mapping = {
        "aws_vpc": "networking", "aws_subnet": "networking",
        "aws_security_group": "networking", "aws_internet_gateway": "networking",
        "aws_nat_gateway": "networking", "aws_route_table": "networking",
        "aws_iam": "iam", "aws_eks": "compute", "aws_ecs": "compute",
        "aws_lambda": "compute", "aws_ecr": "container-registry",
        "aws_lb": "networking", "aws_alb": "networking",
        "aws_s3": "storage", "aws_dynamodb": "database",
        "aws_rds": "database", "aws_elasticache": "cache",
        "aws_kms": "security", "aws_cloudwatch": "observability",
    }
    for prefix, category in mapping.items():
        if resource_name.startswith(prefix):
            return category
    return "general"


def load_existing(resource_name: str) -> dict[str, Any] | None:
    """Load existing local JSON data for a resource."""
    path = _DATA_DIR / f"{resource_name}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_resource(resource_name: str, data: dict[str, Any]) -> None:
    """Save resource data to JSON file."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = _DATA_DIR / f"{resource_name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved: %s", path)


def ingest_resource(resource_name: str, force: bool = False) -> bool:
    """Ingest a single Terraform resource."""
    existing = load_existing(resource_name)

    if existing and not force:
        logger.info("Skipping %s — already exists (use --force to overwrite)", resource_name)
        return True

    logger.info("Ingesting %s from Terraform Registry...", resource_name)
    data = fetch_registry_docs(resource_name)

    if data:
        if existing:
            # Merge: registry data fills in gaps, existing curated data takes precedence
            for key in ("best_practices", "security_notes", "common_errors"):
                if existing.get(key):
                    data[key] = existing[key]  # keep curated content
        save_resource(resource_name, data)
        return True

    logger.warning("Could not fetch %s from registry — keeping existing data", resource_name)
    return False


def list_available() -> None:
    """Print available local resources."""
    resources = sorted(p.stem for p in _DATA_DIR.glob("*.json"))
    print(f"\nAvailable local resources ({len(resources)}):")
    for r in resources:
        print(f"  {r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Terraform docs into MCP data store")
    parser.add_argument("--resource", help="Ingest a single resource (e.g., aws_vpc)")
    parser.add_argument("--all", action="store_true", help="Ingest all target resources")
    parser.add_argument("--list", action="store_true", help="List available local resources")
    parser.add_argument("--force", action="store_true", help="Overwrite existing data")
    args = parser.parse_args()

    if args.list:
        list_available()
        return

    if args.resource:
        ingest_resource(args.resource, force=args.force)
    elif args.all:
        success = 0
        failed = 0
        for resource in RESOURCES_TO_INGEST:
            ok = ingest_resource(resource, force=args.force)
            if ok:
                success += 1
            else:
                failed += 1
            time.sleep(0.5)  # rate limit
        logger.info("Done — %d succeeded, %d failed", success, failed)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python mcp/scripts/ingest_terraform_docs.py --list")
        print("  python mcp/scripts/ingest_terraform_docs.py --resource aws_vpc")
        print("  python mcp/scripts/ingest_terraform_docs.py --all")


if __name__ == "__main__":
    main()
