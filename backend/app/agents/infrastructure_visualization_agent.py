"""
InfrastructureVisualizationAgent — produces text-based visual representations
of a selected infrastructure plan with no external dependencies.

Input
-----
run(selected_plan)

  selected_plan — dict containing:
    "architecture"     : infrastructure blueprint (from MultiPlanAgent / PlannerAgent)
    "cost_estimation"  : cost dict produced by CostEstimationAgent

Output
------
{
  "visualization": {
    "diagram":     str,          # ASCII architecture diagram
    "summary":     dict,         # human-readable key/value summary
    "resources":   list[dict],   # structured resource table rows
    "highlights":  list[str]     # key feature callouts
  }
}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.app.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

# ── Box-drawing helpers ───────────────────────────────────────────────────────

_H = "─"
_V = "│"
_TL = "┌"
_TR = "┐"
_BL = "└"
_BR = "┘"
_T_DOWN = "┬"
_T_UP = "┴"
_T_RIGHT = "├"
_T_LEFT = "┤"
_CROSS = "┼"
_ARR_DOWN = "▼"


def _box(label: str, width: int = 13) -> List[str]:
    """Return a 3-line box centred on *label*."""
    inner = width - 2
    text = label[:inner].center(inner)
    top = _TL + _H * inner + _TR
    mid = _V + text + _V
    bot = _BL + _H * inner + _BR
    return [top, mid, bot]


def _centre(text: str, total_width: int) -> str:
    return text.center(total_width)


# ── Diagram builders ──────────────────────────────────────────────────────────


def _build_monolith_diagram(arch: Dict[str, Any]) -> str:
    db_engine = (arch.get("database") or {}).get("engine", "RDS")
    db_label = f"RDS ({db_engine.upper()[:6]})" if db_engine else "RDS DB"
    compute_type = (arch.get("compute") or {}).get("type", "EC2")
    instance = (arch.get("compute") or {}).get("instance_type", "")
    compute_label = f"{compute_type.upper()[:6]} {instance}"[:11] if instance else compute_type.upper()[:11]

    w = 60
    lines: List[str] = []
    lines.append(_centre("┌──────────────────────┐", w))
    lines.append(_centre("│       Internet        │", w))
    lines.append(_centre("└──────────┬────────────┘", w))
    lines.append(_centre("│", w))
    lines.append(_centre("┌──────────▼────────────┐", w))
    lines.append(_centre("│          ALB          │", w))
    lines.append(_centre("└──────────┬────────────┘", w))
    lines.append(_centre("│", w))
    lines.append(_centre(f"┌──────────▼────────────┐", w))
    lines.append(_centre(f"│  {compute_label.center(19)}│", w))
    lines.append(_centre("│    (Single Node)      │", w))
    lines.append(_centre("└──────────┬────────────┘", w))
    lines.append(_centre("│", w))
    lines.append(_centre(f"┌──────────▼────────────┐", w))
    lines.append(_centre(f"│  {db_label.center(19)}│", w))
    lines.append(_centre("└───────────────────────┘", w))
    return "\n".join(lines)


def _build_microservices_diagram(arch: Dict[str, Any], node_count: int) -> str:
    cache_enabled = bool(arch.get("cache"))
    db_engine = (arch.get("database") or {}).get("engine", "RDS")
    db_az = (arch.get("database") or {}).get("deployment", "single-az")
    db_label = f"RDS {db_az[:7].upper()}"
    cache_label = "ElastiCache" if cache_enabled else None

    # Clamp display nodes to 1-5
    display_nodes = min(max(node_count, 1), 5)

    w = 80
    lines: List[str] = []

    lines.append(_centre("┌──────────────────────┐", w))
    lines.append(_centre("│       Internet        │", w))
    lines.append(_centre("└──────────┬────────────┘", w))
    lines.append(_centre("│", w))
    lines.append(_centre("┌──────────▼────────────┐", w))
    lines.append(_centre("│          ALB          │", w))
    lines.append(_centre("└──────────┬────────────┘", w))
    lines.append(_centre("│", w))

    # Pod row
    pod_width = 11
    gap = 6
    total_pod_section = display_nodes * pod_width + (display_nodes - 1) * gap
    pod_top_row = "   ".join([_TL + _H * (pod_width - 2) + _TR] * display_nodes)
    pod_mid_row = "   ".join([_V + " Pod {:1d} (EKS)".format(i + 1)[:pod_width - 2].center(pod_width - 2) + _V for i in range(display_nodes)])
    pod_bot_row = "   ".join([_BL + _H * (pod_width - 2) + _BR] * display_nodes)

    # Connector bar above pods
    connector_top = _centre("┌" + _H * (total_pod_section + 2) + "┐", w)

    lines.append(_centre(pod_top_row, w))
    lines.append(_centre(pod_mid_row, w))
    lines.append(_centre(pod_bot_row, w))
    lines.append(_centre("│" + " " * ((total_pod_section) // 2) + "│", w))

    # Data tier
    if cache_enabled:
        lines.append(_centre("┌────────────────┐   ┌────────────────┐", w))
        lines.append(_centre(f"│  {db_label[:14].center(14)}│   │ {cache_label[:14].center(14)} │", w))
        lines.append(_centre("└────────────────┘   └────────────────┘", w))
    else:
        lines.append(_centre("┌────────────────┐", w))
        lines.append(_centre(f"│  {db_label[:14].center(14)}│", w))
        lines.append(_centre("└────────────────┘", w))

    return "\n".join(lines)


def _build_serverless_diagram(arch: Dict[str, Any]) -> str:
    db_engine = (arch.get("database") or {}).get("engine", "DynamoDB")
    db_label = db_engine.upper()[:12] if db_engine else "DynamoDB"
    w = 60
    lines: List[str] = []

    lines.append(_centre("┌──────────────────────┐", w))
    lines.append(_centre("│       Internet        │", w))
    lines.append(_centre("└──────────┬────────────┘", w))
    lines.append(_centre("│", w))
    lines.append(_centre("┌──────────▼────────────┐", w))
    lines.append(_centre("│     API Gateway       │", w))
    lines.append(_centre("└──────────┬────────────┘", w))
    lines.append(_centre("│", w))
    lines.append(_centre("┌────────────────────────────────────────┐", w))
    lines.append(_centre("│         Lambda Functions               │", w))
    lines.append(_centre("│  [fn-auth]  [fn-api]  [fn-worker]      │", w))
    lines.append(_centre("└──────────┬─────────────────────────────┘", w))
    lines.append(_centre("│", w))
    lines.append(_centre(f"┌──────────▼────────────┐", w))
    lines.append(_centre(f"│  {db_label.center(19)}│", w))
    lines.append(_centre("└───────────────────────┘", w))

    return "\n".join(lines)


def _build_generic_diagram(arch: Dict[str, Any]) -> str:
    """Fallback diagram for unknown architecture types."""
    components: List[str] = []
    if arch.get("compute"):
        components.append("Compute Layer")
    if arch.get("database"):
        components.append("Database Layer")
    if arch.get("cache"):
        components.append("Cache Layer")
    if arch.get("storage"):
        components.append("Storage Layer")
    if not components:
        components = ["Infrastructure"]

    w = 60
    lines: List[str] = []
    lines.append(_centre("┌──────────────────────┐", w))
    lines.append(_centre("│       Internet        │", w))
    lines.append(_centre("└──────────┬────────────┘", w))
    lines.append(_centre("│", w))
    for comp in components:
        box_top = f"┌──────────▼────────────┐" if comp == components[0] else "┌───────────────────────┐"
        lines.append(_centre(box_top, w))
        lines.append(_centre(f"│  {comp.center(19)}│", w))
        lines.append(_centre("└──────────┬────────────┘" if comp != components[-1] else "└───────────────────────┘", w))
        if comp != components[-1]:
            lines.append(_centre("│", w))

    return "\n".join(lines)


# ── Architecture detection ────────────────────────────────────────────────────


def _detect_architecture_type(arch: Dict[str, Any]) -> Tuple[str, int]:
    """
    Returns (arch_type, node_count).
    arch_type is one of: "microservices", "serverless", "monolith"
    """
    arch_type = (arch.get("type") or arch.get("architecture_type") or "").lower()

    if "serverless" in arch_type or arch.get("functions") or arch.get("lambda"):
        return "serverless", 0

    compute = arch.get("compute") or {}
    compute_type = (compute.get("type") or "").lower()
    min_nodes = int(compute.get("min_nodes") or compute.get("nodes") or 1)
    max_nodes = int(compute.get("max_nodes") or min_nodes)
    node_count = max(min_nodes, 1)

    if "serverless" in compute_type or "lambda" in compute_type:
        return "serverless", 0

    if "microservices" in arch_type or "eks" in compute_type or "kubernetes" in compute_type or "k8s" in compute_type:
        return "microservices", node_count

    if min_nodes > 1 or max_nodes > 2:
        return "microservices", node_count

    return "monolith", node_count


# ── Summary & resource table builders ────────────────────────────────────────


def _build_summary(arch: Dict[str, Any], cost: Dict[str, Any], arch_type: str, node_count: int) -> Dict[str, str]:
    compute = arch.get("compute") or {}
    database = arch.get("database") or {}
    cache = arch.get("cache")
    storage = arch.get("storage")
    networking = arch.get("networking") or {}

    compute_svc = (compute.get("type") or compute.get("service") or "EC2").upper()
    if arch_type == "serverless":
        compute_str = "Lambda (serverless)"
    elif node_count > 1:
        compute_str = f"{compute_svc} ({node_count} nodes)"
    else:
        instance = compute.get("instance_type", "")
        compute_str = f"{compute_svc} ({instance})" if instance else compute_svc

    db_engine = (database.get("engine") or "RDS").upper()
    db_az = database.get("deployment", "single-az")
    db_str = f"{db_engine} ({db_az.replace('-', ' ').title()})" if database else "N/A"

    cache_engine = (cache or {}).get("engine", "") if isinstance(cache, dict) else ""
    cache_str = f"{cache_engine.capitalize()} (enabled)" if cache_engine else ("Enabled" if cache else "Disabled")

    lb_type = networking.get("load_balancer", "ALB") if networking else "ALB"
    vpc = "VPC" if networking else ""
    net_str = f"{lb_type} + {vpc}".strip(" +") if lb_type else "VPC"

    monthly_cost = cost.get("monthly_cost", 0)
    cost_str = f"${monthly_cost:,.0f}/month" if monthly_cost else "N/A"

    return {
        "compute":        compute_str,
        "database":       db_str,
        "cache":          cache_str,
        "networking":     net_str,
        "estimated_cost": cost_str,
    }


def _build_resources(arch: Dict[str, Any], arch_type: str, node_count: int) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    compute = arch.get("compute") or {}
    database = arch.get("database") or {}
    cache = arch.get("cache")
    storage = arch.get("storage")
    networking = arch.get("networking") or {}

    if arch_type == "serverless":
        rows.append({"type": "Compute", "service": "Lambda", "details": "Serverless functions"})
        rows.append({"type": "API", "service": "API Gateway", "details": "HTTP/REST endpoint"})
    else:
        compute_svc = (compute.get("type") or "EC2").upper()
        instance = compute.get("instance_type") or compute.get("node_type", "")
        min_n = compute.get("min_nodes", 1)
        max_n = compute.get("max_nodes", min_n)
        details = f"{instance}, {min_n}-{max_n} nodes" if instance else f"{min_n}-{max_n} nodes"
        rows.append({"type": "Compute", "service": compute_svc, "details": details})
        rows.append({"type": "Networking", "service": networking.get("load_balancer", "ALB"), "details": "Load balancer + VPC"})

    if database:
        db_engine = (database.get("engine") or "RDS").upper()
        db_class = database.get("instance_class") or database.get("instance_type", "")
        db_az = database.get("deployment", "single-az")
        replicas = database.get("read_replicas", 0)
        details = f"{db_az.title()}"
        if db_class:
            details = f"{db_class}, {details}"
        if replicas:
            details += f", {replicas} read replica(s)"
        rows.append({"type": "Database", "service": db_engine, "details": details})
    else:
        db_label = "DynamoDB" if arch_type == "serverless" else "RDS"
        rows.append({"type": "Database", "service": db_label, "details": "Managed database"})

    if cache:
        cache_engine = (cache.get("engine") or "Redis").capitalize() if isinstance(cache, dict) else "Redis"
        cache_instance = cache.get("instance_type", "") if isinstance(cache, dict) else ""
        rows.append({"type": "Cache", "service": cache_engine, "details": cache_instance or "Enabled"})
    else:
        rows.append({"type": "Cache", "service": "N/A", "details": "Disabled"})

    if storage:
        svc = (storage.get("type") or "S3").upper()
        cls = storage.get("storage_class") or storage.get("class", "Standard")
        rows.append({"type": "Storage", "service": svc, "details": cls.title()})
    else:
        rows.append({"type": "Storage", "service": "S3", "details": "Standard"})

    return rows


def _build_highlights(arch: Dict[str, Any], arch_type: str, node_count: int) -> List[str]:
    highlights: List[str] = []
    compute = arch.get("compute") or {}
    database = arch.get("database") or {}
    cache = arch.get("cache")
    scaling = arch.get("scaling") or {}

    # Architecture-level callout
    if arch_type == "serverless":
        highlights.append("Serverless architecture — no server management required")
    elif arch_type == "microservices":
        highlights.append(f"Distributed microservices across {node_count} compute node(s)")
    else:
        highlights.append("Monolithic single-node deployment — simple to operate")

    # Database HA
    db_deploy = database.get("deployment", "single-az") if database else "single-az"
    if "multi" in db_deploy.lower():
        highlights.append("High availability with Multi-AZ database deployment")
    else:
        highlights.append("Single-AZ database — consider Multi-AZ for production HA")

    # Cache
    if cache:
        highlights.append("In-memory cache layer reduces database read pressure")

    # Auto-scaling
    strategy = scaling.get("strategy", "")
    max_r = scaling.get("max_replicas", 0)
    if strategy or max_r:
        highlights.append(
            f"Auto-scaling enabled (strategy: {strategy or 'default'}, "
            f"max replicas: {max_r or 'N/A'})"
        )

    # Read replicas
    replicas = int(database.get("read_replicas", 0)) if database else 0
    if replicas:
        highlights.append(f"{replicas} read replica(s) for improved read throughput")

    return highlights


# ── Agent class ───────────────────────────────────────────────────────────────


class InfrastructureVisualizationAgent(BaseAgent):
    """
    Generates a text-based visual representation of a selected infrastructure
    plan.  No LLM calls, no external dependencies — fully deterministic.

    Input
    -----
    selected_plan : dict with keys "architecture" and "cost_estimation"

    Output
    ------
    {"visualization": {"diagram": str, "summary": dict, "resources": list, "highlights": list}}
    """

    def __init__(self) -> None:
        super().__init__(name="InfrastructureVisualizationAgent")

    # ── Public interface ──────────────────────────────────────────────────────

    def run(self, selected_plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a full visualization bundle for *selected_plan*.

        Parameters
        ----------
        selected_plan:
            Must contain "architecture" (blueprint dict) and optionally
            "cost_estimation" (cost dict).

        Returns
        -------
        {"visualization": {"diagram": str, "summary": dict,
                           "resources": list[dict], "highlights": list[str]}}
        """
        arch: Dict[str, Any] = selected_plan.get("architecture") or {}
        cost: Dict[str, Any] = selected_plan.get("cost_estimation") or {}

        arch_type, node_count = _detect_architecture_type(arch)

        logger.info(
            "[InfrastructureVisualizationAgent] arch_type=%s  nodes=%d  "
            "components=%s",
            arch_type,
            node_count,
            ", ".join(k for k in ("compute", "database", "cache", "storage") if arch.get(k)),
        )

        diagram = self._build_diagram(arch, arch_type, node_count)
        summary = _build_summary(arch, cost, arch_type, node_count)
        resources = _build_resources(arch, arch_type, node_count)
        highlights = _build_highlights(arch, arch_type, node_count)

        return {
            "visualization": {
                "diagram":    diagram,
                "summary":    summary,
                "resources":  resources,
                "highlights": highlights,
            }
        }

    # ── Diagram dispatch ──────────────────────────────────────────────────────

    @staticmethod
    def _build_diagram(arch: Dict[str, Any], arch_type: str, node_count: int) -> str:
        header = "=" * 62 + "\n  INFRASTRUCTURE DIAGRAM\n" + "=" * 62
        if arch_type == "serverless":
            body = _build_serverless_diagram(arch)
        elif arch_type == "microservices":
            body = _build_microservices_diagram(arch, node_count)
        elif arch_type == "monolith":
            body = _build_monolith_diagram(arch)
        else:
            body = _build_generic_diagram(arch)

        footer = "=" * 62
        return f"{header}\n\n{body}\n\n{footer}"
