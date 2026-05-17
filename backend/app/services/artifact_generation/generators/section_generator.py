"""
ArtifactSectionGenerator — generates blueprint section variables via constrained LLM prompts.

Key design:
  • ONE batched LLM call fills variables for ALL dynamic sections simultaneously.
  • Static sections (no placeholders) are rendered deterministically without LLM.
  • Deterministic fallbacks guarantee a rendered artifact even on total LLM failure.
  • RAG context is retrieved per-section before the batch call to enrich the prompt.

The LLM is asked to return a JSON object of the form:
  {
    "section_id": { "var_name": "value", ... },
    ...
  }

This is much more constrained than "generate the full Dockerfile" — the model
cannot hallucinate entire files, only variable values.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from backend.app.services.artifact_generation.models.blueprint import Blueprint, BlueprintSection
from backend.app.services.artifact_generation.models.generation import SectionGenerationResult
from backend.app.services.artifact_generation.rag.section_retriever import SectionAwareRetriever
from backend.app.services.core.llm_service import LLMService

logger = logging.getLogger(__name__)

# Maximum chars of RAG context injected per section in the batch prompt
_MAX_RAG_CHARS_PER_SECTION = 400
# Maximum chars of total RAG context in the batch prompt
_MAX_RAG_TOTAL_CHARS = 1200

# ── System prompt (invariant) ─────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are a DevSecOps infrastructure specialist generating Dockerfile section variables.

Task: fill variable values for the blueprint sections listed below.

=== CRITICAL RULES — VIOLATIONS CAUSE BUILD FAILURES ===

1. RETURN FORMAT
   Return ONLY a valid JSON object — no markdown, no code fences, no explanations.
   Top-level keys are section IDs; values are objects with variable name/value pairs.
   Do NOT generate Docker instructions — only fill the variable VALUES.

2. BASE IMAGES — use current, non-deprecated images
   Java JRE:   eclipse-temurin:17-jre  (NOT openjdk:17-jre-slim — it is removed from Docker Hub)
   Java JDK:   eclipse-temurin:17-jdk-alpine  (for builder stage)
   Python:     python:3.11-slim
   Node:       node:20-alpine
   Always pin a specific tag — never use :latest

3. DISTRO-AWARE USER CREATION
   eclipse-temurin:*-jre (no alpine suffix) → Debian → use:
     "groupadd -r appgroup && useradd -r -g appgroup appuser"
   eclipse-temurin:*-alpine OR alpine:* → Alpine → use:
     "addgroup -S appgroup && adduser -S appuser -G appgroup"
   python:*-slim → Debian → use:
     "groupadd -r appgroup && useradd -r -g appgroup appuser"
   NEVER mix Alpine commands with Debian images or vice-versa.

4. EXEC FORM — double quotes ONLY
   CMD and ENTRYPOINT variables must be valid JSON arrays with DOUBLE QUOTES:
     CORRECT:   ["java", "-jar", "app.jar"]
     CORRECT:   ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
     WRONG:     ['java', '-jar', 'app.jar']   ← single quotes are not JSON
     WRONG:     java -jar app.jar             ← shell form is not exec form

5. RUN COMMANDS — always shell form (no brackets)
   build_command, dependency_cache_command, install_command must be plain shell strings:
     CORRECT:   "mvn clean package -DskipTests -q"
     CORRECT:   "pip install --no-cache-dir --user -r requirements.txt"
     WRONG:     ["mvn", "clean", "package"]   ← RUN does NOT support exec form

6. HEALTHCHECK DEPENDENCIES
   If healthcheck_cmd uses "curl": the image must have curl installed.
   If the runtime image does NOT include curl by default, set healthcheck_cmd to:
     Debian: "curl -f http://localhost:{port}/actuator/health || exit 1"  (after apt install curl)
     Alpine: "wget -q --spider http://localhost:{port}/actuator/health || exit 1"
   For Spring Boot without actuator: use a TCP check instead:
     "echo 'GET / HTTP/1.0' | nc localhost {port} || exit 1"

7. SPRING BOOT SPECIFICS
   jar_path: use "target/*.jar" (Maven) or "build/libs/*.jar" (Gradle)
   build_command: "mvn clean package -DskipTests -q" for Maven
   dependency_cache_command: "mvn dependency:go-offline -q"
   startup_command: ["java", "-jar", "app.jar"]

Never include real secrets, passwords, or API keys.
Adapt ALL values to the specific project context provided.\
"""


class ArtifactSectionGenerator:
    """
    Generates variables for all blueprint sections in one batched LLM call.

    Workflow:
      1. Partition sections into static (render direct) and dynamic (need LLM).
      2. Retrieve per-section RAG context for dynamic sections.
      3. Build one constrained batch prompt listing every dynamic section.
      4. Call LLM once → parse nested JSON of section variables.
      5. Render each section template with its variables.
      6. Fall back to deterministic variable values if LLM call fails.
    """

    def __init__(
        self,
        llm: LLMService,
        section_retriever: Optional[SectionAwareRetriever] = None,
    ):
        self.llm = llm
        self.retriever = section_retriever or SectionAwareRetriever()

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_all_sections(
        self,
        blueprint: Blueprint,
        project_context: Dict[str, Any],
        corrector_feedback: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, SectionGenerationResult]:
        """
        Generate all section results for a blueprint in one pass.

        Returns:
            Mapping of section_id → SectionGenerationResult (preserves blueprint order).
        """
        start = time.monotonic()
        framework = _extract_framework(project_context)
        language = _extract_language(project_context)

        static_sections = blueprint.static_sections()
        dynamic_sections = blueprint.dynamic_sections()

        logger.info(
            "[SectionGenerator] blueprint=%s static=%d dynamic=%d framework=%s lang=%s",
            blueprint.blueprint_id,
            len(static_sections),
            len(dynamic_sections),
            framework,
            language,
        )

        results: Dict[str, SectionGenerationResult] = {}

        # ── 1. Static sections — no LLM needed ───────────────────────────────
        for section in static_sections:
            results[section.id] = SectionGenerationResult(
                section_id=section.id,
                blueprint_id=blueprint.blueprint_id,
                variables={},
                rendered_content=section.template.strip(),
                rag_sources=[],
                generation_time_ms=0.0,
                used_fallback=False,
            )

        # ── 2. Dynamic sections — one batched LLM call ────────────────────────
        if dynamic_sections:
            rag_by_section = self._retrieve_rag_for_sections(
                dynamic_sections, framework, language, project_context
            )

            try:
                all_variables = self._call_llm_batch(
                    blueprint=blueprint,
                    dynamic_sections=dynamic_sections,
                    project_context=project_context,
                    rag_by_section=rag_by_section,
                    corrector_feedback=corrector_feedback,
                )
                used_fallback = False
                fallback_error: Optional[str] = None
            except Exception as exc:
                logger.warning(
                    "[SectionGenerator] LLM batch call failed: %s — using deterministic fallbacks",
                    exc,
                )
                all_variables = {}
                used_fallback = True
                fallback_error = str(exc)

            for section in dynamic_sections:
                variables = all_variables.get(section.id) or {}
                if not variables:
                    # LLM omitted this section or returned bad data → use fallbacks
                    variables = _deterministic_fallbacks(section, project_context)
                    used_fallback = True

                rendered = _render_template(section.template, variables)
                rag_info = rag_by_section.get(section.id, {})

                results[section.id] = SectionGenerationResult(
                    section_id=section.id,
                    blueprint_id=blueprint.blueprint_id,
                    variables=variables,
                    rendered_content=rendered,
                    rag_sources=rag_info.get("sources", []),
                    generation_time_ms=0.0,
                    used_fallback=used_fallback,
                    error=fallback_error if used_fallback else None,
                )

        elapsed_ms = round((time.monotonic() - start) * 1000, 2)
        logger.info(
            "[SectionGenerator] Completed %d sections in %.1fms (fallback=%s)",
            len(results),
            elapsed_ms,
            any(r.used_fallback for r in results.values()),
        )

        return results

    # ── LLM batch call ────────────────────────────────────────────────────────

    def _call_llm_batch(
        self,
        blueprint: Blueprint,
        dynamic_sections: List[BlueprintSection],
        project_context: Dict[str, Any],
        rag_by_section: Dict[str, Dict[str, Any]],
        corrector_feedback: Optional[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        user_prompt = _build_batch_user_prompt(
            blueprint=blueprint,
            dynamic_sections=dynamic_sections,
            project_context=project_context,
            rag_by_section=rag_by_section,
            corrector_feedback=corrector_feedback,
            max_rag_total=_MAX_RAG_TOTAL_CHARS,
        )

        response = self.llm.chat_json(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=1500,
        )

        if not isinstance(response, dict):
            raise ValueError(f"LLM returned {type(response).__name__}, expected dict")

        # Normalise: unwrap any top-level "sections" key some models add
        if "sections" in response and isinstance(response["sections"], dict):
            response = response["sections"]

        logger.debug(
            "[SectionGenerator] LLM returned variables for sections: %s",
            list(response.keys()),
        )
        return response

    # ── RAG retrieval ─────────────────────────────────────────────────────────

    def _retrieve_rag_for_sections(
        self,
        sections: List[BlueprintSection],
        framework: str,
        language: str,
        project_context: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        # Only retrieve for sections that have RAG tags (skip trivial sections)
        section_ids = [s.id for s in sections if s.rag_tags]
        if not section_ids:
            return {}

        results = self.retriever.retrieve_for_sections(
            section_ids=section_ids,
            framework=framework,
            language=language,
            project_context=project_context,
            top_k=2,
        )

        hits = sum(1 for r in results.values() if r.get("available"))
        logger.debug(
            "[SectionGenerator] RAG retrieval: %d/%d sections hit",
            hits, len(section_ids),
        )
        return results


# ── Prompt construction ───────────────────────────────────────────────────────

def _build_batch_user_prompt(
    blueprint: Blueprint,
    dynamic_sections: List[BlueprintSection],
    project_context: Dict[str, Any],
    rag_by_section: Dict[str, Dict[str, Any]],
    corrector_feedback: Optional[Dict[str, Any]],
    max_rag_total: int,
) -> str:
    main_service = project_context.get("main_service") or {}
    runtime = project_context.get("runtime") or {}
    framework = _extract_framework(project_context)
    language = _extract_language(project_context)

    lines: List[str] = [
        f"Blueprint: {blueprint.blueprint_id}",
        f"Artifact:  {blueprint.artifact_type}",
        "",
        "Project context:",
        f"  language:         {language or 'unknown'}",
        f"  framework:        {framework or 'unknown'}",
        f"  port:             {main_service.get('port') or _default_port(framework)}",
        f"  entrypoint:       {main_service.get('entrypoint') or ''}",
        f"  run_command:      {main_service.get('run_command') or ''}",
        f"  python_version:   {runtime.get('python_version') or ''}",
        f"  java_version:     {runtime.get('java_version') or ''}",
        f"  node_version:     {runtime.get('node_version') or ''}",
        f"  package_managers: {', '.join(runtime.get('package_managers') or [])}",
        f"  dependency_files: {', '.join((runtime.get('dependency_files') or [])[:3])}",
        "",
    ]

    # ── Repository build context block (CRITICAL for correct COPY paths) ──────
    repo_ctx_dict = project_context.get("repository_build_context") or {}
    docker_strategy = repo_ctx_dict.get("docker") or {}
    if docker_strategy:
        ctx_path  = docker_strategy.get("context_path", ".")
        df_path   = docker_strategy.get("dockerfile_path", "Dockerfile")
        strategy  = docker_strategy.get("strategy", "repo_root_context")
        dep_files = repo_ctx_dict.get("dependency_files") or {}
        copy_instrs = repo_ctx_dict.get("copy_instructions") or {}

        lines += [
            "=== REPOSITORY BUILD CONTEXT (use these exact paths in COPY instructions) ===",
            f"  build strategy:   {strategy}",
            f"  context path:     {ctx_path}",
            f"  dockerfile path:  {df_path}",
        ]
        if dep_files:
            for lang, files in dep_files.items():
                if files:
                    lines.append(f"  {lang} deps in repo: {', '.join(files[:3])}")
        if copy_instrs:
            lines.append("")
            lines.append("  CORRECT COPY instructions (use EXACTLY these — do NOT invent paths):")
            for lang, instr in copy_instrs.items():
                lines.append(f"    {lang}: {instr}")

        # Generate explicit COPY rules when context is repo root and files are in subdirectory
        copy_prefix = docker_strategy.get("recommended_copy_prefix")
        if ctx_path in (".", "") and copy_prefix:
            lines += [
                "",
                f"  WARNING: Build context is '{ctx_path}' but source files are in '{copy_prefix}/'.",
                f"  All COPY sources MUST include the '{copy_prefix}/' prefix:",
                f"    ✓ CORRECT: COPY {copy_prefix}/requirements.txt ./requirements.txt",
                f"    ✗ WRONG:   COPY requirements.txt .  (file is NOT at repo root)",
                f"    ✓ CORRECT: COPY {copy_prefix}/main.py ./main.py",
                f"    ✗ WRONG:   COPY main.py .  (file is NOT at repo root)",
            ]
        lines.append("=== END REPOSITORY BUILD CONTEXT ===")
        lines.append("")

    # Corrector feedback (if any)
    if corrector_feedback:
        global_issues = corrector_feedback.get("issues") or []
        if global_issues:
            lines.append("Fix these issues from the previous attempt:")
            for issue in global_issues[:5]:
                lines.append(f"  - {issue}")
            lines.append("")

    # RAG context block (total budget capped)
    rag_total_chars = 0
    rag_lines: List[str] = []
    for section in dynamic_sections:
        rag_info = rag_by_section.get(section.id, {})
        if not rag_info.get("available"):
            continue
        block = (rag_info.get("context_block") or "").strip()
        if not block:
            continue
        truncated = block[:_MAX_RAG_CHARS_PER_SECTION]
        if rag_total_chars + len(truncated) > max_rag_total:
            break
        rag_lines.append(f"[{section.id}] {truncated}")
        rag_total_chars += len(truncated)

    if rag_lines:
        lines.append("Relevant best practices (from knowledge base):")
        lines.extend(rag_lines)
        lines.append("")

    # Section variable specs
    lines.append("Fill variables for these sections:")
    lines.append("")
    for section in dynamic_sections:
        lines.append(f"Section \"{section.id}\":")
        lines.append(f"  Description: {section.description}")
        lines.append("  Template:")
        for tl in section.template.strip().splitlines():
            lines.append(f"    {tl}")
        if section.required_variables:
            lines.append(f"  Required: {', '.join(section.required_variables)}")
        if section.optional_variables:
            lines.append(f"  Optional: {', '.join(section.optional_variables)}")
        # Section-specific corrector feedback
        if corrector_feedback:
            section_errors = (corrector_feedback.get("section_errors") or {}).get(section.id, [])
            if section_errors:
                lines.append(f"  Fix: {'; '.join(section_errors[:3])}")
        lines.append("")

    # Expected output format
    lines.append("Return ONLY this JSON (all section IDs as keys):")
    example: Dict[str, Any] = {}
    for section in dynamic_sections:
        example[section.id] = {v: "..." for v in section.required_variables[:2]}
    import json
    lines.append(json.dumps(example, indent=2))

    return "\n".join(lines)


# ── Template rendering ────────────────────────────────────────────────────────

def _render_template(template: str, variables: Dict[str, Any]) -> str:
    """Replace {{ variable }} placeholders with provided values."""
    def _replace(match: re.Match) -> str:  # type: ignore[type-arg]
        key = match.group(1).strip()
        return str(variables.get(key, f"{{{{ {key} }}}}"))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", _replace, template)


# ── Deterministic fallbacks ───────────────────────────────────────────────────

def _deterministic_fallbacks(
    section: BlueprintSection,
    project_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Return deterministic variable values for a section when LLM is unavailable.

    The goal is a syntactically valid artifact, not a perfect one.
    These values are overridden by the LLM in normal operation.

    IMPORTANT: requirements_file and dependency_file return the full repo-relative
    path (e.g., "backend/app/requirements-backend.txt") so that COPY instructions
    are correct when the build context is the repository root.
    """
    main_service = project_context.get("main_service") or {}
    runtime = project_context.get("runtime") or {}
    language = (main_service.get("language") or "").lower()
    framework = (main_service.get("framework") or "").lower()
    port = str(main_service.get("port") or _default_port(framework))

    # Use repo-relative path for requirements so COPY is correct for monorepos
    req_file = _requirements_file(language, runtime)

    all_vars: Dict[str, Any] = {
        # ── Images ──────────────────────────────────────────────────────────
        "builder_image": _builder_image(language, runtime),
        "runtime_image": _runtime_image(language, runtime),
        "base_image": _runtime_image(language, runtime),
        # ── Paths ────────────────────────────────────────────────────────────
        "workdir": "/app",
        # ── Build ────────────────────────────────────────────────────────────
        # Full repo-relative path (e.g., "backend/app/requirements-backend.txt")
        "requirements_file": req_file,
        "dependency_file": req_file,
        "build_file": _build_file(language),
        "dependency_cache_command": _dep_cache_cmd(language),
        "build_command": _build_cmd(language, framework),
        "install_command": _install_cmd_for_file(language, req_file),
        "package_files": _package_files(language),
        "jar_path": "target/*.jar",
        # ── Network ──────────────────────────────────────────────────────────
        "port": port,
        # ── Security ─────────────────────────────────────────────────────────
        # Default to Debian-style (eclipse-temurin JRE is Debian-based)
        "create_user_command": _create_user_command(language, runtime),
        "app_user": "appuser",
        # ── Startup ──────────────────────────────────────────────────────────
        "startup_command": _startup_command(language, framework, main_service, port),
        # ── Health check ─────────────────────────────────────────────────────
        "healthcheck_interval": "30s",
        "healthcheck_timeout": "10s",
        "healthcheck_retries": "3",
        "healthcheck_cmd": f"curl -f http://localhost:{port}/health || exit 1",
    }

    return {k: all_vars[k] for k in section.all_variables if k in all_vars}


# ── Per-field deterministic helpers ──────────────────────────────────────────

def _builder_image(language: str, runtime: Dict[str, Any]) -> str:
    py = runtime.get("python_version") or "3.11"
    java = runtime.get("java_version") or "17"
    node = runtime.get("node_version") or "20"
    mapping = {
        "python": f"python:{py}-slim",
        "java": f"eclipse-temurin:{java}-jdk-alpine",
        "kotlin": f"eclipse-temurin:{java}-jdk-alpine",
        "javascript": f"node:{node}-alpine",
        "typescript": f"node:{node}-alpine",
    }
    return mapping.get(language, "alpine:3.19")


def _runtime_image(language: str, runtime: Dict[str, Any]) -> str:
    py = runtime.get("python_version") or "3.11"
    java = runtime.get("java_version") or "17"
    node = runtime.get("node_version") or "20"
    mapping = {
        "python": f"python:{py}-slim",
        "java": f"eclipse-temurin:{java}-jre-alpine",
        "kotlin": f"eclipse-temurin:{java}-jre-alpine",
        "javascript": f"node:{node}-alpine",
        "typescript": f"node:{node}-alpine",
    }
    return mapping.get(language, "alpine:3.19")


def _requirements_file(language: str, runtime: Dict[str, Any]) -> str:
    # Prefer the full repo-relative path from dependency_files (correct for monorepos)
    dep_files: List[str] = runtime.get("dependency_files") or []
    if dep_files:
        return dep_files[0]
    mapping = {
        "python": "requirements.txt",
        "java": "pom.xml",
        "kotlin": "build.gradle",
        "javascript": "package.json",
        "typescript": "package.json",
    }
    return mapping.get(language, "requirements.txt")


def _requirements_copy_instruction(language: str, project_context: Dict[str, Any]) -> str:
    """
    Return the correct COPY instruction for the primary dependency file,
    accounting for the build context.  Prefers the precomputed copy_instructions
    from RepositoryBuildContext; falls back to a plain COPY using the runtime path.
    """
    repo_ctx = project_context.get("repository_build_context") or {}
    copy_instrs = repo_ctx.get("copy_instructions") or {}
    if language in copy_instrs:
        return copy_instrs[language]

    # Fallback: compute from runtime dependency_files
    runtime = project_context.get("runtime") or {}
    dep_file = _requirements_file(language, runtime)
    filename = dep_file.split("/")[-1]
    return f"COPY {dep_file} ./{filename}"


def _build_file(language: str) -> str:
    mapping = {"java": "pom.xml", "kotlin": "build.gradle"}
    return mapping.get(language, "pom.xml")


def _package_files(language: str) -> str:
    return "package*.json" if language in ("javascript", "typescript") else "package.json"


def _dep_cache_cmd(language: str) -> str:
    mapping = {
        "java": "mvn dependency:go-offline -q",
        "kotlin": "gradle dependencies --no-daemon -q",
        "javascript": "npm ci --only=production",
        "typescript": "npm ci --only=production",
    }
    return mapping.get(language, "mvn dependency:go-offline -q")


def _build_cmd(language: str, framework: str) -> str:
    if language in ("java", "kotlin", "scala"):
        if "gradle" in framework:
            return "gradle build -x test --no-daemon -q"
        return "mvn clean package -DskipTests -q"
    return "mvn clean package -DskipTests -q"


def _install_cmd(language: str) -> str:
    mapping = {
        "python": "pip install --no-cache-dir --user -r requirements.txt",
        "javascript": "npm ci --only=production",
        "typescript": "npm ci --only=production",
    }
    return mapping.get(language, "pip install --no-cache-dir -r requirements.txt")


def _install_cmd_for_file(language: str, req_file: str) -> str:
    """Like _install_cmd but uses the actual file name (basename) after COPY."""
    filename = req_file.split("/")[-1]  # basename — this is what ends up in WORKDIR after COPY
    if language == "python":
        return f"pip install --no-cache-dir -r {filename}"
    if language in ("javascript", "typescript"):
        return "npm ci --only=production"
    return f"pip install --no-cache-dir -r {filename}"


def _default_port(framework: str) -> int:
    ports = {
        "fastapi": 8000, "flask": 5000, "django": 8000,
        "spring": 8080, "springboot": 8080, "spring_boot": 8080,
        "express": 3000, "fastify": 3000, "nestjs": 3000,
    }
    return ports.get((framework or "").lower(), 8080)


def _startup_command(
    language: str,
    framework: str,
    main_service: Dict[str, Any],
    port: str,
) -> str:
    if cmd := main_service.get("run_command"):
        return f'["{cmd}"]'
    ep = main_service.get("entrypoint") or "main"
    fw = framework.lower()
    if language == "python":
        if any(f in fw for f in ("fastapi", "uvicorn", "starlette")):
            return f'["uvicorn", "{ep}:app", "--host", "0.0.0.0", "--port", "{port}"]'
        if "gunicorn" in fw or "flask" in fw or "django" in fw:
            return f'["gunicorn", "--bind", "0.0.0.0:{port}", "{ep}:app"]'
        return '["python", "app.py"]'
    if language in ("java", "kotlin"):
        return '["java", "-jar", "app.jar"]'
    if language in ("javascript", "typescript"):
        return '["node", "dist/index.js"]'
    return '["sh", "-c", "echo No startup command configured"]'


def _extract_framework(context: Dict[str, Any]) -> str:
    main_service = context.get("main_service") or {}
    if fw := main_service.get("framework"):
        return fw
    runtime = context.get("runtime") or {}
    fws: List[str] = runtime.get("frameworks") or []
    return fws[0] if fws else ""


def _extract_language(context: Dict[str, Any]) -> str:
    main_service = context.get("main_service") or {}
    if lang := main_service.get("language"):
        return lang
    runtime = context.get("runtime") or {}
    langs: List[str] = runtime.get("languages") or []
    return langs[0] if langs else ""


def _create_user_command(language: str, runtime: Dict[str, Any]) -> str:
    """
    Return the correct user+group creation command for the runtime image's distro.

    eclipse-temurin (no alpine suffix) → Debian → groupadd/useradd
    node:*-alpine, eclipse-temurin:*-alpine, python:*-alpine → Alpine → addgroup/adduser
    python:*-slim → Debian → groupadd/useradd (default for python)
    """
    runtime_img = _runtime_image(language, runtime).lower()
    if "alpine" in runtime_img:
        return "addgroup -S appgroup && adduser -S appuser -G appgroup"
    # Debian / slim / temurin non-alpine
    return "groupadd -r appgroup && useradd -r -g appgroup appuser"
