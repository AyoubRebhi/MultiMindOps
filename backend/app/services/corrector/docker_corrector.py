"""
Docker Corrector Agent — analyzes Docker build failures and produces
structured remediation suggestions.

Pipeline (deterministic-first, LLM-second):
  1. LogSanitizer  — strip ANSI / noise / duplicates from raw logs
  2. ErrorExtractor — regex-based structured extraction
  3. FailureClassifier — deterministic taxonomy classification
  4. LLM enrichment (optional) — enrich root_cause + fix explanations
  5. Return CorrectorResult conforming to platform schema

The agent NEVER writes files, NEVER triggers retries, NEVER modifies state.
All exceptions are caught internally; analyze() always returns a result.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from .base_corrector import BaseCorrectorAgent
from .error_extractor import extract_errors
from .failure_classifier import classify_failure
from .log_sanitizer import extract_error_section, sanitize_logs
from .remediation_models import (
    CorrectorResult,
    ExtractedError,
    FailureClassification,
    FailureType,
    RemediationFix,
    RemediationSeverity,
)

logger = logging.getLogger(__name__)

# ── Deterministic fix library (one entry per FailureType) ─────────────────────
#
# Each value is a list of dicts that map directly to RemediationFix fields.
# These are the fallback fixes used when no LLM is available, and also the
# baseline that LLM output can replace.

_DEFAULT_FIXES: Dict[FailureType, List[Dict[str, Any]]] = {

    FailureType.DEPENDENCY_FAILURE: [
        {
            "title": "Verify import name matches installed package name",
            "explanation": (
                "Some packages use different import names from their install name. "
                "For example, `PIL` is installed as `Pillow`, and `cv2` as `opencv-python`. "
                "Cross-reference the failing import with your requirements file."
            ),
            "patch": "# requirements.txt — use the correct install name:\nPillow  # not PIL",
            "severity": RemediationSeverity.HIGH,
            "applies_to": "requirements.txt",
        },
        {
            "title": "Ensure RUN pip install executes before the failing import",
            "explanation": (
                "The package installation step must appear in the Dockerfile before "
                "any COPY or RUN step that imports the module."
            ),
            "patch": "COPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .",
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Check for platform-specific wheels",
            "explanation": (
                "If the package has native extensions, ensure you have the build tools "
                "installed first. Add `build-essential` and `python3-dev` via apt."
            ),
            "patch": "RUN apt-get update && apt-get install -y --no-install-recommends build-essential python3-dev",
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.PERMISSION_FAILURE: [
        {
            "title": "Add chmod to make scripts executable",
            "explanation": (
                "The build failed because a file or directory was not accessible. "
                "Add an explicit `chmod` step before the failing command."
            ),
            "patch": "RUN chmod +x /app/entrypoint.sh",
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Fix ownership with chown",
            "explanation": (
                "Ensure the target directory and its contents are owned by the user "
                "that will run the process."
            ),
            "patch": "RUN chown -R appuser:appuser /app",
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Install packages as root, then switch to non-root user",
            "explanation": (
                "Perform all package installations before switching to a non-root "
                "USER directive. Package managers typically require root access."
            ),
            "patch": (
                "# Install first (as root), then drop privileges:\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "RUN useradd -m -r appuser\n"
                "USER appuser"
            ),
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.MISSING_FILE: [
        {
            "title": "Verify COPY source path exists in the build context",
            "explanation": (
                "The file referenced in a COPY or ADD instruction does not exist "
                "in the Docker build context. Check the path is relative to the "
                "directory where `docker build` is run, not the Dockerfile location."
            ),
            "patch": (
                "# Correct COPY syntax:\n"
                "COPY requirements.txt /app/requirements.txt\n"
                "# The file ./requirements.txt must exist in the build context."
            ),
            "severity": RemediationSeverity.CRITICAL,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Review .dockerignore for accidental exclusions",
            "explanation": (
                ".dockerignore patterns may be excluding files that the Dockerfile "
                "needs. Open .dockerignore and check for overly broad patterns like "
                "`*` or `*.txt`."
            ),
            "severity": RemediationSeverity.HIGH,
            "applies_to": ".dockerignore",
        },
        {
            "title": "Use WORKDIR before relative COPY paths",
            "explanation": (
                "Set WORKDIR before using relative destination paths in COPY/ADD "
                "to avoid ambiguous resolution."
            ),
            "patch": "WORKDIR /app\nCOPY . .",
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.NETWORK_FAILURE: [
        {
            "title": "Retry with a package mirror or alternate registry",
            "explanation": (
                "A network connectivity failure occurred during package download. "
                "Try using an explicit mirror URL or a local cache proxy."
            ),
            "patch": (
                "# pip with explicit index:\n"
                "RUN pip install --no-cache-dir --index-url https://pypi.org/simple/ -r requirements.txt\n\n"
                "# npm with explicit registry:\n"
                "RUN npm install --registry https://registry.npmjs.org"
            ),
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Build with --network=host to bypass Docker NAT",
            "explanation": (
                "DNS resolution may fail inside the Docker build network. "
                "Building with `--network=host` makes the host network directly "
                "available to the build process."
            ),
            "patch": "# docker build --network=host -t myimage .",
            "severity": RemediationSeverity.MEDIUM,
        },
        {
            "title": "Propagate proxy settings via build arguments",
            "explanation": (
                "If the host is behind a corporate proxy, pass proxy settings "
                "as build arguments."
            ),
            "patch": (
                "ARG HTTP_PROXY\n"
                "ARG HTTPS_PROXY\n"
                "ARG NO_PROXY\n"
                "ENV http_proxy=$HTTP_PROXY \\\n"
                "    https_proxy=$HTTPS_PROXY \\\n"
                "    no_proxy=$NO_PROXY"
            ),
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.SYNTAX_ERROR: [
        {
            "title": "Fix syntax error at the line indicated in the build output",
            "explanation": (
                "A syntax error was detected in application code or a configuration "
                "file. Locate the file and line number shown in the error output and "
                "correct the syntax."
            ),
            "severity": RemediationSeverity.CRITICAL,
        },
        {
            "title": "Lint source files before building",
            "explanation": (
                "Add a linting step early in the Dockerfile to surface syntax errors "
                "before reaching expensive compilation or install steps."
            ),
            "patch": (
                "# Python:\n"
                "RUN python -m py_compile your_module.py\n\n"
                "# JavaScript/TypeScript:\n"
                "RUN npx eslint . --max-warnings 0\n\n"
                "# Dockerfile itself:\n"
                "# hadolint Dockerfile"
            ),
            "severity": RemediationSeverity.HIGH,
        },
    ],

    FailureType.PACKAGE_MANAGER_FAILURE: [
        {
            "title": "Pin package versions to a known-compatible set",
            "explanation": (
                "Package resolution failed, often due to conflicting or unavailable "
                "version constraints. Pin all direct dependencies to exact versions "
                "that are known to work together."
            ),
            "patch": (
                "# requirements.txt — pin exact versions:\n"
                "Flask==3.0.3\n"
                "requests==2.31.0\n\n"
                "# package.json — use exact versions (remove ^ or ~):\n"
                "\"express\": \"4.18.2\""
            ),
            "severity": RemediationSeverity.HIGH,
        },
        {
            "title": "Update the package index before installing",
            "explanation": (
                "The package index in the base image may be stale. Run the package "
                "manager's update command before install to get fresh metadata."
            ),
            "patch": (
                "# apt:\n"
                "RUN apt-get update && apt-get install -y --no-install-recommends pkg-name\n\n"
                "# Alpine:\n"
                "RUN apk update && apk add --no-cache pkg-name"
            ),
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Use --no-cache-dir with pip to avoid cache corruption",
            "explanation": (
                "pip's local cache can occasionally become corrupted. "
                "Use --no-cache-dir to force fresh downloads and eliminate "
                "the cache as a source of non-determinism."
            ),
            "patch": "RUN pip install --no-cache-dir -r requirements.txt",
            "severity": RemediationSeverity.LOW,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.BASE_IMAGE_FAILURE: [
        {
            "title": "Verify base image name and tag on Docker Hub",
            "explanation": (
                "The FROM directive references an image or tag that could not be "
                "pulled. Check for typos and confirm the tag exists at "
                "hub.docker.com (or your private registry)."
            ),
            "patch": (
                "# Use a verified tag:\n"
                "FROM python:3.11-slim\n\n"
                "# Check available tags:\n"
                "# https://hub.docker.com/_/python/tags"
            ),
            "severity": RemediationSeverity.CRITICAL,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Use a fully-qualified image reference for private registries",
            "explanation": (
                "When pulling from a private registry, prefix the image with the "
                "full registry hostname."
            ),
            "patch": "FROM registry.example.com/myteam/baseimage:1.2.3",
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Authenticate to the registry before building",
            "explanation": (
                "Private registry images require `docker login` before the build. "
                "Ensure registry credentials are configured in the CI environment."
            ),
            "patch": "# docker login registry.example.com -u $REGISTRY_USER -p $REGISTRY_PASSWORD",
            "severity": RemediationSeverity.HIGH,
        },
    ],

    FailureType.ENVIRONMENT_VARIABLE_FAILURE: [
        {
            "title": "Declare build-time variables with ARG",
            "explanation": (
                "Variables needed only during the build (not at runtime) should "
                "be declared with ARG. Pass their values with --build-arg."
            ),
            "patch": (
                "# Dockerfile:\n"
                "ARG API_KEY\n"
                "RUN echo \"Using API_KEY=$API_KEY\"\n\n"
                "# Build command:\n"
                "# docker build --build-arg API_KEY=$MY_API_KEY ."
            ),
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Declare runtime variables with ENV",
            "explanation": (
                "Variables needed by the running container should be declared "
                "with ENV. They can have default values or be overridden at "
                "`docker run` time with -e."
            ),
            "patch": (
                "ENV DATABASE_URL=postgresql://localhost/mydb \\\n"
                "    LOG_LEVEL=INFO"
            ),
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.BUILD_CONTEXT_FAILURE: [
        {
            "title": "Run docker build from the correct directory",
            "explanation": (
                "The build context is the directory passed to `docker build` "
                "(usually `.`). All COPY/ADD paths in the Dockerfile are relative "
                "to this directory. Ensure you are running docker build from the "
                "project root."
            ),
            "patch": (
                "# Correct: build from project root:\n"
                "docker build -t myimage .\n\n"
                "# Or specify Dockerfile explicitly:\n"
                "docker build -f docker/Dockerfile -t myimage ."
            ),
            "severity": RemediationSeverity.CRITICAL,
        },
        {
            "title": "Review .dockerignore to prevent excluding needed files",
            "explanation": (
                "A .dockerignore pattern may be preventing required files from "
                "reaching the build context. Audit all patterns, especially "
                "wildcards like `*`, `*.py`, or directory names."
            ),
            "severity": RemediationSeverity.HIGH,
            "applies_to": ".dockerignore",
        },
    ],

    FailureType.UNKNOWN_FAILURE: [
        {
            "title": "Enable verbose output in the failing step",
            "explanation": (
                "The failure could not be automatically classified. Add verbose "
                "flags to the failing command to capture more diagnostic detail."
            ),
            "patch": (
                "# Shell debug mode:\n"
                "RUN set -x && your-failing-command\n\n"
                "# pip verbose:\n"
                "RUN pip install --no-cache-dir -v -r requirements.txt\n\n"
                "# npm verbose:\n"
                "RUN npm install --loglevel verbose"
            ),
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Review the full build output for the root error",
            "explanation": (
                "Scroll up in the build log to find the first ERROR or FAILED line. "
                "Docker often reports a cascade of errors — the root cause is usually "
                "the first one."
            ),
            "severity": RemediationSeverity.MEDIUM,
        },
    ],
}


# ── LLM prompt ────────────────────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """\
You are a Docker build failure expert embedded in a DevSecOps platform.
You receive structured failure information and must return enriched remediation.

Return ONLY a valid JSON object — no text before or after:
{
  "root_cause": "<precise 2-3 sentence technical explanation of why THIS build failed>",
  "retry_recommended": <true if a retry without changes might succeed, false otherwise>,
  "fixes": [
    {
      "title": "<short imperative action title>",
      "explanation": "<detailed explanation specific to this error>",
      "patch": "<optional: exact Dockerfile line or shell command>",
      "severity": "<critical|high|medium|low>",
      "applies_to": "<optional: Dockerfile|requirements.txt|.dockerignore|etc>"
    }
  ]
}

Rules:
- root_cause must be specific to the ACTUAL error shown, not a generic template
- fixes should be 2-4 items ordered by likelihood of resolving the issue
- patch is strongly preferred when a concrete change is possible
- Do NOT invent problems not present in the error output
- Do NOT include any markdown, explanation text, or code fences outside the JSON\
"""


# ── Helper functions ──────────────────────────────────────────────────────────

def _build_root_cause(
    classification: FailureClassification,
    extracted: ExtractedError,
) -> str:
    """Build a deterministic root cause description from classified failure."""
    step_ctx = (
        f" during Dockerfile step `{extracted.failed_step}`"
        if extracted.failed_step
        else ""
    )

    if extracted.last_error_line:
        detail = f" Error: {extracted.last_error_line[:200]}"
    elif extracted.error_excerpt:
        first_line = extracted.error_excerpt.split("\n")[0][:200]
        detail = f" Detail: {first_line}"
    else:
        detail = ""

    pkg = extracted.package_manager or "unknown"

    templates = {
        FailureType.DEPENDENCY_FAILURE: (
            f"A required dependency or module could not be imported{step_ctx}.{detail}"
        ),
        FailureType.PERMISSION_FAILURE: (
            f"The build process was denied access to a file or resource{step_ctx}.{detail}"
        ),
        FailureType.MISSING_FILE: (
            f"A file referenced in the Dockerfile or application code does not "
            f"exist in the build context{step_ctx}.{detail}"
        ),
        FailureType.NETWORK_FAILURE: (
            f"Network connectivity failed during package download or external "
            f"resource access{step_ctx}.{detail}"
        ),
        FailureType.SYNTAX_ERROR: (
            f"A syntax error was detected in the application code or "
            f"configuration{step_ctx}.{detail}"
        ),
        FailureType.PACKAGE_MANAGER_FAILURE: (
            f"The package manager ({pkg}) failed to resolve or install "
            f"dependencies{step_ctx}.{detail}"
        ),
        FailureType.BASE_IMAGE_FAILURE: (
            f"The Docker base image specified in the FROM directive could not "
            f"be pulled from the registry{step_ctx}.{detail}"
        ),
        FailureType.ENVIRONMENT_VARIABLE_FAILURE: (
            f"A required environment variable is missing or undefined{step_ctx}.{detail}"
        ),
        FailureType.BUILD_CONTEXT_FAILURE: (
            f"The Docker build context is missing required files or is "
            f"incorrectly configured{step_ctx}.{detail}"
        ),
        FailureType.UNKNOWN_FAILURE: (
            f"The build failed with an unclassified error{step_ctx}.{detail}"
        ),
    }
    return templates.get(
        classification.failure_type,
        f"Build failed ({classification.failure_type.value}){step_ctx}.{detail}",
    )


def _should_retry(classification: FailureClassification) -> bool:
    """
    Determine whether a retry without any code changes is likely to help.

    Transient failures (network, registry flaps) benefit from retries.
    Structural failures (syntax, missing files, permissions) require code changes.
    """
    transient_types = {
        FailureType.NETWORK_FAILURE,
        FailureType.PACKAGE_MANAGER_FAILURE,  # Registry can be temporarily unavailable
        FailureType.BASE_IMAGE_FAILURE,        # Pull can fail transiently
        FailureType.UNKNOWN_FAILURE,           # Give it one shot
    }
    return classification.failure_type in transient_types


def _build_default_fixes(failure_type: FailureType) -> List[RemediationFix]:
    """Build the deterministic fix list for a given failure type."""
    raw = _DEFAULT_FIXES.get(failure_type, _DEFAULT_FIXES[FailureType.UNKNOWN_FAILURE])
    return [RemediationFix(**fix) for fix in raw]


def _parse_llm_fixes(llm_fixes: list) -> List[RemediationFix]:
    """
    Safely parse LLM-returned fix objects into RemediationFix instances.
    Malformed entries are skipped rather than raising.
    """
    result: List[RemediationFix] = []
    for raw in llm_fixes:
        if not isinstance(raw, dict):
            continue
        title = raw.get("title", "").strip()
        explanation = raw.get("explanation", "").strip()
        if not title or not explanation:
            continue
        severity_raw = raw.get("severity", "medium")
        try:
            severity = RemediationSeverity(severity_raw.lower())
        except ValueError:
            severity = RemediationSeverity.MEDIUM
        result.append(RemediationFix(
            title=title,
            explanation=explanation,
            patch=raw.get("patch") or None,
            severity=severity,
            applies_to=raw.get("applies_to") or None,
        ))
    return result


# ── DockerCorrectorAgent ──────────────────────────────────────────────────────

class DockerCorrectorAgent(BaseCorrectorAgent):
    """
    Analyzes Docker build failures and produces structured remediation.

    The agent is deterministic by default. Passing an `llm_service` enables
    optional LLM enrichment that replaces the root_cause description and
    fix list with model-generated content specific to the actual error.

    Invariants:
      - analyze() never raises; errors are caught and returned as results.
      - Deterministic extraction + classification always runs first.
      - LLM enrichment is additive: it can only improve, never break.
    """

    def __init__(self, llm_service: Any = None) -> None:
        super().__init__(agent_name="DockerCorrectorAgent")
        self._llm = llm_service  # LLMService | None

    async def analyze(
        self,
        raw_logs: str,
        artifacts: Optional[dict] = None,
        context: Optional[dict] = None,
    ) -> CorrectorResult:
        task_id = (context or {}).get("task_id")
        self._log_analysis_start(task_id)

        try:
            return await self._run_pipeline(raw_logs, artifacts, context)
        except Exception as exc:
            logger.exception(
                "[Corrector] Unexpected error during analysis for task=%s: %s",
                task_id, exc,
            )
            return CorrectorResult(
                status="error",
                error_type=FailureType.UNKNOWN_FAILURE,
                root_cause=f"Corrector agent encountered an internal error: {exc}",
                confidence=0.0,
                retry_recommended=True,
                fixes=_build_default_fixes(FailureType.UNKNOWN_FAILURE),
                llm_enriched=False,
            )

    async def _run_pipeline(
        self,
        raw_logs: str,
        artifacts: Optional[dict],
        context: Optional[dict],
    ) -> CorrectorResult:
        # ── Step 1: Sanitize ─────────────────────────────────────────────────
        sanitized = sanitize_logs(raw_logs)
        error_section = extract_error_section(raw_logs)
        logger.debug("[Corrector] Sanitized: %d chars → %d chars", len(raw_logs), len(sanitized))

        # ── Step 2: Deterministic extraction ─────────────────────────────────
        extracted = extract_errors(raw_logs)

        # ── Step 3: Deterministic classification ──────────────────────────────
        classification = classify_failure(sanitized, extracted)
        logger.info(
            "[FailureClassifier] Classified as %s confidence=%.2f rule=%s",
            classification.failure_type.value,
            classification.confidence,
            classification.matched_rule,
        )

        # ── Step 4: Build deterministic baseline result ───────────────────────
        root_cause = _build_root_cause(classification, extracted)
        retry_recommended = _should_retry(classification)
        fixes = _build_default_fixes(classification.failure_type)
        llm_enriched = False

        # ── Step 5: Optional LLM enrichment ──────────────────────────────────
        if self._llm is not None:
            try:
                llm_data = await self._call_llm(
                    sanitized=sanitized,
                    error_section=error_section,
                    extracted=extracted,
                    classification=classification,
                    artifacts=artifacts or {},
                )
                if llm_data:
                    llm_root = llm_data.get("root_cause", "").strip()
                    if llm_root:
                        root_cause = llm_root
                        logger.debug("[Corrector] LLM root_cause accepted")

                    llm_retry = llm_data.get("retry_recommended")
                    if isinstance(llm_retry, bool):
                        retry_recommended = llm_retry

                    parsed_fixes = _parse_llm_fixes(llm_data.get("fixes", []))
                    if parsed_fixes:
                        fixes = parsed_fixes
                        llm_enriched = True
                        logger.info(
                            "[Corrector] LLM enrichment applied: %d fixes", len(fixes)
                        )
            except Exception as exc:
                logger.warning(
                    "[Corrector] LLM enrichment failed (deterministic result kept): %s", exc
                )

        result = CorrectorResult(
            status="analyzed",
            error_type=classification.failure_type,
            root_cause=root_cause,
            confidence=classification.confidence,
            failed_step=extracted.failed_step,
            failed_line=extracted.failed_line_number,
            error_excerpt=extracted.error_excerpt,
            retry_recommended=retry_recommended,
            fixes=fixes,
            llm_enriched=llm_enriched,
        )
        self._log_analysis_complete(result)
        return result

    async def _call_llm(
        self,
        sanitized: str,
        error_section: str,
        extracted: ExtractedError,
        classification: FailureClassification,
        artifacts: dict,
    ) -> Optional[dict]:
        """
        Invoke the LLM for enrichment.
        Runs the synchronous LLMService.chat_json() in a thread pool so we
        never block the asyncio event loop.
        """
        dockerfile_lines = (artifacts.get("dockerfile") or "").splitlines()
        dockerfile_snippet = "\n".join(dockerfile_lines[:30])
        if len(dockerfile_lines) > 30:
            dockerfile_snippet += f"\n... ({len(dockerfile_lines) - 30} more lines omitted)"

        user_prompt = (
            f"Docker build failure analysis request:\n\n"
            f"FAILURE TYPE (deterministic): {classification.failure_type.value}\n"
            f"CONFIDENCE: {classification.confidence:.2f}\n"
            f"FAILED STEP: {extracted.failed_step or 'unknown'}\n"
            f"EXIT CODE: {extracted.exit_code or 'unknown'}\n"
            f"PACKAGE MANAGER DETECTED: {extracted.package_manager or 'none'}\n\n"
            f"ERROR EXCERPT (surrounding the last error):\n"
            f"{'─' * 60}\n"
            f"{error_section[:1500]}\n"
            f"{'─' * 60}\n\n"
            f"DOCKERFILE (first 30 lines):\n"
            f"{'─' * 60}\n"
            f"{dockerfile_snippet or '(not available)'}\n"
            f"{'─' * 60}\n\n"
            f"Provide an enriched root cause analysis and specific remediation "
            f"steps that address this exact failure."
        )

        logger.debug("[Corrector] Calling LLM for enrichment (task logs: %d chars)", len(sanitized))

        result = await asyncio.to_thread(
            self._llm.chat_json,
            _LLM_SYSTEM_PROMPT,
            user_prompt,
            0.1,    # Low temperature: we want deterministic, factual output
            1500,
        )
        return result
