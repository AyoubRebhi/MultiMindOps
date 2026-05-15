"""
InfrastructureContextAssembler — merges all context sources into one normalized
generation context that is topology-aware and repository-grounded.

Sources merged:
  1. mapped_context   — output of InfrastructureContextMapper (codebase analysis)
  2. compose_topology — output of ComposeTopologyAnalyzer (docker-compose.yml)
  3. known_files      — repository file list from codebase analysis
  4. build_context_report — output of BuildContextResolver (COPY validation)

The resulting context replaces the raw project_context fed into
StructuredDockerfileGenerator, ensuring every downstream component has
topology-aware, repository-grounded input.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.app.services.infrastructure.compose_topology_analyzer import ComposeTopology, ServiceTopology

logger = logging.getLogger(__name__)


class InfrastructureContextAssembler:
    """
    Assembles a unified, topology-aware generation context.

    Design principle: this is the single normalization point between raw analysis
    and artifact generation. All downstream generators receive context from here.
    """

    def assemble(
        self,
        *,
        mapped_context: Dict[str, Any],
        compose_topology: Optional[ComposeTopology] = None,
        known_files: Optional[List[str]] = None,
        build_context_report: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Merge all context sources into a single normalized context dict.

        Args:
            mapped_context:       Output of InfrastructureContextMapper.map().
            compose_topology:     Parsed docker-compose topology (optional).
            known_files:          Repository file paths from codebase analysis (optional).
            build_context_report: COPY resolution report from BuildContextResolver (optional).

        Returns:
            Enriched context dict — superset of mapped_context with topology keys added.
        """
        enriched = dict(mapped_context)

        # ── 1. Compose topology ───────────────────────────────────────────────
        if compose_topology is not None:
            self._inject_compose_topology(enriched, compose_topology)
        else:
            enriched.setdefault("compose_topology", None)
            enriched.setdefault("runtime_mode", "production")
            enriched.setdefault("hot_reload", False)
            enriched.setdefault("cmd_strategy", "production")

        # ── 2. Known files ────────────────────────────────────────────────────
        enriched["known_files"] = known_files if known_files is not None else []

        # ── 3. Build context report ───────────────────────────────────────────
        if build_context_report is not None:
            enriched["build_context_report"] = build_context_report
            if not build_context_report.get("valid", True):
                warnings = enriched.setdefault("generation_warnings", [])
                warnings.extend(build_context_report.get("issues", []))
        else:
            enriched.setdefault("build_context_report", None)

        # ── 4. Topology summary (compact, for UI + logging) ───────────────────
        enriched["topology_summary"] = self._build_topology_summary(enriched)

        logger.info(
            "[InfraContextAssembler] assembled — runtime_mode=%s hot_reload=%s "
            "compose_services=%d build_context=%s is_monorepo=%s",
            enriched.get("runtime_mode"),
            enriched.get("hot_reload"),
            len((enriched.get("compose_topology") or {}).get("services", [])),
            enriched.get("build_context"),
            (enriched.get("build_context_report") or {}).get("is_monorepo", False),
        )
        return enriched

    # ── Compose injection ─────────────────────────────────────────────────────

    def _inject_compose_topology(
        self, enriched: Dict[str, Any], topology: ComposeTopology
    ) -> None:
        enriched["compose_topology"] = topology.to_dict()
        enriched["runtime_mode"] = topology.runtime_mode
        enriched["hot_reload"] = topology.hot_reload
        enriched["cmd_strategy"] = self._infer_cmd_strategy(topology)

        # Promote compose-detected backend into main_service if missing
        main_svc = enriched.get("main_service") or {}
        if not main_svc and topology.backend_service:
            backend = self._find_service(topology, topology.backend_service)
            if backend:
                enriched["main_service"] = self._service_to_main_service(backend, {})
                main_svc = enriched["main_service"]

        # Fill run_command from compose command if not yet set
        if not (main_svc or {}).get("run_command") and topology.backend_service:
            backend = self._find_service(topology, topology.backend_service)
            if backend and backend.command:
                main_svc = dict(main_svc)
                main_svc["run_command"] = backend.command
                main_svc["run_command_source"] = "compose"
                enriched["main_service"] = main_svc

        # Ensure docker-compose is expected when compose defines DB/cache services
        if topology.has_db or topology.has_cache:
            expectations = dict(enriched.get("artifact_expectations") or {})
            expectations["needs_docker_compose"] = True
            enriched["artifact_expectations"] = expectations

    # ── CMD strategy ──────────────────────────────────────────────────────────

    def _infer_cmd_strategy(self, topology: ComposeTopology) -> str:
        """Map compose runtime mode to CMD generation strategy."""
        return {
            "development": "development",
            "staging": "staging",
        }.get(topology.runtime_mode, "production")

    # ── Service helpers ───────────────────────────────────────────────────────

    def _find_service(
        self, topology: ComposeTopology, name: str
    ) -> Optional[ServiceTopology]:
        return next((s for s in topology.services if s.name == name), None)

    def _service_to_main_service(
        self, svc: ServiceTopology, existing: Dict[str, Any]
    ) -> Dict[str, Any]:
        result = dict(existing)
        result.setdefault("name", svc.name)
        if not result.get("run_command") and svc.command:
            result["run_command"] = svc.command
        if not result.get("entrypoint") and svc.entrypoint:
            result["entrypoint"] = svc.entrypoint
        if not result.get("port") and svc.ports:
            try:
                # "8080:8000" → container port is 8000
                result["port"] = int(svc.ports[0].split(":")[-1])
            except (ValueError, IndexError):
                pass
        return result

    # ── Topology summary for UI ───────────────────────────────────────────────

    def _build_topology_summary(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        main_svc = ctx.get("main_service") or {}
        compose = ctx.get("compose_topology") or {}
        build_report = ctx.get("build_context_report") or {}
        runtime = ctx.get("runtime") or {}
        dep_files = runtime.get("dependency_files") or []

        return {
            "runtime_mode": ctx.get("runtime_mode", "production"),
            "hot_reload": ctx.get("hot_reload", False),
            "backend_service": compose.get("backend_service") or main_svc.get("name"),
            "build_context": ctx.get("build_context", "."),
            "dependency_file": dep_files[0] if dep_files else None,
            "entrypoint": main_svc.get("entrypoint") or main_svc.get("run_command"),
            "framework": main_svc.get("framework"),
            "language": main_svc.get("language"),
            "port": main_svc.get("port"),
            "compose_services": [s.get("name") for s in compose.get("services", [])],
            "has_db": compose.get("has_db", False),
            "has_cache": compose.get("has_cache", False),
            "is_monorepo": build_report.get("is_monorepo", False),
            "build_context_valid": build_report.get("valid", True),
            "build_context_issues": build_report.get("issues", []),
            "build_context_warnings": build_report.get("warnings", []),
        }
