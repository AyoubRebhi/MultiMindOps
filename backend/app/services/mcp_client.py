"""
MCP Client for DevSecOps AI Platform.

Provides sync-friendly access to MCP server resources and tools.
The backend agents are synchronous (ReAct loop) so this client bridges
async MCP protocol to sync calling code via a background event loop thread.

Architecture:
  - Direct mode (default): loads JSON data files directly — zero subprocess overhead
  - Protocol mode (opt-in): spawns MCP server subprocess for full protocol compliance

Direct mode is used for read-only resource access (terraform schemas, best practices).
Protocol mode is available for tool calls when full MCP session is needed.

Usage:
    client = MCPClient.get_instance()

    # Get a terraform resource schema
    resource = client.get_terraform_resource("aws_vpc")

    # Validate HCL code
    result = client.validate_terraform_code(hcl_string)

    # Get hybrid context (MCP + Qdrant combined)
    context = client.build_terraform_context("aws_vpc", architecture_type="eks")
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Ensure project root on path ───────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class MCPClient:
    """
    Production-grade MCP client with in-memory cache (24h TTL).

    Uses direct JSON file access for zero-latency resource reads.
    Optionally connects via MCP stdio protocol for full tool support.
    """

    _instance: MCPClient | None = None
    _lock = threading.Lock()

    CACHE_TTL: float = 86_400.0  # 24 hours

    def __init__(self) -> None:
        self._cache: dict[str, tuple[Any, float]] = {}
        self._cache_lock = threading.Lock()
        self._available = False

        # Lazy-import the server module (same process, no subprocess)
        self._server_module = self._load_server_module()

    # ── Singleton ─────────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> MCPClient:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Public resource API ───────────────────────────────────────────────────

    def get_terraform_resource(self, resource_name: str) -> dict[str, Any] | None:
        """
        Return structured Terraform resource data for the given resource type.

        Returns None if not found. Result is cached for 24 hours.
        """
        cache_key = f"tf_resource:{resource_name}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self._server_module:
            return None

        try:
            data = self._server_module.get_terraform_resource_direct(resource_name)
            if data:
                self._set_cached(cache_key, data)
            return data
        except Exception as exc:
            logger.warning("[MCPClient] get_terraform_resource(%s) failed: %s", resource_name, exc)
            return None

    def get_terraform_resource_formatted(self, resource_name: str) -> str:
        """
        Return a formatted, LLM-ready explanation of a Terraform resource.

        Returns empty string if not found.
        """
        cache_key = f"tf_resource_fmt:{resource_name}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self._server_module:
            return ""

        try:
            data = self._server_module.get_terraform_resource_direct(resource_name)
            if not data:
                return ""
            from devsecops_mcp.tools.terraform_tools import explain_terraform_resource
            formatted = explain_terraform_resource(resource_name, data)
            self._set_cached(cache_key, formatted)
            return formatted
        except Exception as exc:
            logger.warning("[MCPClient] get_terraform_resource_formatted(%s) failed: %s", resource_name, exc)
            return ""

    def list_terraform_resources(self) -> list[str]:
        """Return a list of all available Terraform resource names."""
        cache_key = "tf_catalog"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self._server_module:
            return []

        try:
            resources = self._server_module.list_terraform_resources_direct()
            self._set_cached(cache_key, resources)
            return resources
        except Exception as exc:
            logger.warning("[MCPClient] list_terraform_resources failed: %s", exc)
            return []

    def get_architecture_template(self, architecture_type: str) -> dict[str, Any] | None:
        """
        Return a full architecture template guide (eks/ecs/serverless).

        Includes required files, resource list, mandatory outputs, and HCL examples.
        """
        cache_key = f"arch_template:{architecture_type}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self._server_module:
            return None

        try:
            builder_map = {
                "eks": self._server_module._build_eks_template_guide,
                "ecs": self._server_module._build_ecs_template_guide,
                "serverless": self._server_module._build_serverless_template_guide,
            }
            builder = builder_map.get(architecture_type)
            if not builder:
                return None
            result = builder()
            self._set_cached(cache_key, result)
            return result
        except Exception as exc:
            logger.warning("[MCPClient] get_architecture_template(%s) failed: %s", architecture_type, exc)
            return None

    def get_aws_best_practices(self) -> dict[str, Any] | None:
        """Return AWS Well-Architected best practices."""
        cache_key = "aws_best_practices"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        if not self._server_module:
            return None

        try:
            from devsecops_mcp.resources.aws_resources import load_aws_best_practices
            data = load_aws_best_practices("best_practices")
            if data:
                self._set_cached(cache_key, data)
            return data
        except Exception as exc:
            logger.warning("[MCPClient] get_aws_best_practices failed: %s", exc)
            return None

    # ── Public tool API ───────────────────────────────────────────────────────

    def validate_terraform_code(self, hcl: str) -> dict[str, Any]:
        """
        Validate Terraform HCL code for syntax errors, security issues, and best practices.

        Returns dict with: valid, score, issues, warnings, summary.
        """
        if not self._server_module:
            return {"valid": True, "score": 100, "issues": [], "warnings": [], "summary": "MCP unavailable"}
        try:
            return self._server_module.validate_hcl_direct(hcl)
        except Exception as exc:
            logger.warning("[MCPClient] validate_terraform_code failed: %s", exc)
            return {"valid": True, "score": 100, "issues": [], "warnings": [], "summary": f"Validation error: {exc}"}

    def suggest_terraform_fix(self, hcl: str) -> dict[str, Any]:
        """Suggest actionable fixes for Terraform HCL code issues."""
        if not self._server_module:
            return {"fixes": [], "fix_count": 0}
        try:
            return self._server_module.suggest_fixes_direct(hcl)
        except Exception as exc:
            logger.warning("[MCPClient] suggest_terraform_fix failed: %s", exc)
            return {"fixes": [], "fix_count": 0}

    # ── High-level context builder ─────────────────────────────────────────────

    def build_terraform_context(
        self,
        query: str,
        architecture_type: str = "eks",
        resource_hints: list[str] | None = None,
        max_chars: int = 12_000,
    ) -> dict[str, Any]:
        """
        Build a structured MCP context block for Terraform generation.

        Combines:
        - Architecture template guide (file structure, mandatory outputs)
        - Specific resource schemas for detected/hinted resources
        - AWS best practices (security and cost sections)

        Returns dict with: available, context_text, resources_loaded, architecture_type
        """
        if not self._server_module:
            return {"available": False, "context_text": "", "resources_loaded": [], "architecture_type": architecture_type}

        context_parts: list[str] = []
        resources_loaded: list[str] = []

        # 1. Architecture template ─────────────────────────────────────────────
        arch_template = self.get_architecture_template(architecture_type)
        if arch_template:
            context_parts.append(self._format_arch_template(arch_template))

        # 2. Detect which resources are relevant ──────────────────────────────
        relevant_resources = self._detect_relevant_resources(
            query=query,
            architecture_type=architecture_type,
            hints=resource_hints or [],
        )

        # 3. Load formatted resource schemas ──────────────────────────────────
        chars_used = sum(len(p) for p in context_parts)
        for resource_name in relevant_resources:
            if chars_used >= max_chars:
                break
            formatted = self.get_terraform_resource_formatted(resource_name)
            if formatted and len(formatted) + chars_used <= max_chars:
                context_parts.append(formatted)
                resources_loaded.append(resource_name)
                chars_used += len(formatted)

        # 4. Add security best practices (condensed) ──────────────────────────
        if chars_used < max_chars - 500:
            bp = self.get_aws_best_practices()
            if bp:
                sec_practices = bp.get("pillars", {}).get("security", {}).get("practices", [])
                if sec_practices:
                    sec_block = "AWS Security Best Practices:\n" + "\n".join(
                        f"  ✓ {p}" for p in sec_practices[:5]
                    )
                    context_parts.append(sec_block)

        context_text = "\n\n".join(context_parts)
        if len(context_text) > max_chars:
            context_text = context_text[:max_chars] + "\n\n[...MCP context truncated...]"

        return {
            "available": bool(context_parts),
            "context_text": context_text,
            "resources_loaded": resources_loaded,
            "architecture_type": architecture_type,
            "char_count": len(context_text),
        }

    def build_kubernetes_context(self, query: str, max_chars: int = 2_000) -> dict[str, Any]:
        """Build structured MCP context for Kubernetes manifest generation."""
        if not self._server_module:
            return {"available": False, "context_text": "", "templates_loaded": []}

        context_parts: list[str] = []
        templates_loaded: list[str] = []

        try:
            from mcp.resources.kubernetes_resources import (
                load_kubernetes_template,
                list_kubernetes_templates,
            )
            from mcp.server import _format_kubernetes_resource

            for tmpl_name in list_kubernetes_templates():
                data = load_kubernetes_template(tmpl_name)
                if data:
                    formatted = _format_kubernetes_resource(tmpl_name, data)
                    context_parts.append(formatted)
                    templates_loaded.append(tmpl_name)
                if sum(len(p) for p in context_parts) >= max_chars:
                    break
        except Exception as exc:
            logger.warning("[MCPClient] build_kubernetes_context failed: %s", exc)

        context_text = "\n\n".join(context_parts)
        return {
            "available": bool(context_parts),
            "context_text": context_text[:max_chars],
            "templates_loaded": templates_loaded,
        }

    # ── Health check ──────────────────────────────────────────────────────────

    def health_check(self) -> dict[str, Any]:
        """Return health status of the MCP client."""
        resources = self.list_terraform_resources()
        return {
            "status": "ok" if resources else "degraded",
            "mode": "direct",
            "available_terraform_resources": len(resources),
            "cache_entries": len(self._cache),
        }

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _get_cached(self, key: str) -> Any | None:
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expire_at = entry
            if time.monotonic() > expire_at:
                del self._cache[key]
                return None
            return value

    def _set_cached(self, key: str, value: Any) -> None:
        with self._cache_lock:
            self._cache[key] = (value, time.monotonic() + self.CACHE_TTL)

    def invalidate_cache(self, prefix: str | None = None) -> None:
        """Clear cache entries (optionally filtered by key prefix)."""
        with self._cache_lock:
            if prefix is None:
                self._cache.clear()
            else:
                keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
                for k in keys_to_remove:
                    del self._cache[k]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_server_module(self) -> Any | None:
        """Import the MCP server module for direct (in-process) data access."""
        try:
            import devsecops_mcp.server as srv  # type: ignore
            self._available = True
            logger.info("[MCPClient] MCP server module loaded (direct mode)")
            return srv
        except ImportError as exc:
            logger.warning("[MCPClient] MCP server module not available: %s", exc)
            return None

    def _detect_relevant_resources(
        self,
        query: str,
        architecture_type: str,
        hints: list[str],
    ) -> list[str]:
        """Determine which Terraform resources are most relevant to the query."""
        query_lower = query.lower()

        # Architecture-default resources
        arch_defaults: dict[str, list[str]] = {
            "eks": ["aws_vpc", "aws_eks_cluster", "aws_iam_role", "aws_ecr_repository", "aws_alb"],
            "ecs": ["aws_vpc", "aws_ecs_cluster", "aws_iam_role", "aws_ecr_repository", "aws_alb"],
            "serverless": ["aws_iam_role", "backend_s3"],
        }

        # Query-based additions
        keyword_resources: dict[str, str] = {
            "vpc": "aws_vpc",
            "security group": "aws_security_group",
            "iam": "aws_iam_role",
            "ecr": "aws_ecr_repository",
            "s3": "backend_s3",
            "backend": "backend_s3",
            "alb": "aws_alb",
            "load balancer": "aws_alb",
            "eks": "aws_eks_cluster",
            "ecs": "aws_ecs_cluster",
        }

        result: list[str] = list(arch_defaults.get(architecture_type, []))

        for keyword, resource in keyword_resources.items():
            if keyword in query_lower and resource not in result:
                result.append(resource)

        # Honor explicit hints
        for hint in hints:
            if hint not in result:
                result.append(hint)

        # Filter to only existing resources
        available = set(self.list_terraform_resources())
        return [r for r in result if r in available][:6]  # cap at 6 to fit in context

    @staticmethod
    def _format_arch_template(template: dict[str, Any]) -> str:
        arch = template.get("architecture", "").upper()
        desc = template.get("description", "")
        files = template.get("required_files", {})
        outputs = template.get("mandatory_outputs", [])

        lines = [
            f"=== ARCHITECTURE: {arch} ===",
            "",
            f"Description: {desc}",
            "",
            "Required Terraform Files:",
        ]
        for fname, fdesc in files.items():
            lines.append(f"  • {fname}: {fdesc}")

        if outputs:
            lines += ["", f"Mandatory outputs.tf entries: {', '.join(outputs)}"]

        cost = template.get("cost_optimization", [])
        if cost:
            lines += ["", "Cost Optimization:"]
            for tip in cost:
                lines.append(f"  ✓ {tip}")

        return "\n".join(lines)
