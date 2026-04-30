#!/usr/bin/env python3
"""
Terraform Knowledge Ingestion Pipeline
=======================================
Automated scraper + cleaner + chunker for Terraform documentation
and real-world HCL examples.

Sources (in priority order):
  1. HashiCorp Terraform Registry API  — resource schemas + provider docs
  2. HashiCorp developer docs           — conceptual guides (state, backends, modules)
  3. GitHub search API                  — real-world .tf files from public repos

Output:
  rag/corpus/terraform/<resource_name>.tf     — HCL examples
  rag/corpus/terraform/<topic>_guide.md       — Conceptual markdown docs

Usage:
  python rag/scripts/terraform_scraper.py --resources aws_vpc aws_s3_bucket aws_iam_role
  python rag/scripts/terraform_scraper.py --guides state backends modules providers
  python rag/scripts/terraform_scraper.py --all  # fetch everything in priority list
  python rag/scripts/terraform_scraper.py --github-examples aws_vpc --max-repos 10

Environment variables:
  GITHUB_TOKEN   — optional, raises GitHub API rate limit from 60 to 5000 req/h
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[2]
CORPUS_TERRAFORM = ROOT / "rag" / "corpus" / "terraform"
CORPUS_TERRAFORM.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("terraform_scraper")

# ── Priority resource list (HIGH → MEDIUM → LOW impact) ───────────────────────

HIGH_PRIORITY_RESOURCES = [
    # Networking (most queried)
    "aws_vpc", "aws_subnet", "aws_internet_gateway", "aws_route_table",
    "aws_security_group", "aws_nat_gateway", "aws_eip",
    # IAM (security-critical)
    "aws_iam_role", "aws_iam_policy", "aws_iam_role_policy_attachment",
    "aws_iam_instance_profile", "aws_iam_openid_connect_provider",
    # Compute
    "aws_instance", "aws_launch_template", "aws_autoscaling_group",
    # State management
    "aws_s3_bucket", "aws_s3_bucket_versioning",
    "aws_s3_bucket_server_side_encryption_configuration",
    "aws_dynamodb_table",
    # EKS
    "aws_eks_cluster", "aws_eks_node_group",
]

MEDIUM_PRIORITY_RESOURCES = [
    "aws_rds_instance", "aws_db_subnet_group", "aws_elasticache_cluster",
    "aws_alb", "aws_alb_listener", "aws_alb_target_group",
    "aws_cloudwatch_log_group", "aws_cloudwatch_metric_alarm",
    "aws_ecr_repository", "aws_lambda_function",
]

GUIDE_TOPICS = [
    "state", "backends", "modules", "providers", "workspaces",
    "variables", "outputs", "data-sources", "expressions", "functions",
]

# ── Terraform Registry API ────────────────────────────────────────────────────

_REGISTRY_BASE = "https://registry.terraform.io/v1"
_TF_DOCS_BASE  = "https://developer.hashicorp.com"
_GITHUB_API    = "https://api.github.com"


class TerraformRegistryScraper:
    """Fetch resource schemas and examples from registry.terraform.io."""

    def __init__(self, timeout: float = 30.0, delay: float = 0.5):
        self._timeout = timeout
        self._delay   = delay
        self._client  = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "devsecops-rag-scraper/1.0"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TerraformRegistryScraper":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def fetch_provider_schema(self, provider: str = "hashicorp/aws") -> dict[str, Any]:
        """Fetch the full provider schema from the registry."""
        namespace, pname = provider.split("/")
        url = f"{_REGISTRY_BASE}/providers/{namespace}/{pname}/versions"
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            data = resp.json()
            versions = data.get("versions", [])
            if not versions:
                return {}
            latest = versions[0].get("version", "")
            logger.info("AWS provider latest version: %s", latest)
            return {"provider": provider, "latest_version": latest, "versions": versions[:5]}
        except Exception as exc:
            logger.warning("Registry schema fetch failed: %s", exc)
            return {}

    def fetch_resource_docs(self, resource_type: str) -> str | None:
        """
        Fetch resource documentation from the Terraform Registry.
        Returns markdown text or None on failure.
        """
        # aws_vpc → provider=aws, resource=vpc
        parts = resource_type.split("_", 1)
        if len(parts) < 2:
            return None
        provider_prefix, resource_name = parts[0], parts[1]

        url = (
            f"{_REGISTRY_BASE}/providers/hashicorp/{provider_prefix}"
            f"/docs/resources/{resource_name}"
        )
        time.sleep(self._delay)
        try:
            resp = self._client.get(url)
            if resp.status_code == 404:
                logger.debug("Registry 404 for %s — trying docs site", resource_type)
                return None
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("attributes", {}).get("content", "")
        except Exception as exc:
            logger.warning("Registry docs fetch failed for %s: %s", resource_type, exc)
            return None

    def generate_hcl_example(self, resource_type: str, doc_content: str) -> str:
        """
        Synthesize a minimal working HCL example from registry doc content.
        Extracts argument names from the ## Argument Reference section.
        """
        lines = []
        lines.append(f"# Auto-generated example for {resource_type}")
        lines.append(f"# Source: Terraform Registry")
        lines.append("")

        # Extract required arguments from docs (lines starting with "* `argname`" marked Required)
        required_args: list[str] = []
        optional_args: list[str] = []

        arg_pattern = re.compile(r'\* `(\w+)`[^-]*-\s*(.*)')
        in_arg_section = False

        for line in doc_content.split("\n"):
            if "## Argument Reference" in line or "## Arguments" in line:
                in_arg_section = True
                continue
            if in_arg_section and line.startswith("## "):
                in_arg_section = False
            if in_arg_section:
                m = arg_pattern.match(line)
                if m:
                    arg_name = m.group(1)
                    desc     = m.group(2)
                    if "required" in desc.lower():
                        required_args.append(arg_name)
                    elif "optional" in desc.lower():
                        optional_args.append(arg_name)

        lines.append(f'resource "{resource_type}" "example" {{')
        for arg in required_args[:8]:
            lines.append(f'  {arg} = "<required>"')
        for arg in optional_args[:4]:
            lines.append(f'  # {arg} = "<optional>"')
        lines.append("}")
        lines.append("")

        return "\n".join(lines)


class GitHubTerraformScraper:
    """
    Search GitHub for real-world Terraform examples using the code search API.
    Requires GITHUB_TOKEN env var for higher rate limits.
    """

    def __init__(self, token: str = "", timeout: float = 30.0, delay: float = 2.0):
        self._token  = token or os.environ.get("GITHUB_TOKEN", "")
        self._delay  = delay
        headers = {"User-Agent": "devsecops-rag-scraper/1.0", "Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._client = httpx.Client(timeout=timeout, headers=headers, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def search_examples(
        self,
        resource_type: str,
        max_files: int = 5,
        min_stars: int = 10,
    ) -> list[dict[str, str]]:
        """
        Search GitHub for .tf files that define a specific resource type.
        Returns list of {"url": str, "content": str, "repo": str, "stars": int}
        """
        query = f'resource "{resource_type}" extension:tf'
        url   = f"{_GITHUB_API}/search/code"
        params = {
            "q":        query,
            "per_page": min(max_files * 3, 30),  # over-fetch, filter by quality
            "sort":     "indexed",
        }
        time.sleep(self._delay)
        try:
            resp = self._client.get(url, params=params)
            if resp.status_code == 403:
                logger.warning("GitHub rate limit hit — set GITHUB_TOKEN to raise limit")
                return []
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except Exception as exc:
            logger.warning("GitHub search failed for %s: %s", resource_type, exc)
            return []

        results: list[dict[str, str]] = []
        for item in items[:max_files * 2]:
            raw_url    = item.get("html_url", "").replace("github.com", "raw.githubusercontent.com")
            raw_url    = raw_url.replace("/blob/", "/")
            repo_name  = item.get("repository", {}).get("full_name", "")
            stars      = item.get("repository", {}).get("stargazers_count", 0)

            if stars < min_stars:
                continue

            time.sleep(self._delay)
            try:
                content_resp = self._client.get(raw_url)
                content_resp.raise_for_status()
                content = content_resp.text

                # Quality filter: skip auto-generated or empty files
                if len(content) < 100 or "auto-generated" in content.lower():
                    continue

                # Only keep files that actually contain the resource
                if f'resource "{resource_type}"' not in content:
                    continue

                results.append({
                    "url":     raw_url,
                    "content": _clean_hcl(content),
                    "repo":    repo_name,
                    "stars":   str(stars),
                })

                if len(results) >= max_files:
                    break

            except Exception as exc:
                logger.debug("Failed to fetch %s: %s", raw_url, exc)

        return results

    def close_client(self) -> None:
        self._client.close()


# ── HCL Cleaner ───────────────────────────────────────────────────────────────

def _clean_hcl(content: str) -> str:
    """
    Sanitize raw HCL from GitHub:
    - Remove hardcoded AWS account IDs, access keys, secrets
    - Remove personal email addresses
    - Normalize whitespace
    - Keep comments that explain architecture decisions
    """
    # Remove AWS access keys
    content = re.sub(r'AKIA[0-9A-Z]{16}', 'AKIAXXXXXXXXXXXXXXXX', content)
    # Remove 12-digit AWS account IDs
    content = re.sub(r'\b\d{12}\b', '123456789012', content)
    # Remove secrets/passwords in assignments
    content = re.sub(
        r'(password|secret|token|key)\s*=\s*"[^"]{8,}"',
        r'\1 = "<redacted>"',
        content,
        flags=re.IGNORECASE,
    )
    # Normalize line endings
    content = content.replace("\r\n", "\n").strip()
    return content


# ── Chunk Strategy for HCL ────────────────────────────────────────────────────

def chunk_hcl_file(content: str, source_path: str) -> list[dict[str, str]]:
    """
    Split a .tf file into atomic chunks preserving HCL block integrity.

    Strategy:
    1. Split on top-level block boundaries (resource, data, variable, output, module).
    2. Each top-level block becomes one chunk — NEVER split inside a block.
    3. If a block > 1500 chars, it stays as one chunk (don't split HCL mid-block).
    4. Add a prose header chunk with file-level context if file has a comment header.

    Returns list of {"content": str, "chunk_type": str, "block_type": str}
    """
    chunks: list[dict[str, str]] = []

    # Extract file-level comment header (lines starting with #)
    header_lines: list[str] = []
    for line in content.split("\n"):
        if line.startswith("#") or line.strip() == "":
            header_lines.append(line)
        else:
            break
    if len(header_lines) > 2:
        header_text = "\n".join(header_lines).strip()
        if len(header_text) > 50:
            chunks.append({
                "content":    header_text,
                "chunk_type": "prose",
                "block_type": "file_header",
                "source":     source_path,
            })

    # Regex to match top-level HCL blocks
    # Matches: resource "type" "name" {, variable "name" {, output "name" {, etc.
    block_pattern = re.compile(
        r'^(resource|data|variable|output|module|provider|terraform|locals)\s*'
        r'(?:"[^"]*"\s*)?(?:"[^"]*"\s*)?\{',
        re.MULTILINE,
    )

    positions = [m.start() for m in block_pattern.finditer(content)]
    positions.append(len(content))

    for i, start in enumerate(positions[:-1]):
        end = positions[i + 1]
        block_text = content[start:end].strip()

        if len(block_text) < 20:
            continue

        # Determine block type from the match
        m = block_pattern.match(block_text)
        block_type = m.group(1) if m else "unknown"

        chunks.append({
            "content":    block_text,
            "chunk_type": "config",
            "block_type": block_type,
            "source":     source_path,
        })

    return chunks


# ── Metadata schema for Terraform corpus ─────────────────────────────────────

def build_terraform_metadata(
    resource_type: str,
    source: str,
    chunk_type: str,
    block_type: str,
    provider: str = "aws",
) -> dict[str, str]:
    """
    Standard metadata schema for all Terraform corpus entries.
    Used by ingest_qdrant.py and the RAG retrieval filters.
    """
    return {
        "source_type":    "terraform_hcl",
        "artifact_type":  "terraform",
        "doc_type":       "terraform",
        "cloud_provider": provider,
        "resource_type":  resource_type,
        "chunk_type":     chunk_type,   # config | prose | security_rule
        "block_type":     block_type,   # resource | variable | output | module | ...
        "source":         source,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Terraform docs and HCL examples for the DevSecOps RAG corpus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--resources", nargs="+", metavar="RESOURCE",
        help="Terraform resource types to fetch (e.g. aws_vpc aws_s3_bucket)",
    )
    parser.add_argument(
        "--all-high-priority", action="store_true",
        help="Fetch all HIGH priority resources",
    )
    parser.add_argument(
        "--github-examples", nargs="+", metavar="RESOURCE",
        help="Search GitHub for real-world .tf examples of these resources",
    )
    parser.add_argument(
        "--max-repos", type=int, default=5,
        help="Max GitHub repos to pull examples from per resource (default: 5)",
    )
    parser.add_argument(
        "--min-stars", type=int, default=10,
        help="Min GitHub repo stars for quality filter (default: 10)",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Delay in seconds between API calls (default: 1.0)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be fetched without writing files",
    )
    args = parser.parse_args()

    resources_to_fetch = list(args.resources or [])
    if args.all_high_priority:
        resources_to_fetch = HIGH_PRIORITY_RESOURCES

    total_written = 0

    # ── Registry scraping ──────────────────────────────────────────────────────
    if resources_to_fetch:
        logger.info("Fetching %d resources from Terraform Registry…", len(resources_to_fetch))
        with TerraformRegistryScraper(delay=args.delay) as scraper:
            for resource in resources_to_fetch:
                logger.info("  → %s", resource)
                doc = scraper.fetch_resource_docs(resource)
                if doc:
                    example_hcl = scraper.generate_hcl_example(resource, doc)
                    out_file = CORPUS_TERRAFORM / f"{resource}_registry.tf"
                    if not args.dry_run:
                        out_file.write_text(example_hcl, encoding="utf-8")
                        logger.info("    Wrote: %s (%d chars)", out_file.name, len(example_hcl))
                    else:
                        logger.info("    [dry-run] Would write: %s", out_file.name)
                    total_written += 1
                else:
                    logger.warning("    No docs found for %s", resource)

    # ── GitHub scraping ────────────────────────────────────────────────────────
    if args.github_examples:
        github_token = os.environ.get("GITHUB_TOKEN", "")
        if not github_token:
            logger.warning(
                "GITHUB_TOKEN not set — rate limit is 60 req/h. "
                "Set GITHUB_TOKEN for 5000 req/h."
            )

        gh = GitHubTerraformScraper(token=github_token, delay=args.delay * 2)
        try:
            for resource in args.github_examples:
                logger.info("Searching GitHub for %s examples…", resource)
                examples = gh.search_examples(
                    resource_type=resource,
                    max_files=args.max_repos,
                    min_stars=args.min_stars,
                )
                logger.info("  Found %d examples", len(examples))

                for j, ex in enumerate(examples, 1):
                    out_name  = f"{resource}_github_{j}.tf"
                    out_file  = CORPUS_TERRAFORM / out_name
                    header    = (
                        f"# Source: {ex['repo']} (stars={ex['stars']})\n"
                        f"# URL: {ex['url']}\n"
                        f"# Scraped by terraform_scraper.py\n\n"
                    )
                    final_content = header + ex["content"]

                    if not args.dry_run:
                        out_file.write_text(final_content, encoding="utf-8")
                        logger.info("    Wrote: %s (%d chars)", out_name, len(final_content))
                    else:
                        logger.info("    [dry-run] Would write: %s", out_name)
                    total_written += 1
        finally:
            gh.close_client()

    if not resources_to_fetch and not args.github_examples:
        parser.print_help()
        return 1

    action = "Would write" if args.dry_run else "Wrote"
    logger.info("%s %d files to %s", action, total_written, CORPUS_TERRAFORM)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
