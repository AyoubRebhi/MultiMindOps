"""
BlueprintSelector — picks the best-matching blueprint for a given project context.

Selection priority:
  1. Exact framework match  (fastapi → python_fastapi)
  2. Language match         (python  → python_fastapi)
  3. Generic fallback       (generic_multi_stage)
  4. First available        (last resort)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from backend.app.services.artifact_generation.blueprints.loader import BlueprintLoader
from backend.app.services.artifact_generation.models.blueprint import Blueprint

logger = logging.getLogger(__name__)

# framework name (lowercased) → blueprint filename stem
_FRAMEWORK_MAP: Dict[str, str] = {
    # Python ASGI / WSGI
    "fastapi": "python_fastapi",
    "flask": "python_fastapi",
    "django": "python_fastapi",
    "uvicorn": "python_fastapi",
    "gunicorn": "python_fastapi",
    "starlette": "python_fastapi",
    "aiohttp": "python_fastapi",
    "tornado": "python_fastapi",
    # Java / JVM
    "spring": "spring_boot",
    "springboot": "spring_boot",
    "spring_boot": "spring_boot",
    "spring-boot": "spring_boot",
    "quarkus": "spring_boot",
    "micronaut": "spring_boot",
    "helidon": "spring_boot",
    "vert.x": "spring_boot",
    "vertx": "spring_boot",
    # Node.js
    "express": "node_express",
    "fastify": "node_express",
    "nestjs": "node_express",
    "nest": "node_express",
    "koa": "node_express",
    "hapi": "node_express",
    "next": "node_express",
    "nuxt": "node_express",
    "remix": "node_express",
}

# language (lowercased) → blueprint filename stem
_LANGUAGE_MAP: Dict[str, str] = {
    "python": "python_fastapi",
    "java": "spring_boot",
    "kotlin": "spring_boot",
    "scala": "spring_boot",
    "groovy": "spring_boot",
    "javascript": "node_express",
    "typescript": "node_express",
    "js": "node_express",
    "ts": "node_express",
}


class BlueprintSelector:
    """
    Selects the best-matching Docker blueprint for a given project context.

    The selector is intentionally simple and deterministic — no LLM involved.
    All selection logic is based on the project context extracted by
    InfrastructureContextMapper.
    """

    def __init__(self, loader: Optional[BlueprintLoader] = None):
        self._loader = loader or BlueprintLoader()

    def select(self, project_context: Dict[str, Any]) -> Blueprint:
        """
        Return the best-matching blueprint for the project.

        Args:
            project_context: Output of InfrastructureContextMapper.map().

        Returns:
            A Blueprint ready for section generation.

        Raises:
            ValueError: When no blueprints are available (misconfigured install).
        """
        framework = self._extract_framework(project_context)
        language = self._extract_language(project_context)

        logger.info(
            "[BlueprintSelector] Selecting blueprint: framework=%r language=%r",
            framework, language,
        )

        # 1. Framework exact match (separator/case-insensitive: "Spring Boot",
        #    "spring-boot", "springBoot" all resolve to the same blueprint).
        if framework:
            blueprint = self._try_load(self._lookup(_FRAMEWORK_MAP, framework))
            if blueprint:
                logger.info(
                    "[BlueprintSelector] Matched by framework %r → %s",
                    framework, blueprint.blueprint_id,
                )
                return blueprint

        # 2. Language fallback
        if language:
            blueprint = self._try_load(self._lookup(_LANGUAGE_MAP, language))
            if blueprint:
                logger.info(
                    "[BlueprintSelector] Matched by language %r → %s",
                    language, blueprint.blueprint_id,
                )
                return blueprint

        # 3. Generic multi-stage
        blueprint = self._loader.load_by_name("generic_multi_stage")
        if blueprint:
            logger.info("[BlueprintSelector] Using generic_multi_stage blueprint")
            return blueprint

        # 4. Any available blueprint as last resort
        all_blueprints = self._loader.load_all_docker()
        if all_blueprints:
            logger.warning(
                "[BlueprintSelector] Falling back to first available blueprint: %s",
                all_blueprints[0].blueprint_id,
            )
            return all_blueprints[0]

        raise ValueError(
            "No blueprints available. Ensure blueprints/docker/*.yaml files exist."
        )

    # ── Lookup ────────────────────────────────────────────────────────────────

    @staticmethod
    def _lookup(table: Dict[str, str], raw: str) -> str:
        """Resolve a framework/language string to a blueprint stem, tolerant of
        case and separators. 'Spring Boot', 'spring-boot', 'springBoot' and
        'spring_boot' all collapse to the same key before lookup."""
        key = raw.strip().lower()
        if key in table:
            return table[key]
        # Normalize separators: drop spaces/hyphens/underscores/dots entirely and
        # compare against equally-normalized table keys.
        def _norm(s: str) -> str:
            return s.replace(" ", "").replace("-", "").replace("_", "").replace(".", "")
        nkey = _norm(key)
        for table_key, stem in table.items():
            if _norm(table_key) == nkey:
                return stem
        return ""

    # ── Context extraction ────────────────────────────────────────────────────

    @staticmethod
    def _extract_framework(context: Dict[str, Any]) -> Optional[str]:
        main_service = context.get("main_service") or {}
        if fw := main_service.get("framework"):
            return fw
        runtime = context.get("runtime") or {}
        frameworks: List[str] = runtime.get("frameworks") or []
        return frameworks[0] if frameworks else None

    @staticmethod
    def _extract_language(context: Dict[str, Any]) -> Optional[str]:
        main_service = context.get("main_service") or {}
        if lang := main_service.get("language"):
            return lang
        runtime = context.get("runtime") or {}
        languages: List[str] = runtime.get("languages") or []
        return languages[0] if languages else None

    def _try_load(self, blueprint_name: str) -> Optional[Blueprint]:
        if not blueprint_name:
            return None
        return self._loader.load_by_name(blueprint_name)
