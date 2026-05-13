"""
BlueprintLoader — loads, validates, and caches artifact blueprints from YAML files.

Blueprints live under:
    services/artifact_generation/blueprints/docker/*.yaml
    services/artifact_generation/blueprints/terraform/*.yaml  (future)
    services/artifact_generation/blueprints/kubernetes/*.yaml (future)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from backend.app.services.artifact_generation.models.blueprint import Blueprint

logger = logging.getLogger(__name__)

# Root directory containing blueprint subdirectories (docker/, terraform/, …)
_BLUEPRINTS_ROOT = Path(__file__).parent


class BlueprintLoader:
    """
    Loads artifact blueprints from YAML files and caches them in memory.

    Thread-safe for read-only access (blueprints never change at runtime).
    """

    def __init__(self, blueprints_root: Optional[Path] = None):
        self._root = blueprints_root or _BLUEPRINTS_ROOT
        # cache key: "{artifact_type}/{name}", e.g. "docker/python_fastapi"
        self._cache: Dict[str, Blueprint] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def load_all_docker(self) -> List[Blueprint]:
        """Load all blueprints from the docker/ subdirectory."""
        return self._load_from_dir(self._root / "docker", "docker")

    def load_by_name(
        self,
        name: str,
        artifact_type: str = "docker",
    ) -> Optional[Blueprint]:
        """
        Load a blueprint by filename stem (without .yaml extension).

        Example: load_by_name("python_fastapi") → loads docker/python_fastapi.yaml
        """
        cache_key = f"{artifact_type}/{name}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        path = self._root / artifact_type / f"{name}.yaml"
        if not path.exists():
            logger.warning("[BlueprintLoader] Blueprint file not found: %s", path)
            return None

        blueprint = self._parse_yaml(path)
        if blueprint:
            self._cache[cache_key] = blueprint
            logger.debug(
                "[BlueprintLoader] Loaded %s (id=%s, sections=%d)",
                path.name, blueprint.blueprint_id, len(blueprint.sections),
            )
        return blueprint

    def available_names(self, artifact_type: str = "docker") -> List[str]:
        """Return sorted list of available blueprint stems for an artifact type."""
        directory = self._root / artifact_type
        if not directory.exists():
            return []
        return sorted(p.stem for p in directory.glob("*.yaml"))

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _load_from_dir(self, directory: Path, artifact_type: str) -> List[Blueprint]:
        blueprints: List[Blueprint] = []
        if not directory.exists():
            logger.warning("[BlueprintLoader] Blueprint directory not found: %s", directory)
            return blueprints

        for yaml_path in sorted(directory.glob("*.yaml")):
            blueprint = self._parse_yaml(yaml_path)
            if blueprint:
                cache_key = f"{artifact_type}/{yaml_path.stem}"
                self._cache[cache_key] = blueprint
                blueprints.append(blueprint)

        logger.info(
            "[BlueprintLoader] Loaded %d blueprints from %s",
            len(blueprints), directory,
        )
        return blueprints

    @staticmethod
    def _parse_yaml(path: Path) -> Optional[Blueprint]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict):
                logger.error("[BlueprintLoader] %s: expected YAML mapping at root", path.name)
                return None
            return Blueprint.model_validate(data)
        except yaml.YAMLError as exc:
            logger.error("[BlueprintLoader] YAML parse error in %s: %s", path.name, exc)
            return None
        except Exception as exc:
            logger.error("[BlueprintLoader] Failed to load %s: %s", path.name, exc)
            return None
