"""
DockerBuildStaticValidator — pre-build COPY source validation.

Runs BEFORE `docker build` to catch path mismatches that would cause:
  ERROR: file not found in build context or excluded by .dockerignore

Design:
  - Validates every COPY instruction source against known_files (repository file list)
  - Accounts for the build context (files must be reachable INSIDE it)
  - Suggests the correct COPY path when a misplaced file is detected
  - Never raises; all errors returned as structured ValidationIssue list

Usage:
  validator = DockerBuildStaticValidator()
  result = validator.validate(dockerfile, build_context=".", known_files=[...])
  if not result.valid:
      for issue in result.issues:
          print(issue.message, "→ fix:", issue.suggested_fix)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Paths generated or gitignored — cannot appear in known_files but are valid
_VIRTUAL_SOURCES = frozenset({
    ".", "./", "/",
    "dist", "build", "target", "__pycache__",
    "node_modules", ".gradle", ".m2",
    ".pytest_cache", ".mypy_cache",
    ".env", ".env.local", ".env.production", ".env.development",
})


@dataclass
class ValidationIssue:
    """A single COPY-path validation issue with actionable fix suggestion."""
    copy_instruction: str            # The full COPY line with the problem
    source_path: str                 # The source that could not be resolved
    build_context: str               # The build context used
    message: str                     # Human-readable diagnosis
    suggested_fix: Optional[str] = None     # Corrected COPY instruction (if computable)
    actual_repo_path: Optional[str] = None  # Where the file actually lives in the repo
    rule: str = "copy_path_mismatch"        # Validation rule identifier
    severity: str = "high"                  # "critical" | "high" | "medium" | "low"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "copy_instruction": self.copy_instruction,
            "source_path": self.source_path,
            "build_context": self.build_context,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
            "actual_repo_path": self.actual_repo_path,
            "rule": self.rule,
            "severity": self.severity,
        }


@dataclass
class StaticValidationResult:
    valid: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    resolved_copies: List[Dict[str, Any]] = field(default_factory=list)   # successful resolutions

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "issue_count": len(self.issues),
            "issues": [i.to_dict() for i in self.issues],
            "warnings": self.warnings,
            "resolved_copies": self.resolved_copies,
        }


class DockerBuildStaticValidator:
    """
    Pre-build static validator: checks every COPY source against the known repository
    file list, accounting for the build context.

    Validation rules:
      VALID:   context="."  COPY backend/app/requirements.txt ./requirements.txt
                            (file exists in repo at backend/app/requirements.txt)
      INVALID: context="."  COPY requirements.txt .
                            (file does NOT exist at repo root — lives in backend/app/)

    When a source is invalid but the file exists elsewhere in the repo, a suggested
    fix is computed (the correct COPY instruction).
    """

    def validate(
        self,
        dockerfile_content: str,
        build_context: str,
        known_files: Optional[List[str]] = None,
        framework: Optional[str] = None,
    ) -> StaticValidationResult:
        """
        Validate all COPY instructions in the Dockerfile against the build context.

        Args:
            dockerfile_content: Raw Dockerfile text.
            build_context:      Build context root relative to repo root (e.g. "." or "backend/app").
            known_files:        Repo-relative file paths from codebase analysis.
                                Without this, COPY-path validation is skipped — but
                                runtime-permission validation still runs.
            framework:          Optional framework hint (e.g. "fastapi", "flask") used
                                to tune the runtime-writable-directory warning.

        Returns:
            StaticValidationResult with issues and suggested fixes.
        """
        result = StaticValidationResult()

        # Runtime-permission validation runs regardless of known_files — it is
        # purely a Dockerfile-content check and catches the production bug class
        # where non-root containers cannot mkdir/write at runtime.
        self._validate_runtime_permissions(dockerfile_content, framework, result)

        if not known_files:
            result.warnings.append(
                "known_files not provided — COPY path validation skipped (metadata mode only)"
            )
            return result

        # Normalize build context
        ctx = build_context.strip().strip("/").lstrip("./") if build_context.strip() not in (".", "") else ""
        ctx_prefix = (ctx + "/") if ctx else ""

        # Build a fast lookup: normalized repo-relative path → original
        repo_index: Dict[str, str] = {}
        for f in known_files:
            norm = f.lstrip("./")
            repo_index[norm.lower()] = norm

        copy_instructions = self._extract_copies(dockerfile_content)

        for full_line, sources, target in copy_instructions:
            for src in sources:
                if self._is_skippable(src):
                    result.resolved_copies.append({
                        "instruction": full_line,
                        "source": src,
                        "status": "skipped (glob/virtual/all-copy)",
                    })
                    continue

                src_norm = src.lstrip("./")

                # Path as given: must exist under the build context
                # i.e., the full path in the repo is: ctx_prefix + src_norm
                expected_repo_path = (ctx_prefix + src_norm).lower()

                if expected_repo_path in repo_index:
                    # Valid
                    result.resolved_copies.append({
                        "instruction": full_line,
                        "source": src,
                        "resolved_repo_path": repo_index[expected_repo_path],
                        "status": "valid",
                    })
                    continue

                # Source is not valid — find where the file actually lives
                actual, suggested = self._find_actual_path(src_norm, ctx_prefix, repo_index)

                issue = ValidationIssue(
                    copy_instruction=full_line,
                    source_path=src,
                    build_context=build_context,
                    message=self._build_message(src, build_context, actual),
                    suggested_fix=suggested,
                    actual_repo_path=actual,
                )
                result.issues.append(issue)
                result.valid = False

                logger.warning(
                    "[StaticValidator] COPY mismatch: src=%r context=%r "
                    "actual_path=%r fix=%r",
                    src, build_context, actual, suggested,
                )

        logger.info(
            "[StaticValidator] done — copies=%d invalid=%d warnings=%d",
            len(copy_instructions),
            len(result.issues),
            len(result.warnings),
        )
        return result

    # ── COPY extraction ───────────────────────────────────────────────────────

    def _extract_copies(
        self, dockerfile: str
    ) -> List[tuple]:
        """Return (full_line, [sources], target) for every non-multistage COPY."""
        results = []
        for line in dockerfile.splitlines():
            stripped = line.strip()
            if not stripped.upper().startswith("COPY"):
                continue
            if re.search(r"COPY\s+--from=", stripped, re.IGNORECASE):
                continue  # multi-stage copy — not a context source
            clean = re.sub(r"--\w+(?:=\S+)?\s*", "", stripped, flags=re.IGNORECASE)
            parts = clean.split()[1:]
            if len(parts) < 2:
                continue
            target = parts[-1]
            sources = parts[:-1]
            results.append((stripped, sources, target))
        return results

    # ── Path resolution ───────────────────────────────────────────────────────

    def _find_actual_path(
        self,
        src_norm: str,
        ctx_prefix: str,
        repo_index: Dict[str, str],
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Try to find where the source file actually lives in the repository.

        Returns (actual_repo_path, suggested_copy_fix) or (None, None).
        """
        filename = Path(src_norm).name.lower()

        # Search for any file with the same name in the repo
        candidates = [
            orig for key, orig in repo_index.items()
            if Path(key).name == filename
        ]

        if not candidates:
            return None, None

        # Pick the best candidate (prefer one under ctx_prefix if context is non-root)
        actual = candidates[0]
        if ctx_prefix:
            under_ctx = [c for c in candidates if c.lower().startswith(ctx_prefix)]
            if under_ctx:
                actual = under_ctx[0]

        # Build the correct COPY source relative to the build context
        if ctx_prefix and actual.lower().startswith(ctx_prefix):
            correct_src = actual[len(ctx_prefix):]  # strip context prefix
        else:
            correct_src = actual  # include full path (context is repo root)

        target_name = "./" + Path(src_norm).name
        suggested = f"COPY {correct_src} {target_name}"
        return actual, suggested

    def _build_message(
        self,
        src: str,
        build_context: str,
        actual_path: Optional[str],
    ) -> str:
        if actual_path:
            return (
                f"COPY source '{src}' not found in build context '{build_context}'. "
                f"The file exists in the repository at '{actual_path}'. "
                f"Adjust the COPY path to match the build context."
            )
        return (
            f"COPY source '{src}' not found in build context '{build_context}'. "
            f"The file does not appear in the repository at all — "
            f"check the file name or add it to the project."
        )

    # ── Runtime-permission validation ─────────────────────────────────────────

    def _validate_runtime_permissions(
        self,
        dockerfile: str,
        framework: Optional[str],
        result: StaticValidationResult,
    ) -> None:
        """
        Catch the runtime-permission bug class that surfaces as
        `PermissionError: [Errno 13] Permission denied: 'workspace'` in production:

          A) USER <non-root>  +  COPY . . (no --chown)
             → /app stays root-owned, runtime process cannot write → HIGH severity
          B) USER <non-root>  +  Python/FastAPI framework  +  no pre-USER mkdir of
             runtime-writable dirs (workspace/logs/tmp) → MEDIUM severity warning
        """
        if not dockerfile or not dockerfile.strip():
            return

        lines = dockerfile.splitlines()

        # Find the LAST USER directive — if it switches to a non-root user, the
        # ownership rule applies to every COPY in the runtime stage.
        user_line: Optional[str] = None
        user_index: int = -1
        for idx, raw in enumerate(lines):
            stripped = raw.strip()
            if re.match(r"(?i)^USER\s+", stripped):
                user_line = stripped
                user_index = idx

        if user_line is None:
            return  # Runs as root — neither check applies

        user_target = re.sub(r"(?i)^USER\s+", "", user_line).strip().split()[0]
        if user_target.lower() in ("root", "0", "0:0"):
            return  # Explicitly running as root — permission checks don't apply

        # ── Identify the runtime stage (after the LAST FROM) ──────────────────
        last_from_idx = -1
        for idx, raw in enumerate(lines):
            if re.match(r"(?i)^FROM\s+", raw.strip()):
                last_from_idx = idx
        runtime_stage = lines[last_from_idx + 1:] if last_from_idx >= 0 else lines

        # ── Rule A: COPY without --chown when USER is non-root ────────────────
        for raw in runtime_stage:
            stripped = raw.strip()
            if not re.match(r"(?i)^COPY\b", stripped):
                continue
            # Skip multistage-only COPYs that bring in build artifacts to a path
            # outside the workdir — those are fine if the runtime user later
            # chowns or only reads them. Still, --chown is the safe default.
            if "--chown=" in stripped.lower():
                continue
            # COPY --from=builder /root/.local /home/appuser/.local — still
            # needs --chown when target runs as non-root.
            result.issues.append(ValidationIssue(
                copy_instruction=stripped,
                source_path="<runtime-stage COPY>",
                build_context="(runtime permission)",
                rule="copy_without_chown_under_nonroot_user",
                severity="high",
                message=(
                    f"Dockerfile drops to non-root USER '{user_target}' but a COPY in "
                    f"the runtime stage does not set --chown. /app and its files will "
                    f"stay root-owned, and the runtime process will hit "
                    f"PermissionError: [Errno 13] when it tries to mkdir/write at runtime."
                ),
                suggested_fix=self._copy_chown_fix(stripped, user_target),
            ))
            result.valid = False

        # ── Rule B: non-root user + Python framework + no writable-dir mkdir ──
        fw = (framework or "").lower()
        framework_needs_writable = any(
            token in fw for token in ("fastapi", "flask", "django", "starlette", "uvicorn", "python")
        )
        if not framework_needs_writable:
            return

        pre_user_lines = lines[:user_index] if user_index >= 0 else lines
        pre_user_blob = "\n".join(pre_user_lines)

        # A "writable runtime dir" preparation is any pre-USER RUN that does
        # mkdir -p <path> + chown ... <path> (or to the WORKDIR ancestor).
        has_mkdir = bool(re.search(r"(?im)^RUN\s+.*mkdir\s+-p\s+\S+", pre_user_blob))
        has_chown = bool(re.search(r"(?im)\bchown\s+-R\s+\S+\s+\S+", pre_user_blob))

        if has_mkdir and has_chown:
            return

        result.warnings.append(
            "Container runs as non-root user but runtime-writable application "
            "directories are not pre-created. Add mkdir/chown before USER switch. "
            "Suggested: 'RUN mkdir -p /app/workspace/repos && chown -R "
            f"{user_target}:{user_target.replace('user', 'group')} /app' before "
            "the USER directive."
        )

    def _copy_chown_fix(self, copy_line: str, user_target: str) -> str:
        """Insert --chown=user:group immediately after the COPY token."""
        group = user_target.replace("user", "group") or "appgroup"
        chown_flag = f"--chown={user_target}:{group}"
        # Split into ['COPY', <rest>] and re-insert the flag
        m = re.match(r"(?i)^(COPY)\b\s+(.*)$", copy_line.strip())
        if not m:
            return f"{chown_flag} {copy_line}"
        return f"COPY {chown_flag} {m.group(2)}"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_skippable(self, src: str) -> bool:
        """True for sources that cannot (or need not) be validated statically."""
        if any(c in src for c in ("*", "?", "[", "]")):
            return True  # glob pattern
        if src.lstrip("./") in _VIRTUAL_SOURCES or src in _VIRTUAL_SOURCES:
            return True
        return False
