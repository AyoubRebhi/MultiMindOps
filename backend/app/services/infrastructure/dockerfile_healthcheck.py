"""
HEALTHCHECK output hardening for generated Dockerfiles.

HEALTHCHECK is the one Docker instruction that is easy to corrupt during string
assembly: it is the only directive a generator routinely emits as a *multi-line*
instruction (``HEALTHCHECK … \\`` + newline + ``CMD …``). When a builder or LLM
serializes that newline as the two literal characters ``\\n`` instead of a real
line break, Docker cannot parse the line and the entire build fails at parse
time with ``unknown instruction: \\nCMD``.

Two deterministic, dependency-free functions guard against that:

  • :func:`normalize_healthcheck` — repairs *raw escape injection*. A literal
    ``\\n`` / ``\\t`` / ``\\r`` (backslash + letter, NOT a real newline) inside a
    HEALTHCHECK line is flattened to a valid single-line HEALTHCHECK. A correctly
    formatted continuation (a bare ``\\`` at end-of-line) is never touched.

  • :func:`validate_healthcheck` — a read-only syntax gate suitable for running
    *before persistence*: it flags literal escape injection, a HEALTHCHECK with
    neither ``CMD`` nor ``NONE``, and unit-less durations (``--interval=30``
    instead of ``--interval=30s``).

Neither function calls the LLM, the network, or Docker.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# A *literal* escape sequence: a backslash (optionally doubled, i.e. "\\n" as it
# appears after a double-escaping bug) immediately followed by n / r / t. A real
# line continuation is a bare backslash at end-of-line and never matches this,
# because after splitlines() there is no character following that backslash.
_LITERAL_ESCAPE_RE = re.compile(r"\\{1,2}[nrt]")
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")
_HEALTHCHECK_PREFIX_RE = re.compile(r"^\s*HEALTHCHECK\b", re.IGNORECASE)

# Flags Docker requires to carry a time unit (s/m/h/ms/…) and the integer flag.
_DURATION_FLAG_RE = re.compile(
    r"--(interval|timeout|start-period|start-interval)=(\S+)", re.IGNORECASE
)
_RETRIES_FLAG_RE = re.compile(r"--retries=(\S+)", re.IGNORECASE)
# Accepts simple ("30s") and compound ("1m30s", "500ms") Go-style durations.
_DURATION_VALUE_RE = re.compile(r"^(?:\d+(?:\.\d+)?(?:ns|us|ms|s|m|h))+$", re.IGNORECASE)


def _is_healthcheck_line(line: str) -> bool:
    return bool(_HEALTHCHECK_PREFIX_RE.match(line))


def normalize_healthcheck(content: str) -> Tuple[str, List[str]]:
    """
    Repair raw escape injection inside HEALTHCHECK instructions.

    Returns ``(repaired_content, repairs)`` where ``repairs`` is a (possibly
    empty) list of human-readable descriptions of each fix applied. When no
    HEALTHCHECK is present, or none is broken, the content is returned unchanged
    with an empty list.

    The repair is conservative: it only rewrites physical lines that *start* with
    ``HEALTHCHECK`` and that actually contain a literal escape sequence, so a
    correctly formatted single- or multi-line HEALTHCHECK is left byte-for-byte
    intact.
    """
    if not content or "HEALTHCHECK" not in content.upper():
        return content, []

    repairs: List[str] = []
    out_lines: List[str] = []
    for line in content.splitlines():
        if _is_healthcheck_line(line) and _LITERAL_ESCAPE_RE.search(line):
            fixed = _LITERAL_ESCAPE_RE.sub(" ", line)
            fixed = _MULTISPACE_RE.sub(" ", fixed).rstrip()
            # ASCII-only message: this string is logged at runtime, and the
            # platform's Windows console encodes stderr as cp1252 (no '->' arrow
            # glyph), so non-ASCII here would raise UnicodeEncodeError on log.
            repairs.append(
                f"replaced literal escape sequence: {line.strip()!r} -> {fixed.strip()!r}"
            )
            out_lines.append(fixed)
        else:
            out_lines.append(line)

    return "\n".join(out_lines), repairs


def validate_healthcheck(content: str) -> List[str]:
    """
    Return a list of HEALTHCHECK syntax problems (empty == valid / absent).

    Detects the failure classes that make ``docker build`` reject the file:
      • a literal ``\\n`` / ``\\t`` / ``\\r`` escape sequence,
      • a HEALTHCHECK with neither a ``CMD`` nor a ``NONE`` clause,
      • a duration flag without a time unit, or a non-integer ``--retries``.
    """
    issues: List[str] = []
    if not content or "HEALTHCHECK" not in content.upper():
        return issues

    for logical in _logical_healthchecks(content):
        if _LITERAL_ESCAPE_RE.search(logical):
            issues.append(
                "HEALTHCHECK contains a literal escape sequence (\\n/\\t/\\r) — "
                "Docker cannot parse it."
            )

        rest = re.sub(r"^\s*HEALTHCHECK\b", "", logical, flags=re.IGNORECASE).strip()
        upper = rest.upper()
        if not upper.startswith("NONE") and "CMD" not in upper:
            issues.append("HEALTHCHECK is missing a CMD (or NONE) clause.")

        for name, value in _DURATION_FLAG_RE.findall(logical):
            if not _DURATION_VALUE_RE.match(value):
                issues.append(
                    f"HEALTHCHECK --{name.lower()} duration {value!r} is missing a "
                    f"time unit (e.g. 30s)."
                )
        retries = _RETRIES_FLAG_RE.findall(logical)
        for value in retries:
            if not value.isdigit():
                issues.append(
                    f"HEALTHCHECK --retries must be a non-negative integer, got {value!r}."
                )

    return issues


def _logical_healthchecks(content: str) -> List[str]:
    """
    Reconstruct each HEALTHCHECK as a single logical instruction.

    Real backslash line-continuations are joined so that a correctly formatted
    multi-line HEALTHCHECK is validated as one instruction. A line broken by a
    *literal* ``\\n`` stays a single physical line (it does not end with a bare
    backslash), so it is returned as-is with the escape still embedded — which is
    exactly what :func:`validate_healthcheck` needs to flag.
    """
    lines = content.splitlines()
    out: List[str] = []
    i = 0
    while i < len(lines):
        if _is_healthcheck_line(lines[i]):
            buf = [lines[i]]
            while buf[-1].rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                buf.append(lines[i])
            joined = " ".join(seg.rstrip().rstrip("\\").strip() for seg in buf)
            out.append(joined.strip())
        i += 1
    return out
