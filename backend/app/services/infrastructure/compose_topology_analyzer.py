"""
ComposeTopologyAnalyzer — parses docker-compose.yml to extract service topology.

Provides topology context for the Dockerfile generation pipeline so that:
  - Runtime mode (dev/prod/staging) is inferred from compose commands and env vars
  - Volume mounts signal hot-reload dev workflows
  - Port mappings can be verified against Dockerfile EXPOSE
  - Service dependency graph is available for compose-aware generation
  - Backend service is identified (the one being Dockerized)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ServiceTopology:
    name: str
    image: Optional[str] = None
    build_context: Optional[str] = None
    build_dockerfile: Optional[str] = None
    ports: List[str] = field(default_factory=list)
    volumes: List[str] = field(default_factory=list)
    command: Optional[str] = None
    entrypoint: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    environment: Dict[str, str] = field(default_factory=dict)
    healthcheck: Optional[Dict[str, Any]] = None
    networks: List[str] = field(default_factory=list)
    restart: Optional[str] = None


@dataclass
class ComposeTopology:
    services: List[ServiceTopology] = field(default_factory=list)
    backend_service: Optional[str] = None
    runtime_mode: str = "production"   # "development" | "staging" | "production"
    hot_reload: bool = False
    has_db: bool = False
    has_cache: bool = False
    service_graph: Dict[str, List[str]] = field(default_factory=dict)
    networks: List[str] = field(default_factory=list)
    volumes: List[str] = field(default_factory=list)
    compose_version: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "services": [
                {
                    "name": s.name,
                    "image": s.image,
                    "build_context": s.build_context,
                    "build_dockerfile": s.build_dockerfile,
                    "ports": s.ports,
                    "volumes": s.volumes,
                    "command": s.command,
                    "entrypoint": s.entrypoint,
                    "depends_on": s.depends_on,
                    "environment": s.environment,
                    "healthcheck": s.healthcheck,
                    "restart": s.restart,
                }
                for s in self.services
            ],
            "backend_service": self.backend_service,
            "runtime_mode": self.runtime_mode,
            "hot_reload": self.hot_reload,
            "has_db": self.has_db,
            "has_cache": self.has_cache,
            "service_graph": self.service_graph,
            "networks": self.networks,
            "volumes": self.volumes,
            "compose_version": self.compose_version,
        }


# ── Detection patterns ────────────────────────────────────────────────────────

_DEV_PATTERNS = [
    r"--reload",
    r"--hot(?:-reload)?",
    r"\bnodemon\b",
    r"\bwatchdog\b",
    r"\blivereload\b",
    r"flask\s+run",
    r"rails\s+server",
    r"npm\s+run\s+dev",
    r"yarn\s+dev",
    r"vite\b",
    r"\bdevelopment\b",
    r"NODE_ENV=development",
    r"FLASK_ENV=development",
    r"DJANGO_DEBUG=true",
    r"DEBUG=true",
    r"RAILS_ENV=development",
]

_STAGING_PATTERNS = [
    r"\bstaging\b",
    r"NODE_ENV=staging",
    r"RAILS_ENV=staging",
]

_DB_IMAGES = {
    "postgres", "postgresql", "mysql", "mariadb", "mongodb", "mongo",
    "sqlite", "mssql", "sqlserver", "cockroachdb", "cassandra",
}

_CACHE_IMAGES = {
    "redis", "memcached", "rabbitmq", "kafka", "nats", "zookeeper",
}

_BACKEND_NAMES = {
    "backend", "api", "server", "app", "service", "web", "application",
    "gateway", "core", "main",
}


# ── Analyzer ──────────────────────────────────────────────────────────────────

class ComposeTopologyAnalyzer:
    """Parses a docker-compose.yml content string and extracts service topology."""

    def analyze(self, compose_content: str) -> ComposeTopology:
        """
        Parse docker-compose YAML and return a ComposeTopology.

        Args:
            compose_content: Raw docker-compose.yml content as a string.

        Returns:
            ComposeTopology with services, runtime_mode, hot_reload, and graph.
        """
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(compose_content)
        except Exception as exc:
            logger.warning("[ComposeTopologyAnalyzer] YAML parse failed: %s", exc)
            return ComposeTopology()

        if not isinstance(data, dict):
            return ComposeTopology()

        topology = ComposeTopology()
        topology.compose_version = str(data.get("version", "")).strip() or None

        topology.volumes = list((data.get("volumes") or {}).keys())
        topology.networks = list((data.get("networks") or {}).keys())

        services_raw = data.get("services") or {}
        if not isinstance(services_raw, dict):
            return topology

        for svc_name, svc_data in services_raw.items():
            if not isinstance(svc_data, dict):
                continue
            topology.services.append(self._parse_service(svc_name, svc_data))

        topology.service_graph = {s.name: s.depends_on for s in topology.services}
        topology.backend_service = self._detect_backend(topology.services)
        topology.runtime_mode = self._detect_runtime_mode(topology.services)
        topology.hot_reload = self._has_hot_reload(topology.services)
        topology.has_db = self._has_service_type(topology.services, _DB_IMAGES)
        topology.has_cache = self._has_service_type(topology.services, _CACHE_IMAGES)

        logger.info(
            "[ComposeTopologyAnalyzer] Parsed %d services — backend=%s mode=%s hot_reload=%s",
            len(topology.services),
            topology.backend_service,
            topology.runtime_mode,
            topology.hot_reload,
        )
        return topology

    # ── Parsers ───────────────────────────────────────────────────────────────

    def _parse_service(self, name: str, data: Dict[str, Any]) -> ServiceTopology:
        svc = ServiceTopology(name=name)
        svc.image = data.get("image")

        build = data.get("build")
        if isinstance(build, str):
            svc.build_context = build
        elif isinstance(build, dict):
            svc.build_context = build.get("context", ".")
            svc.build_dockerfile = build.get("dockerfile")

        svc.ports = [str(p) for p in (data.get("ports") or [])]
        svc.volumes = [str(v) for v in (data.get("volumes") or [])]

        cmd = data.get("command")
        svc.command = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else (str(cmd) if cmd else None)

        ep = data.get("entrypoint")
        svc.entrypoint = " ".join(str(e) for e in ep) if isinstance(ep, list) else (str(ep) if ep else None)

        depends_raw = data.get("depends_on") or []
        if isinstance(depends_raw, list):
            svc.depends_on = [str(d) for d in depends_raw]
        elif isinstance(depends_raw, dict):
            svc.depends_on = list(depends_raw.keys())

        env_raw = data.get("environment") or {}
        if isinstance(env_raw, list):
            for item in env_raw:
                s = str(item)
                if "=" in s:
                    k, _, v = s.partition("=")
                    svc.environment[k.strip()] = v.strip()
        elif isinstance(env_raw, dict):
            svc.environment = {str(k): str(v) for k, v in env_raw.items()}

        svc.healthcheck = data.get("healthcheck")

        nets = data.get("networks") or []
        svc.networks = list(nets.keys()) if isinstance(nets, dict) else [str(n) for n in nets]

        svc.restart = data.get("restart")
        return svc

    # ── Detection logic ───────────────────────────────────────────────────────

    def _detect_backend(self, services: List[ServiceTopology]) -> Optional[str]:
        """Find the primary application service (the one being Dockerized)."""
        # Priority 1: service with a build context (not just image reference)
        for svc in services:
            if svc.build_context is not None:
                return svc.name

        # Priority 2: name matches canonical backend patterns
        for svc in services:
            if svc.name.lower() in _BACKEND_NAMES:
                return svc.name

        # Priority 3: first non-infra service (not DB/cache)
        for svc in services:
            image = (svc.image or "").lower()
            if not any(db in image for db in (_DB_IMAGES | _CACHE_IMAGES)):
                return svc.name

        return services[0].name if services else None

    def _detect_runtime_mode(self, services: List[ServiceTopology]) -> str:
        all_text = self._collect_all_text(services)

        for pattern in _STAGING_PATTERNS:
            if re.search(pattern, all_text, re.IGNORECASE):
                return "staging"

        for pattern in _DEV_PATTERNS:
            if re.search(pattern, all_text, re.IGNORECASE):
                return "development"

        return "production"

    def _has_hot_reload(self, services: List[ServiceTopology]) -> bool:
        reload_patterns = [r"--reload", r"--hot", r"\bnodemon\b", r"\bwatchdog\b", r"\blivereload\b"]
        all_text = self._collect_all_text(services)
        return any(re.search(p, all_text, re.IGNORECASE) for p in reload_patterns)

    def _has_service_type(self, services: List[ServiceTopology], image_prefixes: set) -> bool:
        for svc in services:
            image = (svc.image or "").lower()
            if any(prefix in image for prefix in image_prefixes):
                return True
            if svc.name.lower() in image_prefixes:
                return True
        return False

    def _collect_all_text(self, services: List[ServiceTopology]) -> str:
        parts = []
        for svc in services:
            if svc.command:
                parts.append(svc.command)
            if svc.entrypoint:
                parts.append(svc.entrypoint)
            for k, v in svc.environment.items():
                parts.append(f"{k}={v}")
        return " ".join(parts)
