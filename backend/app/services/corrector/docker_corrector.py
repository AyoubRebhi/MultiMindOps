"""
DockerCorrectorAgent — GPT-5.4-mini reasoning engine for Docker build failures.

Pipeline (deterministic preprocessing → LLM reasoning → structured output):
  1. LogSanitizer          — strip ANSI / noise / duplicates
  2. ErrorExtractor        — regex-based structured extraction
  3. FailureClassifier     — deterministic taxonomy classification
  4. DistroDetector        — detect Alpine vs Debian from Dockerfile
  5. GPT-5.4-mini reasoning — root cause + multi-stage analysis + structured patches
  6. PatchValidator        — ensure every patch is syntactically valid
  7. Return CorrectorResult with Phase 2 extensions

Phase 2 additions vs Phase 1:
  • Structured patches (file + operation + target + replacement)
  • Multi-stage analysis (primary + cascading + future failures)
  • Per-dimension confidence scores
  • Distro context awareness (Alpine vs Debian remediation)
  • Regeneration guidance (anti-patterns + section hints for InfrastructureAgent)
  • GPT-5.4-mini as primary reasoning engine (ProviderFactory with Groq fallback)

Invariants:
  - analyze() never raises; exceptions are caught and returned as error results.
  - Deterministic extraction + classification always runs first.
  - LLM enrichment is additive: if it fails, the deterministic baseline is kept.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from .base_corrector import BaseCorrectorAgent
from .error_extractor import extract_errors
from .failure_classifier import classify_failure
from .log_sanitizer import extract_error_section, sanitize_logs
from .remediation_models import (
    CorrectorResult,
    DistroContext,
    ExtractedError,
    FailureClassification,
    FailureConfidence,
    FailureType,
    MultiStageAnalysis,
    PatchOperation,
    RegenerationGuidance,
    RemediationFix,
    RemediationSeverity,
    SecondaryFailure,
    StructuredPatch,
)

logger = logging.getLogger(__name__)


# ── Deterministic fix library ─────────────────────────────────────────────────

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
            "title": "Install native build tools for packages with C extensions",
            "explanation": (
                "Packages with native extensions need build tools installed first."
            ),
            "patch": (
                "# Debian: RUN apt-get update && apt-get install -y --no-install-recommends "
                "build-essential python3-dev && rm -rf /var/lib/apt/lists/*\n"
                "# Alpine: RUN apk add --no-cache gcc musl-dev python3-dev"
            ),
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.PERMISSION_FAILURE: [
        {
            "title": "Add chmod to make scripts executable",
            "explanation": "Add an explicit `chmod` step before the failing command.",
            "patch": "RUN chmod +x /app/entrypoint.sh",
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Fix ownership with chown",
            "explanation": "Ensure target directory contents are owned by the process user.",
            "patch": "RUN chown -R appuser:appuser /app",
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Install packages as root before switching to non-root user",
            "explanation": "Package managers require root — install before USER directive.",
            "patch": (
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
                "The file referenced in COPY does not exist in the Docker build context. "
                "All paths are relative to where `docker build` is run."
            ),
            "patch": "COPY requirements.txt /app/requirements.txt",
            "severity": RemediationSeverity.CRITICAL,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Review .dockerignore for accidental exclusions",
            "explanation": ".dockerignore may be excluding required files.",
            "severity": RemediationSeverity.HIGH,
            "applies_to": ".dockerignore",
        },
        {
            "title": "Use WORKDIR before relative COPY paths",
            "explanation": "Set WORKDIR before using relative destination paths.",
            "patch": "WORKDIR /app\nCOPY . .",
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.NETWORK_FAILURE: [
        {
            "title": "Retry with explicit package registry URL",
            "explanation": "A network failure occurred during package download.",
            "patch": (
                "# pip:\nRUN pip install --no-cache-dir --index-url https://pypi.org/simple/ -r requirements.txt\n"
                "# npm:\nRUN npm install --registry https://registry.npmjs.org"
            ),
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Use --network=host to bypass Docker NAT",
            "explanation": "DNS may fail inside the Docker build network.",
            "patch": "# docker build --network=host -t myimage .",
            "severity": RemediationSeverity.MEDIUM,
        },
    ],

    FailureType.SYNTAX_ERROR: [
        {
            "title": "Fix syntax error at the indicated line",
            "explanation": "Locate the file and line number in the error output and correct it.",
            "severity": RemediationSeverity.CRITICAL,
        },
        {
            "title": "Lint source files before building",
            "explanation": "Add a linting step early in the Dockerfile.",
            "patch": (
                "# Python:\nRUN python -m py_compile your_module.py\n"
                "# JavaScript:\nRUN npx eslint . --max-warnings 0"
            ),
            "severity": RemediationSeverity.HIGH,
        },
    ],

    FailureType.DISTRO_MISMATCH: [
        {
            "title": "Use correct user creation commands for the image distro",
            "explanation": (
                "Alpine images use 'addgroup'/'adduser -S'; "
                "Debian/Ubuntu images use 'groupadd'/'useradd -r'. "
                "Mixing these causes 'command not found' at build time."
            ),
            "patch": (
                "# Debian (eclipse-temurin:17-jre, python:3.11-slim, node:20-slim):\n"
                "RUN groupadd -r appgroup && useradd -r -g appgroup appuser\n\n"
                "# Alpine (alpine:3.19, node:20-alpine, eclipse-temurin:17-jre-alpine):\n"
                "RUN addgroup -S appgroup && adduser -S appuser -G appgroup"
            ),
            "severity": RemediationSeverity.CRITICAL,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Use correct package manager for the image distro",
            "explanation": "Alpine uses 'apk add'; Debian/Ubuntu uses 'apt-get install'.",
            "patch": (
                "# Debian:\nRUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*\n"
                "# Alpine:\nRUN apk add --no-cache curl"
            ),
            "severity": RemediationSeverity.CRITICAL,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.EXEC_FORM_INVALID: [
        {
            "title": "Fix JSON exec form — use double quotes, not single quotes",
            "explanation": (
                "Docker exec form (ENTRYPOINT/CMD arrays) requires valid JSON. "
                "JSON only allows double quotes — single quotes cause a parse error."
            ),
            "patch": (
                "# WRONG:\nENTRYPOINT ['java', '-jar', 'app.jar']\n\n"
                "# CORRECT:\nENTRYPOINT [\"java\", \"-jar\", \"app.jar\"]"
            ),
            "severity": RemediationSeverity.CRITICAL,
            "applies_to": "Dockerfile",
        },
        {
            "title": "RUN does not support exec form — use shell form",
            "explanation": (
                "RUN always uses shell form. Only CMD and ENTRYPOINT support exec form. "
                "Remove brackets from RUN instructions."
            ),
            "patch": (
                "# WRONG:\nRUN ['mvn', 'clean', 'package']\n\n"
                "# CORRECT:\nRUN mvn clean package -DskipTests -q"
            ),
            "severity": RemediationSeverity.CRITICAL,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.HEALTHCHECK_DEPENDENCY: [
        {
            "title": "Install curl before using it in HEALTHCHECK",
            "explanation": (
                "HEALTHCHECK uses curl but it is not present in the runtime image. "
                "Add a curl installation step before the HEALTHCHECK instruction."
            ),
            "patch": (
                "# Debian-based images:\n"
                "RUN apt-get update && apt-get install -y --no-install-recommends curl "
                "&& rm -rf /var/lib/apt/lists/*\n\n"
                "# Alpine-based images:\n"
                "RUN apk add --no-cache curl"
            ),
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Use wget instead of curl (wget available in Alpine by default)",
            "explanation": "Alpine includes wget but not curl by default.",
            "patch": (
                "HEALTHCHECK --interval=30s --timeout=10s --retries=3 \\\n"
                "  CMD wget -q --spider http://localhost:8080/actuator/health || exit 1"
            ),
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.BASE_IMAGE_FAILURE: [
        {
            "title": "Replace deprecated openjdk images with eclipse-temurin",
            "explanation": (
                "openjdk:*-jre-slim images have been removed from Docker Hub. "
                "Use eclipse-temurin instead — it is the official OpenJDK distribution."
            ),
            "patch": (
                "# WRONG (removed from Docker Hub):\nFROM openjdk:17-jre-slim\n\n"
                "# CORRECT:\nFROM eclipse-temurin:17-jre\n"
                "# or Alpine variant:\nFROM eclipse-temurin:17-jre-alpine"
            ),
            "severity": RemediationSeverity.CRITICAL,
            "applies_to": "Dockerfile",
        },
        {
            "title": "Verify image tag on Docker Hub before using",
            "explanation": "Check hub.docker.com for the exact available tags.",
            "patch": "FROM python:3.11-slim  # verified tag",
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.PACKAGE_MANAGER_FAILURE: [
        {
            "title": "Pin package versions to a known-compatible set",
            "explanation": "Resolution failures are often version conflicts.",
            "patch": (
                "# requirements.txt:\nFlask==3.0.3\nrequests==2.31.0\n"
                "# package.json (exact):\n\"express\": \"4.18.2\""
            ),
            "severity": RemediationSeverity.HIGH,
        },
        {
            "title": "Update the package index before installing",
            "explanation": "The index in the base image may be stale.",
            "patch": (
                "# apt:\nRUN apt-get update && apt-get install -y --no-install-recommends pkg\n"
                "# Alpine:\nRUN apk update && apk add --no-cache pkg"
            ),
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.ENVIRONMENT_VARIABLE_FAILURE: [
        {
            "title": "Declare build-time variables with ARG",
            "explanation": "Build-time vars use ARG; runtime vars use ENV.",
            "patch": "ARG API_KEY\n# docker build --build-arg API_KEY=$MY_KEY .",
            "severity": RemediationSeverity.HIGH,
            "applies_to": "Dockerfile",
        },
    ],

    FailureType.BUILD_CONTEXT_FAILURE: [
        {
            "title": "Run docker build from the project root",
            "explanation": "All COPY paths are relative to the build context directory.",
            "patch": "docker build -t myimage .",
            "severity": RemediationSeverity.CRITICAL,
        },
    ],

    FailureType.UNKNOWN_FAILURE: [
        {
            "title": "Enable verbose output in the failing step",
            "explanation": "Add debug flags to the failing command to capture more detail.",
            "patch": (
                "# Shell debug:\nRUN set -x && your-failing-command\n"
                "# pip verbose:\nRUN pip install --no-cache-dir -v -r requirements.txt"
            ),
            "severity": RemediationSeverity.MEDIUM,
            "applies_to": "Dockerfile",
        },
    ],
}


# ── GPT reasoning prompts ─────────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """\
You are a senior DevOps engineer and Docker expert embedded in an AI DevSecOps platform.
You receive structured Docker build failure data and must return a comprehensive analysis.

Return ONLY a valid JSON object — no text, no markdown, no code fences:

{
  "root_cause": "<precise 2-3 sentence technical explanation of why THIS build failed>",
  "retry_recommended": <true if a retry without changes might succeed>,
  "distro_context": {
    "detected_family": "<alpine|debian|ubi|unknown>",
    "package_manager": "<apt|apk|dnf|unknown>",
    "runtime_image": "<detected runtime image or null>",
    "builder_image": "<detected builder image or null>"
  },
  "failure_confidence": {
    "overall": 0.92,
    "root_cause": 0.95,
    "fix": 0.88,
    "runtime_success": 0.80
  },
  "multi_stage_analysis": {
    "primary_failure": "<one sentence: what caused the build to fail RIGHT NOW>",
    "secondary_failures": [
      {
        "failure_type": "<failure type enum value>",
        "description": "<what would fail next>",
        "severity": "<critical|high|medium|low>",
        "will_surface": "<immediately|at_runtime|under_load|conditionally>"
      }
    ],
    "future_risks": ["<risk 1>", "<risk 2>"],
    "fix_order": ["<step 1>", "<step 2>", "<step 3>"]
  },
  "structured_patches": [
    {
      "file": "Dockerfile",
      "operation": "replace",
      "target": "<exact line from Dockerfile — must match verbatim>",
      "replacement": "<corrected line(s)>",
      "reason": "<one sentence>",
      "section_id": "<blueprint section id or null>",
      "confidence": 0.95
    }
  ],
  "fixes": [
    {
      "title": "<short imperative action>",
      "explanation": "<specific to this error>",
      "patch": "<optional exact Dockerfile fix>",
      "severity": "<critical|high|medium|low>",
      "applies_to": "<Dockerfile|requirements.txt|etc>"
    }
  ],
  "regeneration_guidance": {
    "avoid_patterns": [
      "Do not use Alpine user commands on Debian images",
      "Do not use openjdk:17-jre-slim — it is deprecated"
    ],
    "force_variables": {
      "runtime_image": "eclipse-temurin:17-jre",
      "create_user_command": "groupadd -r appgroup && useradd -r -g appgroup appuser"
    },
    "section_hints": {
      "security_user": "Use Debian groupadd/useradd — runtime image is eclipse-temurin (Debian)",
      "runtime_base": "Use eclipse-temurin:17-jre — openjdk:17-jre-slim is removed"
    }
  }
}

Critical rules:
- root_cause must be specific to the ACTUAL error shown, not a generic template
- structured_patches must have EXACT target lines matching the Dockerfile — no approximations
- fixes should be 2-5 items ordered by priority (most likely fix first)
- failure_confidence scores must reflect actual uncertainty (don't round to 1.0)
- secondary_failures identifies issues that WILL fail even after fixing the primary
- future_risks identifies issues that MAY fail later under certain conditions
- regeneration_guidance.force_variables overrides LLM choices in the next generation
- Do NOT invent problems not evidenced in the logs
- Do NOT include markdown or explanation text outside the JSON\
"""


def _build_llm_user_prompt(
    sanitized: str,
    error_section: str,
    extracted: ExtractedError,
    classification: FailureClassification,
    artifacts: dict,
    blueprint_used: Optional[str],
    previous_retries: int,
    validator_output: Optional[dict],
) -> str:
    dockerfile_lines = (artifacts.get("dockerfile") or "").splitlines()
    dockerfile_snippet = "\n".join(dockerfile_lines[:50])
    if len(dockerfile_lines) > 50:
        dockerfile_snippet += f"\n... ({len(dockerfile_lines) - 50} more lines omitted)"

    validator_section = ""
    if validator_output:
        errs = validator_output.get("errors") or []
        warns = validator_output.get("warnings") or []
        if errs or warns:
            validator_section = (
                f"\nSTATIC VALIDATOR OUTPUT:\n"
                + "\n".join(f"  ERROR: {e.get('message','')}" for e in errs[:5])
                + "\n".join(f"  WARN:  {w.get('message','')}" for w in warns[:5])
                + "\n"
            )

    blueprint_section = (
        f"\nBLUEPRINT USED: {blueprint_used}" if blueprint_used else ""
    )
    retry_section = (
        f"\nPREVIOUS RETRY COUNT: {previous_retries} (this is attempt #{previous_retries + 1})"
        if previous_retries > 0
        else ""
    )

    return (
        f"Docker build failure analysis request:\n\n"
        f"FAILURE TYPE (deterministic): {classification.failure_type.value}\n"
        f"CLASSIFICATION CONFIDENCE: {classification.confidence:.2f}\n"
        f"FAILED STEP: {extracted.failed_step or 'unknown'}\n"
        f"EXIT CODE: {extracted.exit_code or 'unknown'}\n"
        f"PACKAGE MANAGER DETECTED: {extracted.package_manager or 'none'}\n"
        f"{blueprint_section}"
        f"{retry_section}"
        f"{validator_section}"
        f"\nERROR EXCERPT:\n"
        f"{'─' * 60}\n"
        f"{error_section[:2000]}\n"
        f"{'─' * 60}\n\n"
        f"DOCKERFILE:\n"
        f"{'─' * 60}\n"
        f"{dockerfile_snippet or '(not available)'}\n"
        f"{'─' * 60}\n\n"
        f"Return the complete JSON analysis schema. Be precise and specific to this exact failure."
    )


# ── Distro detection from Dockerfile ─────────────────────────────────────────

_FROM_RE = re.compile(r"(?im)^FROM\s+(\S+?)(?:\s+AS\s+\S+)?$")


def _detect_distro(dockerfile: str) -> DistroContext:
    """Parse FROM statements to detect builder and runtime distro."""
    from_images = _FROM_RE.findall(dockerfile)
    builder = from_images[0] if from_images else None
    runtime = from_images[-1] if from_images else None

    def _family(img: Optional[str]) -> str:
        if not img:
            return "unknown"
        img_l = img.lower()
        if "alpine" in img_l:
            return "alpine"
        if any(x in img_l for x in ("slim", "bookworm", "bullseye", "buster", "ubuntu", "debian")):
            return "debian"
        if any(x in img_l for x in ("temurin", "eclipse")):
            # eclipse-temurin without alpine suffix → debian
            return "alpine" if "alpine" in img_l else "debian"
        if "python" in img_l:
            return "alpine" if "alpine" in img_l else "debian"
        return "unknown"

    fam = _family(runtime)
    pkg_mgr = "apk" if fam == "alpine" else ("apt" if fam == "debian" else "unknown")

    return DistroContext(
        detected_family=fam,
        package_manager=pkg_mgr,
        runtime_image=runtime,
        builder_image=builder,
    )


# ── Helper parsers ────────────────────────────────────────────────────────────

def _build_root_cause(
    classification: FailureClassification,
    extracted: ExtractedError,
) -> str:
    step_ctx = f" during step `{extracted.failed_step}`" if extracted.failed_step else ""
    detail = ""
    if extracted.last_error_line:
        detail = f" Error: {extracted.last_error_line[:200]}"
    elif extracted.error_excerpt:
        detail = f" Detail: {extracted.error_excerpt.split(chr(10))[0][:200]}"

    templates = {
        FailureType.DISTRO_MISMATCH: (
            f"Distro command mismatch{step_ctx}: Alpine-specific commands used on a Debian image "
            f"(or vice-versa).{detail}"
        ),
        FailureType.EXEC_FORM_INVALID: (
            f"Invalid Docker exec form{step_ctx}: single quotes used in CMD/ENTRYPOINT array — "
            f"Docker requires valid JSON with double quotes.{detail}"
        ),
        FailureType.HEALTHCHECK_DEPENDENCY: (
            f"HEALTHCHECK dependency missing{step_ctx}: curl or wget used in health probe "
            f"but not installed in the runtime image.{detail}"
        ),
        FailureType.BASE_IMAGE_FAILURE: (
            f"Base image unavailable{step_ctx}: the FROM directive references a deprecated "
            f"or non-existent image tag.{detail}"
        ),
        FailureType.DEPENDENCY_FAILURE: (
            f"Required dependency missing{step_ctx}.{detail}"
        ),
        FailureType.PERMISSION_FAILURE: (
            f"File permission denied{step_ctx}.{detail}"
        ),
        FailureType.MISSING_FILE: (
            f"File not found in build context{step_ctx}.{detail}"
        ),
        FailureType.NETWORK_FAILURE: (
            f"Network failure during package download{step_ctx}.{detail}"
        ),
        FailureType.SYNTAX_ERROR: (
            f"Syntax error in application code or configuration{step_ctx}.{detail}"
        ),
        FailureType.PACKAGE_MANAGER_FAILURE: (
            f"Package manager failed to resolve dependencies{step_ctx}.{detail}"
        ),
        FailureType.ENVIRONMENT_VARIABLE_FAILURE: (
            f"Required environment variable missing or undefined{step_ctx}.{detail}"
        ),
        FailureType.BUILD_CONTEXT_FAILURE: (
            f"Docker build context missing required files{step_ctx}.{detail}"
        ),
        FailureType.UNKNOWN_FAILURE: (
            f"Build failed with unclassified error{step_ctx}.{detail}"
        ),
    }
    return templates.get(
        classification.failure_type,
        f"Build failed ({classification.failure_type.value}){step_ctx}.{detail}",
    )


def _should_retry(classification: FailureClassification) -> bool:
    transient = {
        FailureType.NETWORK_FAILURE,
        FailureType.PACKAGE_MANAGER_FAILURE,
        FailureType.BASE_IMAGE_FAILURE,
        FailureType.UNKNOWN_FAILURE,
    }
    return classification.failure_type in transient


def _build_default_fixes(failure_type: FailureType) -> List[RemediationFix]:
    raw = _DEFAULT_FIXES.get(failure_type, _DEFAULT_FIXES[FailureType.UNKNOWN_FAILURE])
    return [RemediationFix(**fix) for fix in raw]


def _parse_fixes(llm_fixes: list) -> List[RemediationFix]:
    result: List[RemediationFix] = []
    for raw in llm_fixes:
        if not isinstance(raw, dict):
            continue
        title = (raw.get("title") or "").strip()
        explanation = (raw.get("explanation") or "").strip()
        if not title or not explanation:
            continue
        try:
            severity = RemediationSeverity((raw.get("severity") or "medium").lower())
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


def _parse_structured_patches(raw_patches: list) -> List[StructuredPatch]:
    result: List[StructuredPatch] = []
    for raw in raw_patches:
        if not isinstance(raw, dict):
            continue
        target = (raw.get("target") or "").strip()
        replacement = (raw.get("replacement") or "").strip()
        reason = (raw.get("reason") or "").strip()
        if not target or not reason:
            continue
        try:
            op = PatchOperation((raw.get("operation") or "replace").lower())
        except ValueError:
            op = PatchOperation.REPLACE
        confidence = float(raw.get("confidence") or 0.85)
        result.append(StructuredPatch(
            file=raw.get("file") or "Dockerfile",
            operation=op,
            target=target,
            replacement=replacement,
            reason=reason,
            section_id=raw.get("section_id") or None,
            confidence=min(1.0, max(0.0, confidence)),
        ))
    return result


def _parse_multi_stage(raw: dict) -> Optional[MultiStageAnalysis]:
    if not isinstance(raw, dict):
        return None
    primary = (raw.get("primary_failure") or "").strip()
    if not primary:
        return None

    secondary: List[SecondaryFailure] = []
    for s in (raw.get("secondary_failures") or []):
        if not isinstance(s, dict):
            continue
        desc = (s.get("description") or "").strip()
        if not desc:
            continue
        try:
            ftype = FailureType(s.get("failure_type") or "unknown_failure")
        except ValueError:
            ftype = FailureType.UNKNOWN_FAILURE
        try:
            sev = RemediationSeverity((s.get("severity") or "medium").lower())
        except ValueError:
            sev = RemediationSeverity.MEDIUM
        secondary.append(SecondaryFailure(
            failure_type=ftype,
            description=desc,
            severity=sev,
            will_surface=s.get("will_surface") or "immediately",
        ))

    return MultiStageAnalysis(
        primary_failure=primary,
        secondary_failures=secondary,
        future_risks=[str(r) for r in (raw.get("future_risks") or [])],
        fix_order=[str(s) for s in (raw.get("fix_order") or [])],
    )


def _parse_regen_guidance(raw: dict) -> Optional[RegenerationGuidance]:
    if not isinstance(raw, dict):
        return None
    avoid = [str(p) for p in (raw.get("avoid_patterns") or [])]
    force = {str(k): str(v) for k, v in (raw.get("force_variables") or {}).items()}
    hints = {str(k): str(v) for k, v in (raw.get("section_hints") or {}).items()}
    if not avoid and not force and not hints:
        return None
    return RegenerationGuidance(
        avoid_patterns=avoid,
        force_variables=force,
        section_hints=hints,
    )


def _parse_failure_confidence(raw: dict) -> Optional[FailureConfidence]:
    if not isinstance(raw, dict):
        return None
    try:
        return FailureConfidence(
            overall=float(raw.get("overall") or 0.7),
            root_cause=float(raw.get("root_cause") or 0.7),
            fix=float(raw.get("fix") or 0.7),
            runtime_success=float(raw.get("runtime_success") or 0.6),
        )
    except Exception:
        return None


def _parse_distro_context(raw: dict) -> Optional[DistroContext]:
    if not isinstance(raw, dict):
        return None
    try:
        return DistroContext(
            detected_family=raw.get("detected_family") or None,
            package_manager=raw.get("package_manager") or None,
            runtime_image=raw.get("runtime_image") or None,
            builder_image=raw.get("builder_image") or None,
        )
    except Exception:
        return None


def _validate_patches(
    patches: List[StructuredPatch],
    dockerfile: str,
) -> List[StructuredPatch]:
    """
    Pre-review validation: remove patches whose target line cannot be found
    in the Dockerfile (prevents phantom patches from reaching human review).
    """
    if not dockerfile:
        return patches
    lines = [ln.strip() for ln in dockerfile.splitlines()]
    valid: List[StructuredPatch] = []
    for patch in patches:
        target_stripped = patch.target.strip()
        if any(target_stripped == ln for ln in lines):
            valid.append(patch)
        else:
            logger.debug(
                "[Corrector] Dropping patch — target not found in Dockerfile: %s",
                target_stripped[:60],
            )
    return valid


# ── DockerCorrectorAgent ──────────────────────────────────────────────────────

class DockerCorrectorAgent(BaseCorrectorAgent):
    """
    Analyzes Docker build failures using GPT-5.4-mini as primary reasoning engine.

    Phase 2 architecture:
      Deterministic preprocessing → GPT reasoning → Structured patches → Validation

    The agent never raises. analyze() always returns a CorrectorResult.
    """

    def __init__(self, llm_service: Any = None) -> None:
        super().__init__(agent_name="DockerCorrectorAgent")
        self._llm = llm_service

    async def analyze(
        self,
        raw_logs: str,
        artifacts: Optional[dict] = None,
        context: Optional[dict] = None,
    ) -> CorrectorResult:
        task_id = (context or {}).get("task_id")
        self._log_analysis_start(task_id)

        try:
            return await self._run_pipeline(raw_logs, artifacts or {}, context or {})
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
        artifacts: dict,
        context: dict,
    ) -> CorrectorResult:
        dockerfile = artifacts.get("dockerfile") or ""
        blueprint_used = context.get("blueprint_used")
        previous_retries = int(context.get("retry_count") or 0)
        validator_output = context.get("validator_output")

        # ── Step 1: Sanitize ─────────────────────────────────────────────────
        sanitized = sanitize_logs(raw_logs)
        error_section = extract_error_section(raw_logs)

        # ── Step 2: Deterministic extraction ─────────────────────────────────
        extracted = extract_errors(raw_logs)

        # ── Step 3: Deterministic classification ──────────────────────────────
        classification = classify_failure(sanitized, extracted)
        logger.info(
            "[Corrector] Classified: type=%s confidence=%.2f rule=%s",
            classification.failure_type.value,
            classification.confidence,
            classification.matched_rule,
        )

        # ── Step 4: Distro detection from Dockerfile ──────────────────────────
        distro_ctx = _detect_distro(dockerfile)

        # ── Step 5: Build deterministic baseline ──────────────────────────────
        root_cause = _build_root_cause(classification, extracted)
        retry_recommended = _should_retry(classification)
        fixes = _build_default_fixes(classification.failure_type)
        llm_enriched = False
        structured_patches: List[StructuredPatch] = []
        failure_confidence: Optional[FailureConfidence] = None
        multi_stage: Optional[MultiStageAnalysis] = None
        regen_guidance: Optional[RegenerationGuidance] = None

        # ── Step 6: GPT-5.4-mini reasoning ───────────────────────────────────
        if self._llm is not None:
            try:
                user_prompt = _build_llm_user_prompt(
                    sanitized=sanitized,
                    error_section=error_section,
                    extracted=extracted,
                    classification=classification,
                    artifacts=artifacts,
                    blueprint_used=blueprint_used,
                    previous_retries=previous_retries,
                    validator_output=validator_output,
                )

                llm_data = await asyncio.to_thread(
                    self._llm.chat_json,
                    _LLM_SYSTEM_PROMPT,
                    user_prompt,
                    0.05,   # Near-zero temperature: deterministic forensic analysis
                    2500,
                )

                if isinstance(llm_data, dict):
                    # Root cause
                    llm_root = (llm_data.get("root_cause") or "").strip()
                    if llm_root:
                        root_cause = llm_root

                    # Retry flag
                    llm_retry = llm_data.get("retry_recommended")
                    if isinstance(llm_retry, bool):
                        retry_recommended = llm_retry

                    # Fixes
                    parsed_fixes = _parse_fixes(llm_data.get("fixes") or [])
                    if parsed_fixes:
                        fixes = parsed_fixes
                        llm_enriched = True

                    # Structured patches (pre-validated against Dockerfile)
                    raw_patches = _parse_structured_patches(
                        llm_data.get("structured_patches") or []
                    )
                    structured_patches = _validate_patches(raw_patches, dockerfile)

                    # Confidence scores
                    failure_confidence = _parse_failure_confidence(
                        llm_data.get("failure_confidence") or {}
                    )

                    # Multi-stage analysis
                    multi_stage = _parse_multi_stage(
                        llm_data.get("multi_stage_analysis") or {}
                    )

                    # Distro context (LLM may refine our detection)
                    llm_distro = _parse_distro_context(
                        llm_data.get("distro_context") or {}
                    )
                    if llm_distro and llm_distro.detected_family not in (None, "unknown"):
                        distro_ctx = llm_distro

                    # Regeneration guidance
                    regen_guidance = _parse_regen_guidance(
                        llm_data.get("regeneration_guidance") or {}
                    )

                    logger.info(
                        "[Corrector] LLM enrichment: fixes=%d patches=%d "
                        "multi_stage=%s regen_guidance=%s",
                        len(fixes),
                        len(structured_patches),
                        multi_stage is not None,
                        regen_guidance is not None,
                    )

            except Exception as exc:
                logger.warning(
                    "[Corrector] LLM reasoning failed (deterministic baseline kept): %s", exc
                )

        # ── Step 7: Build overall confidence ──────────────────────────────────
        overall_confidence = classification.confidence
        if failure_confidence is None:
            failure_confidence = FailureConfidence(
                overall=overall_confidence,
                root_cause=overall_confidence,
                fix=max(0.0, overall_confidence - 0.1),
                runtime_success=max(0.0, overall_confidence - 0.2),
            )

        result = CorrectorResult(
            status="analyzed",
            error_type=classification.failure_type,
            root_cause=root_cause,
            confidence=overall_confidence,
            failed_step=extracted.failed_step,
            failed_line=extracted.failed_line_number,
            error_excerpt=extracted.error_excerpt,
            retry_recommended=retry_recommended,
            fixes=fixes,
            llm_enriched=llm_enriched,
            # Phase 2 extensions
            structured_patches=structured_patches,
            failure_confidence=failure_confidence,
            multi_stage_analysis=multi_stage,
            distro_context=distro_ctx,
            regeneration_guidance=regen_guidance,
        )
        self._log_analysis_complete(result)
        return result
