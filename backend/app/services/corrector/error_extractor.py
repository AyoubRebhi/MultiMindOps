"""
Error Extractor — deterministic, regex-based extraction of failure information
from Docker build logs.

Design principle: regex + heuristics only. No LLM dependency.
All extraction functions are pure and unit-testable in isolation.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Optional

from .log_sanitizer import strip_ansi
from .remediation_models import ExtractedError

logger = logging.getLogger(__name__)

# ── Pattern library ───────────────────────────────────────────────────────────

# Dockerfile step (legacy format: "Step N/M : CMD" or "#N CMD")
_STEP_PATTERN = re.compile(
    r"(?:^Step\s+\d+(?:/\d+)?\s*:\s*|^#\d+\s+)(.+)",
    re.IGNORECASE,
)

# "The command 'X' returned a non-zero code: N"
_DOCKERFILE_STEP_FAILED = re.compile(
    r"The\s+command\s+'(.+?)'\s+returned\s+a\s+non-zero\s+code",
    re.IGNORECASE,
)

# Exit code extraction
_EXIT_CODE_PATTERNS = [
    re.compile(r"exit(?:ed)?\s+(?:with\s+)?(?:code\s+|status\s+)?(\d+)", re.IGNORECASE),
    re.compile(r"returned\s+(?:a\s+)?non-?zero\s+exit\s+(?:code\s+)?(\d+)", re.IGNORECASE),
    re.compile(r"The\s+command\s+.+returned\s+a\s+non-zero\s+code:\s*(\d+)", re.IGNORECASE),
    re.compile(r"Process\s+exited\s+with\s+status\s+(\d+)", re.IGNORECASE),
    re.compile(r"exit\s+status\s+(\d+)", re.IGNORECASE),
]

# Python traceback
_PYTHON_TRACEBACK = re.compile(
    r"(Traceback\s*\(most\s+recent\s+call\s+last\):.+?)(?=\n\n|\Z)",
    re.DOTALL | re.IGNORECASE,
)

# npm error lines
_NPM_ERROR = re.compile(
    r"^npm\s+(?:ERR!)\s+(.+)$",
    re.IGNORECASE | re.MULTILINE,
)

# High-signal error line prefixes (ordered by specificity)
_ERROR_LINE_PATTERNS = [
    re.compile(r"^(?:ERROR|FATAL|CRITICAL|FAILED)\b[\s:]+", re.IGNORECASE),
    re.compile(r"^npm\s+ERR!", re.IGNORECASE),
    re.compile(r"^pip.*[Ee]rror:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^E\s+(?:ImportError|ModuleNotFoundError|FileNotFoundError|"
               r"PermissionError|OSError|RuntimeError|TypeError|ValueError)"),
    re.compile(r"\berror\[E\d+\]", re.IGNORECASE),       # Rust errors: error[E0412]
    re.compile(r"\bEXCEPTION\b", re.IGNORECASE),
    re.compile(r"\bfatal:\s", re.IGNORECASE),
    re.compile(r"returned\s+a\s+non-zero", re.IGNORECASE),
]

# Package manager detection — ordered by specificity
_PKG_MANAGER_PATTERNS: Dict[str, re.Pattern] = {
    "npm":      re.compile(r"npm\s+(?:ERR!|install|ci\b|WARN)", re.IGNORECASE),
    "yarn":     re.compile(r"yarn\s+(?:install|add|ERR|error)", re.IGNORECASE),
    "pip":      re.compile(r"pip(?:3)?\s+install|Could\s+not\s+find\s+a\s+version\s+that\s+satisfies", re.IGNORECASE),
    "apt":      re.compile(r"apt-get\s+install|apt\s+install|dpkg\b", re.IGNORECASE),
    "composer": re.compile(r"composer\s+(?:install|require|update)", re.IGNORECASE),
    "cargo":    re.compile(r"cargo\s+(?:build|install|fetch)", re.IGNORECASE),
    "go":       re.compile(r"go\s+(?:build|get|mod\s+download|install)", re.IGNORECASE),
    "maven":    re.compile(r"mvn\b|maven", re.IGNORECASE),
    "gradle":   re.compile(r"gradle\s+build|\.\/gradlew", re.IGNORECASE),
    "apk":      re.compile(r"apk\s+add", re.IGNORECASE),
}

# Line number references in error output
_LINE_NUMBER = re.compile(
    r"(?:at\s+line\s+|line\s+|:)(\d{1,5})(?::|\s|,|$)",
    re.IGNORECASE,
)


# ── Pure extraction functions ─────────────────────────────────────────────────

def _find_last_error_line(lines: list[str]) -> Optional[str]:
    """Scan lines in reverse; return the last line matching an error pattern."""
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        for pat in _ERROR_LINE_PATTERNS:
            if pat.search(line):
                return stripped
    return None


def _find_failed_step(lines: list[str]) -> Optional[str]:
    """
    Find the last Dockerfile step that was executing before the failure.

    Prefers the explicit "The command 'X' returned non-zero" form because it is
    unambiguous. Falls back to the last Step/# marker seen in the output.
    """
    last_step: Optional[str] = None
    for line in lines:
        m = _STEP_PATTERN.match(line.strip())
        if m:
            last_step = m.group(1).strip()

        m2 = _DOCKERFILE_STEP_FAILED.search(line)
        if m2:
            return m2.group(1).strip()

    return last_step


def _find_exit_code(text: str) -> Optional[int]:
    """Extract the first meaningful non-zero exit code from the log text."""
    for pat in _EXIT_CODE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                code = int(m.group(1))
                if code != 0:
                    return code
            except (ValueError, IndexError):
                continue
    return None


def _find_stack_trace(text: str) -> Optional[str]:
    """Extract Python traceback block if present; limit to 20 lines."""
    m = _PYTHON_TRACEBACK.search(text)
    if not m:
        return None
    lines = m.group(0).strip().splitlines()
    return "\n".join(lines[:20])


def _find_error_excerpt(lines: list[str], window: int = 10) -> Optional[str]:
    """
    Return lines surrounding the last error line for quick human review.
    Falls back to the last <window> lines if no explicit error is found.
    """
    last_err_idx: Optional[int] = None
    for i, line in enumerate(lines):
        for pat in _ERROR_LINE_PATTERNS:
            if pat.search(line):
                last_err_idx = i
                break

    if last_err_idx is None:
        return "\n".join(lines[-window:]) if lines else None

    start = max(0, last_err_idx - window // 2)
    end = min(len(lines), last_err_idx + window // 2 + 1)
    return "\n".join(lines[start:end])


def _detect_package_manager(text: str) -> Optional[str]:
    """Return the name of the package manager active during the failure."""
    for name, pat in _PKG_MANAGER_PATTERNS.items():
        if pat.search(text):
            return name
    return None


def _find_failed_line_number(lines: list[str]) -> Optional[int]:
    """
    Attempt to find a source line number referenced in error output.
    Scans from the bottom (most recent error) upwards.
    """
    for line in reversed(lines):
        m = _LINE_NUMBER.search(line)
        if m:
            try:
                candidate = int(m.group(1))
                # Sanity check: line numbers > 0 and < 50000 are plausible
                if 1 <= candidate < 50_000:
                    return candidate
            except ValueError:
                continue
    return None


def _build_stderr_summary(text: str) -> Optional[str]:
    """
    Build a compact summary from npm ERR! lines if present.
    Returns None if no npm errors are detected.
    """
    npm_errors = _NPM_ERROR.findall(text)
    if not npm_errors:
        return None
    unique = list(dict.fromkeys(npm_errors))[:5]  # Deduplicate, keep first 5
    return "npm errors: " + "; ".join(unique)


# ── Public API ────────────────────────────────────────────────────────────────

def extract_errors(raw_logs: str) -> ExtractedError:
    """
    Deterministically extract structured error information from raw Docker
    build logs.

    Args:
        raw_logs: Raw output from `docker build` (combined stdout + stderr).

    Returns:
        ExtractedError with all detectable fields populated. Never raises.
    """
    if not raw_logs:
        logger.debug("[ErrorExtractor] Empty input — returning empty ExtractedError")
        return ExtractedError()

    logger.debug("[ErrorExtractor] Processing %d chars", len(raw_logs))

    clean_text = strip_ansi(raw_logs)
    lines = clean_text.splitlines()

    last_error = _find_last_error_line(lines)
    failed_step = _find_failed_step(lines)
    exit_code = _find_exit_code(clean_text)
    stack_trace = _find_stack_trace(clean_text)
    error_excerpt = _find_error_excerpt(lines)
    package_manager = _detect_package_manager(clean_text)
    failed_line_number = _find_failed_line_number(lines)
    stderr_summary = _build_stderr_summary(clean_text)

    result = ExtractedError(
        last_error_line=last_error,
        failed_step=failed_step,
        failed_line_number=failed_line_number,
        exit_code=exit_code,
        error_excerpt=error_excerpt,
        stack_trace=stack_trace,
        stderr_summary=stderr_summary,
        package_manager=package_manager,
    )

    logger.info(
        "[ErrorExtractor] Extraction complete: "
        "error_line=%s failed_step=%s exit_code=%s pkg_manager=%s stack_trace=%s",
        bool(last_error),
        bool(failed_step),
        exit_code,
        package_manager,
        bool(stack_trace),
    )
    return result
