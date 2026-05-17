"""
RepositoryBuildContext — normalized model of the repository's Docker build setup.

Produced by BuildStrategyDetector from:
  - known_files  (repository file list from codebase analysis)
  - compose_topology (from ComposeTopologyAnalyzer)
  - mapped_context   (from InfrastructureContextMapper)

Consumed by:
  - ArtifactSectionGenerator  (COPY path generation guidance)
  - DockerBuildStaticValidator (pre-build COPY source validation)
  - DockerExecutor             (build strategy selection and logging)
  - DockerCorrectorAgent       (build-context-aware failure diagnosis)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Strategy constants ────────────────────────────────────────────────────────

STRATEGY_REPO_ROOT  = "repo_root_context"   # `docker build -f Dockerfile .`
STRATEGY_BACKEND    = "backend_context"     # `docker build -f backend/app/Dockerfile backend/app`
STRATEGY_COMPOSE    = "compose_driven"      # `docker compose build`

# Files that signal a Python backend dependency file
_PYTHON_DEP_NAMES = frozenset({
    "requirements.txt",
    "requirements-backend.txt",
    "requirements-prod.txt",
    "requirements-base.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "Pipfile",
    "Pipfile.lock",
})

_NODE_DEP_NAMES = frozenset({"package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"})
_JAVA_DEP_NAMES = frozenset({"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle"})

_FRONTEND_ROOTS = frozenset({"frontend", "frontend-react", "frontend-vue", "ui", "client", "web"})
_BACKEND_ROOTS  = frozenset({"backend", "api", "server", "app", "service", "gateway", "core", "src"})


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class BuildStrategy:
    """
    The selected Docker build strategy for this repository.

    strategy values:
      - "repo_root_context"  → build context = ".", Dockerfile at root
      - "backend_context"    → build context = "backend/app", Dockerfile inside it
      - "compose_driven"     → docker compose build; context from compose file
    """
    strategy: str                             # one of the STRATEGY_* constants
    context_path: str                         # e.g., "." or "backend/app"
    dockerfile_path: str                      # e.g., "Dockerfile" or "backend/app/Dockerfile"
    # When context is "." but backend files are in a subdirectory, the generator
    # must prefix COPY sources.  e.g., "backend/app"
    recommended_copy_prefix: Optional[str] = None

    def copy_source_for(self, repo_relative_path: str) -> str:
        """
        Given a repo-relative file path, return the correct COPY source path
        to use in a Dockerfile, accounting for the build context.

        Examples
        --------
        context="."  path="backend/app/requirements.txt"
          → "backend/app/requirements.txt"  (include full subdirectory prefix)

        context="backend/app"  path="backend/app/requirements.txt"
          → "requirements.txt"  (strip context prefix)
        """
        normalized = repo_relative_path.lstrip("./")
        ctx = self.context_path.strip("/").lstrip("./")
        if not ctx:  # context is "." or ""
            return normalized
        prefix = ctx + "/"
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
        return normalized

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "context_path": self.context_path,
            "dockerfile_path": self.dockerfile_path,
            "recommended_copy_prefix": self.recommended_copy_prefix,
        }


@dataclass
class RepositoryBuildContext:
    """
    Normalized model of the repository structure as it relates to Docker builds.

    This is the single source of truth for:
      - Where dependency files live (repo-relative paths)
      - What the Docker build context should be
      - How COPY instructions must be written to match the build context
    """
    repo_root: str = "."                            # Repo root ("." for current dir)
    backend_root: Optional[str] = None              # e.g., "backend/app"
    frontend_root: Optional[str] = None             # e.g., "frontend-React"
    dependency_files: Dict[str, List[str]] = field(default_factory=dict)
    # e.g., {"python": ["backend/app/requirements-backend.txt"], "node": [...]}
    docker: Optional[BuildStrategy] = None

    def copy_instructions_for_deps(self) -> Dict[str, str]:
        """
        Return a mapping of dep-type → recommended COPY instruction string,
        accounting for the build context.

        Example output when context="." and file at "backend/app/requirements-backend.txt":
          {"python": "COPY backend/app/requirements-backend.txt ./requirements-backend.txt"}
        """
        if not self.docker:
            return {}
        result: Dict[str, str] = {}
        for lang, files in self.dependency_files.items():
            if not files:
                continue
            f = files[0]  # primary dep file
            src = self.docker.copy_source_for(f)
            dest = "./" + Path(src).name
            result[lang] = f"COPY {src} {dest}"
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "backend_root": self.backend_root,
            "frontend_root": self.frontend_root,
            "dependency_files": self.dependency_files,
            "docker": self.docker.to_dict() if self.docker else None,
            "copy_instructions": self.copy_instructions_for_deps(),
        }


@dataclass
class BuildArtifactContext:
    """
    Shared context consumed by BOTH Dockerfile generator and docker-compose generator.

    Ensures the Dockerfile COPY paths and compose build.context are always consistent.
    Passed as project_context["build_artifact_context"] into the generation pipeline.
    """
    strategy: BuildStrategy
    repository: RepositoryBuildContext
    backend_root: str
    # Precomputed COPY instructions  e.g., {"python": "COPY backend/app/requirements.txt ./requirements.txt"}
    dependency_copy_instructions: Dict[str, str] = field(default_factory=dict)
    compose_context: str = "."               # What to put in docker-compose build.context
    compose_dockerfile: str = "Dockerfile"   # What to put in docker-compose build.dockerfile
    exposed_ports: List[int] = field(default_factory=list)
    runtime_assumptions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.to_dict(),
            "repository": self.repository.to_dict(),
            "backend_root": self.backend_root,
            "dependency_copy_instructions": self.dependency_copy_instructions,
            "compose_context": self.compose_context,
            "compose_dockerfile": self.compose_dockerfile,
            "exposed_ports": self.exposed_ports,
            "runtime_assumptions": self.runtime_assumptions,
        }


# ── BuildStrategyDetector ─────────────────────────────────────────────────────

class BuildStrategyDetector:
    """
    Determines the Docker build strategy and repository context from available signals.

    Decision priority:
      1. Compose topology  (if compose defines a build context, use it)
      2. Mapped context    (explicit build_context from InfrastructureContextMapper)
      3. File layout       (infer from known_files structure)
    """

    def detect(
        self,
        known_files: List[str],
        mapped_context: Dict[str, Any],
        compose_topology: Optional[Any] = None,  # ComposeTopology from ComposeTopologyAnalyzer
    ) -> RepositoryBuildContext:
        """
        Analyze repository signals and return a normalized RepositoryBuildContext.
        """
        backend_root  = self._find_backend_root(known_files, mapped_context)
        frontend_root = self._find_frontend_root(known_files)
        dep_files     = self._find_dependency_files(known_files)
        strategy      = self._select_strategy(
            known_files=known_files,
            backend_root=backend_root,
            compose_topology=compose_topology,
            mapped_context=mapped_context,
        )

        repo_ctx = RepositoryBuildContext(
            repo_root=".",
            backend_root=backend_root,
            frontend_root=frontend_root,
            dependency_files=dep_files,
            docker=strategy,
        )

        logger.info(
            "[BuildStrategyDetector] strategy=%s context=%s backend_root=%s "
            "copy_prefix=%s py_deps=%s",
            strategy.strategy,
            strategy.context_path,
            backend_root,
            strategy.recommended_copy_prefix,
            dep_files.get("python", []),
        )
        return repo_ctx

    def build_artifact_context(
        self,
        repo_ctx: RepositoryBuildContext,
        mapped_context: Dict[str, Any],
    ) -> BuildArtifactContext:
        """
        Produce a BuildArtifactContext from a RepositoryBuildContext.
        Both Dockerfile and docker-compose generators consume this.
        """
        strategy = repo_ctx.docker or BuildStrategy(
            strategy=STRATEGY_REPO_ROOT,
            context_path=".",
            dockerfile_path="Dockerfile",
        )

        # Derive compose paths from strategy so they always match
        if strategy.strategy == STRATEGY_BACKEND:
            compose_ctx = strategy.context_path      # "backend/app"
            compose_df  = "Dockerfile"
        elif strategy.strategy == STRATEGY_COMPOSE:
            compose_ctx = strategy.context_path
            compose_df  = strategy.dockerfile_path
        else:
            compose_ctx = strategy.context_path      # "."
            compose_df  = strategy.dockerfile_path   # "Dockerfile"

        ports: List[int] = []
        main_svc = mapped_context.get("main_service") or {}
        if main_svc.get("port"):
            try:
                ports.append(int(main_svc["port"]))
            except (TypeError, ValueError):
                pass

        return BuildArtifactContext(
            strategy=strategy,
            repository=repo_ctx,
            backend_root=repo_ctx.backend_root or ".",
            dependency_copy_instructions=repo_ctx.copy_instructions_for_deps(),
            compose_context=compose_ctx,
            compose_dockerfile=compose_df,
            exposed_ports=ports,
            runtime_assumptions={
                "framework": (main_svc.get("framework") or "").lower(),
                "language": (main_svc.get("language") or "").lower(),
            },
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_backend_root(
        self, known_files: List[str], mapped_context: Dict[str, Any]
    ) -> Optional[str]:
        # Prefer explicit service_root from mapper
        service_root = (mapped_context.get("service_root") or "").strip().strip("/")
        if service_root and service_root not in (".", ""):
            return service_root

        # Find the shallowest directory that contains a backend dep file
        best: Optional[str] = None
        best_depth = 999
        for f in known_files:
            normalized = f.lstrip("./")
            p = Path(normalized)
            if p.name.lower() in _PYTHON_DEP_NAMES and len(p.parts) > 1:
                parent = str(p.parent)
                depth  = len(p.parts) - 1
                if depth < best_depth:
                    # Prefer parent dirs that look like backend dirs
                    if any(root in parent.lower() for root in _BACKEND_ROOTS) or depth < best_depth:
                        best = parent
                        best_depth = depth

        if best:
            return best

        # Fall back to first top-level dir matching backend patterns
        top_dirs: Dict[str, int] = {}
        for f in known_files:
            parts = Path(f.lstrip("./")).parts
            if len(parts) > 1:
                top_dirs[parts[0].lower()] = top_dirs.get(parts[0].lower(), 0) + 1
        for d in _BACKEND_ROOTS:
            if d in top_dirs:
                return d
        return None

    def _find_frontend_root(self, known_files: List[str]) -> Optional[str]:
        for f in known_files:
            parts = Path(f.lstrip("./")).parts
            if len(parts) > 1 and parts[0].lower() in _FRONTEND_ROOTS:
                return parts[0]
        return None

    def _find_dependency_files(self, known_files: List[str]) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {"python": [], "node": [], "java": []}
        seen: set = set()
        for f in known_files:
            normalized = f.lstrip("./")
            if normalized in seen:
                continue
            name = Path(normalized).name.lower()
            if name in _PYTHON_DEP_NAMES:
                result["python"].append(normalized)
                seen.add(normalized)
            elif name in _NODE_DEP_NAMES:
                result["node"].append(normalized)
                seen.add(normalized)
            elif name in _JAVA_DEP_NAMES:
                result["java"].append(normalized)
                seen.add(normalized)
        # Sort by path depth (shallowest first) then alphabetically
        for lang in result:
            result[lang] = sorted(result[lang], key=lambda p: (len(Path(p).parts), p))
        return {k: v for k, v in result.items() if v}

    def _select_strategy(
        self,
        known_files: List[str],
        backend_root: Optional[str],
        compose_topology: Optional[Any],
        mapped_context: Dict[str, Any],
    ) -> BuildStrategy:
        # ── 1. Compose-driven: honour compose build context when explicit ──────
        if compose_topology and hasattr(compose_topology, "services"):
            for svc in compose_topology.services:
                if svc.build_context and svc.build_context not in (".", ".."):
                    ctx = svc.build_context.lstrip("./").rstrip("/")
                    df  = svc.build_dockerfile or "Dockerfile"
                    return BuildStrategy(
                        strategy=STRATEGY_COMPOSE,
                        context_path=ctx,
                        dockerfile_path=df,
                        recommended_copy_prefix=None,
                    )

        # ── 2. Explicit build_context from mapper ─────────────────────────────
        explicit_ctx = (mapped_context.get("build_context") or "").strip()

        if explicit_ctx and explicit_ctx not in (".", ""):
            # Explicit non-root context — files are relative to it
            return BuildStrategy(
                strategy=STRATEGY_BACKEND,
                context_path=explicit_ctx.rstrip("/"),
                dockerfile_path=f"{explicit_ctx.rstrip('/')}/Dockerfile",
                recommended_copy_prefix=None,
            )

        # ── 3. Repo-root context with monorepo subdirectory ───────────────────
        # Context = "." but backend source lives in a subdirectory
        if backend_root and backend_root not in (".", ""):
            return BuildStrategy(
                strategy=STRATEGY_REPO_ROOT,
                context_path=".",
                dockerfile_path="Dockerfile",
                recommended_copy_prefix=backend_root,
            )

        # ── 4. Flat single-service repo ───────────────────────────────────────
        return BuildStrategy(
            strategy=STRATEGY_REPO_ROOT,
            context_path=".",
            dockerfile_path="Dockerfile",
            recommended_copy_prefix=None,
        )
