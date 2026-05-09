"""
Log Sanitizer — cleans raw Docker build logs for LLM analysis.

Design: deterministic, regex-based, no LLM calls.
All helpers are independently unit-testable pure functions.

Pipeline:
  1. Strip ANSI escape codes
  2. Remove Docker layer progress / hash lines
  3. Remove consecutive duplicate lines
  4. Context-aware filtering (preserve error context, discard pure noise)
  5. Truncate extremely long lines
  6. Cap total output lines
"""

from __future__ import annotations

import logging
import re
from typing import List

logger = logging.getLogger(__name__)

# ── Compiled patterns ─────────────────────────────────────────────────────────

# ANSI: ESC followed by control sequence
_ANSI_ESCAPE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Docker layer progress: BuildKit-style (#N ...) and legacy layer hashes
_DOCKER_PROGRESS = re.compile(
    r"^(?:"
    r"\s*#\d+\s+(?:DONE|CACHED|sha256:|COPY\s|ADD\s|FROM\s|RUN\s|CMD\s|"
    r"LABEL\s|ENV\s|EXPOSE\s|ARG\s|WORKDIR\s|ENTRYPOINT\s|HEALTHCHECK\s).*"
    r"|\s*=>\s+\[.*?\]\s+.*"
    r"|\s*--->"
    r"|\s*Removing\s+intermediate\s+container\s+[a-f0-9]+"
    r"|\s*Successfully\s+built\s+[a-f0-9]+"
    r"|\s*Successfully\s+tagged\s+"
    r"|\s*\d+:\s+sha256:[a-f0-9]+"
    r"|\s*#\d+\s+\d+\.\d+s\s+done"
    r")",
    re.IGNORECASE,
)

# Download/upload progress bars from apt/pip/npm/curl
_PROGRESS_BAR = re.compile(
    r"(?:"
    r"\[=*\s*>?\s*\]"          # [=====>   ]
    r"|\d+%\s*(?:\||eta|--:--)"  # 73% |===| eta
    r"|^\s*Get:\d+"              # apt: Get:1 http://...
    r"|^\s*Fetching\s+https?://"
    r"|^\s*Downloading\s+https?://"
    r")",
    re.IGNORECASE,
)

# Pure noise lines with no diagnostic value
_NOISE_PATTERNS = [
    re.compile(r"^\s*$"),
    re.compile(r"^[.\s]+$"),
    re.compile(r"^\s*Sending\s+build\s+context\s+to\s+Docker\s+daemon", re.IGNORECASE),
    re.compile(r"^\s*-->\s+[a-f0-9]{8,}"),        # ---> abc123def456
    re.compile(r"^\s*-->\s+Using\s+cache", re.IGNORECASE),
    re.compile(r"^\s*\[internal\]", re.IGNORECASE),
]

# High-signal lines that must be preserved regardless of noise classification
_KEEP_PATTERNS = [
    re.compile(r"\bERROR\b", re.IGNORECASE),
    re.compile(r"\bFAILED\b", re.IGNORECASE),
    re.compile(r"\bfatal\b", re.IGNORECASE),
    re.compile(r"\bexception\b", re.IGNORECASE),
    re.compile(r"\btraceback\b", re.IGNORECASE),
    re.compile(r"\bpermission\s+denied\b", re.IGNORECASE),
    re.compile(r"\bno\s+such\s+file\s+or\s+directory\b", re.IGNORECASE),
    re.compile(r"\bexit(?:ed)?\s+(?:with\s+)?(?:code|status)\b", re.IGNORECASE),
    re.compile(r"\bcould\s+not\s+find\b|\bnot\s+found\b", re.IGNORECASE),
    re.compile(r"\bsyntaxerror\b|\binvalid\s+syntax\b", re.IGNORECASE),
    re.compile(r"\bconnection\s+(?:refused|timed?\s+out|reset)\b", re.IGNORECASE),
    re.compile(r"\bcannot\b|\bunable\s+to\b", re.IGNORECASE),
    re.compile(r"^npm\s+ERR!", re.IGNORECASE),
    re.compile(r"^pip.*error", re.IGNORECASE),
    re.compile(r"^E\s+\w"),         # pytest error lines: "E   ImportError: ..."
    re.compile(r"\bOSError\b|\bIOError\b|\bRuntimeError\b", re.IGNORECASE),
    re.compile(r"returned\s+a\s+non-zero\s+(?:exit\s+)?code", re.IGNORECASE),
    re.compile(r"The\s+command\s+.+\s+returned\s+a\s+non-zero", re.IGNORECASE),
]

_MAX_OUTPUT_LINES = 300
_MAX_LINE_LENGTH = 500
_CONTEXT_LINES = 5   # Lines before/after a high-signal line to keep for context
_HEAD_LINES = 100    # Lines to keep from the start when truncating
_TAIL_LINES = 100    # Lines to keep from the end when truncating


# ── Pure helper functions (unit-testable) ─────────────────────────────────────

def strip_ansi(text: str) -> str:
    """Remove all ANSI terminal escape sequences from text."""
    return _ANSI_ESCAPE.sub("", text)


def is_noise_line(line: str) -> bool:
    """Return True if this line carries no diagnostic value."""
    stripped = line.strip()
    if not stripped:
        return True
    return any(p.search(stripped) for p in _NOISE_PATTERNS)


def is_important_line(line: str) -> bool:
    """Return True if this line is high-signal and must always be preserved."""
    return any(p.search(line) for p in _KEEP_PATTERNS)


def is_docker_progress_line(line: str) -> bool:
    """Return True for Docker build progress / layer hash lines."""
    return bool(_DOCKER_PROGRESS.match(line)) or bool(_PROGRESS_BAR.search(line))


def remove_consecutive_duplicates(lines: List[str]) -> List[str]:
    """Remove consecutive duplicate lines (common in docker pull progress)."""
    if not lines:
        return []
    result: List[str] = [lines[0]]
    for line in lines[1:]:
        if line.strip() != result[-1].strip():
            result.append(line)
    return result


def truncate_line(line: str, max_length: int = _MAX_LINE_LENGTH) -> str:
    """Truncate a line that exceeds max_length characters."""
    if len(line) > max_length:
        return line[:max_length] + " [truncated]"
    return line


def _mark_important_context(lines: List[str], window: int = _CONTEXT_LINES) -> set[int]:
    """Return indices of important lines and their surrounding context window."""
    important: set[int] = set()
    for i, line in enumerate(lines):
        if is_important_line(line):
            start = max(0, i - window)
            end = min(len(lines), i + window + 1)
            important.update(range(start, end))
    return important


# ── Main pipeline ─────────────────────────────────────────────────────────────

def sanitize_logs(raw_logs: str) -> str:
    """
    Full sanitization pipeline for Docker build logs.

    Returns cleaned log text optimized for LLM analysis. The output is
    deterministic: same input always produces the same output.
    """
    if not raw_logs or not raw_logs.strip():
        return ""

    logger.debug("[LogSanitizer] Input: %d chars", len(raw_logs))

    # 1. Strip ANSI escape codes
    text = strip_ansi(raw_logs)

    # 2. Split into lines
    lines = text.splitlines()

    # 3. Remove Docker layer / build progress lines
    lines = [ln for ln in lines if not is_docker_progress_line(ln)]

    # 4. Remove consecutive duplicates
    lines = remove_consecutive_duplicates(lines)

    # 5. Context-aware noise filtering
    keep_indices = _mark_important_context(lines)
    filtered: List[str] = []
    for i, line in enumerate(lines):
        if i in keep_indices or not is_noise_line(line):
            filtered.append(line)

    # 6. Truncate long lines
    filtered = [truncate_line(ln) for ln in filtered]

    # 7. Cap total output — keep head + tail, omit middle
    if len(filtered) > _MAX_OUTPUT_LINES:
        head = filtered[:_HEAD_LINES]
        tail = filtered[-_TAIL_LINES:]
        omitted = len(filtered) - _HEAD_LINES - _TAIL_LINES
        filtered = head + [f"... [{omitted} lines omitted for brevity] ..."] + tail

    result = "\n".join(filtered)
    logger.debug(
        "[LogSanitizer] Output: %d chars, %d lines (reduced from %d input lines)",
        len(result), len(filtered), len(text.splitlines()),
    )
    return result


def extract_error_section(raw_logs: str, window: int = 30) -> str:
    """
    Extract the log section surrounding the last detected error.

    This produces a focused excerpt for the LLM, rather than the full
    sanitized log. Useful when full logs are large.
    """
    lines = strip_ansi(raw_logs).splitlines()

    # Find index of the last high-signal line
    error_idx: int | None = None
    for i in range(len(lines) - 1, -1, -1):
        if is_important_line(lines[i]):
            error_idx = i
            break

    if error_idx is None:
        # No explicit error found — return the last N lines as fallback
        tail = lines[-window:] if lines else []
        return "\n".join(tail)

    start = max(0, error_idx - window // 2)
    end = min(len(lines), error_idx + window // 2 + 1)
    return "\n".join(lines[start:end])
