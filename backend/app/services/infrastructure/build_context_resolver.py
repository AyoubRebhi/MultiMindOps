"""
BuildContextResolver — validates Docker build context and COPY instruction sources.

Goes beyond syntax checking to resolve whether COPY source paths actually exist
relative to the build context root, catching missing-file errors before
`docker build` runs.

Works in two modes:
  1. Filesystem mode  — checks real paths when `repo_root` is provided
  2. Metadata mode    — checks against `known_files` list from codebase analysis
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class CopyResolutionResult:
    instruction: str          # Original COPY line
    sources: List[str]        # Source paths listed in the instruction
    target: str               # Destination path inside the container
    valid: bool
    issues: List[str] = field(default_factory=list)


@dataclass
class BuildContextReport:
    build_context_path: str
    dockerfile_path: Optional[str]
    is_monorepo: bool
    copy_resolutions: List[CopyResolutionResult] = field(default_factory=list)
    invalid_copies: List[str] = field(default_factory=list)
    valid: bool = True
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "build_context_path": self.build_context_path,
            "dockerfile_path": self.dockerfile_path,
            "is_monorepo": self.is_monorepo,
            "valid": self.valid,
            "issues": self.issues,
            "warnings": self.warnings,
            "invalid_copies": self.invalid_copies,
            "copy_count": len(self.copy_resolutions),
            "valid_copies": sum(1 for c in self.copy_resolutions if c.valid),
        }


# Files commonly generated or gitignored that won't appear in known_files
_VIRTUAL_SOURCES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "dist", "build", "target", "__pycache__", "node_modules",
    ".gradle", ".m2", ".pytest_cache", ".mypy_cache",
}

# Common dependency file names → COPY pattern regex
_DEP_FILES: Dict[str, str] = {
    "requirements.txt": r"COPY\s+\S*requirements\S*\.txt",
    "requirements*.txt": r"COPY\s+\S*requirements",
    "package.json": r"COPY\s+\S*package\.json",
    "package-lock.json": r"COPY\s+\S*package-lock\.json",
    "pom.xml": r"COPY\s+\S*pom\.xml",
    "build.gradle": r"COPY\s+\S*build\.gradle",
    "build.gradle.kts": r"COPY\s+\S*build\.gradle\.kts",
    "Gemfile": r"COPY\s+\S*Gemfile\b",
    "go.mod": r"COPY\s+\S*go\.mod",
    "go.sum": r"COPY\s+\S*go\.sum",
    "pyproject.toml": r"COPY\s+\S*pyproject\.toml",
    "Pipfile": r"COPY\s+\S*Pipfile\b",
}


class BuildContextResolver:
    """
    Resolves and validates Docker build context against COPY instructions.

    Operates on actual filesystem when `repo_root` is provided, otherwise
    uses the `known_files` metadata list from CodebaseAnalysisAgent.
    """

    def resolve(
        self,
        dockerfile_content: str,
        build_context: str,
        repo_root: Optional[str] = None,
        known_files: Optional[List[str]] = None,
    ) -> BuildContextReport:
        """
        Analyze COPY instructions against the build context.

        Args:
            dockerfile_content: The Dockerfile text.
            build_context:      Relative path to the Docker build context (e.g. "." or "backend").
            repo_root:          Absolute path to repo root (enables filesystem validation).
            known_files:        File list from codebase analysis (used when no filesystem access).

        Returns:
            BuildContextReport with per-COPY validation and overall validity.
        """
        report = BuildContextReport(
            build_context_path=build_context,
            dockerfile_path=None,
            is_monorepo=self._detect_monorepo(build_context, known_files),
        )

        abs_context: Optional[Path] = None
        if repo_root:
            candidate = Path(repo_root) / build_context
            if candidate.exists():
                abs_context = candidate

        copy_instructions = self._extract_copy_instructions(dockerfile_content)

        for instr, sources, target in copy_instructions:
            resolution = self._resolve_copy(
                instruction=instr,
                sources=sources,
                target=target,
                abs_context=abs_context,
                known_files=known_files,
                build_context=build_context,
            )
            report.copy_resolutions.append(resolution)
            if not resolution.valid:
                report.valid = False
                report.invalid_copies.append(instr)
                report.issues.extend(resolution.issues)

        # Warn on dependency files that may be missing
        report.warnings.extend(
            self._check_dependency_files(dockerfile_content, known_files, build_context)
        )

        logger.info(
            "[BuildContextResolver] context=%s monorepo=%s copies=%d invalid=%d warnings=%d",
            build_context,
            report.is_monorepo,
            len(report.copy_resolutions),
            len(report.invalid_copies),
            len(report.warnings),
        )
        return report

    # ── COPY extraction ───────────────────────────────────────────────────────

    def _extract_copy_instructions(
        self, dockerfile: str
    ) -> List[Tuple[str, List[str], str]]:
        """
        Return (full_line, sources, target) for every COPY that is not --from=<stage>.
        """
        results = []
        for line in dockerfile.splitlines():
            stripped = line.strip()
            if not stripped.upper().startswith("COPY"):
                continue
            if re.search(r"COPY\s+--from=", stripped, re.IGNORECASE):
                continue  # multi-stage reference — not a context copy

            # Remove flag tokens before parsing paths
            clean = re.sub(r"--\w+(?:=\S+)?\s*", "", stripped, flags=re.IGNORECASE)
            parts = clean.split()[1:]  # drop "COPY"
            if len(parts) < 2:
                continue
            target = parts[-1]
            sources = parts[:-1]
            results.append((stripped, sources, target))
        return results

    # ── Resolution ────────────────────────────────────────────────────────────

    def _resolve_copy(
        self,
        instruction: str,
        sources: List[str],
        target: str,
        abs_context: Optional[Path],
        known_files: Optional[List[str]],
        build_context: str,
    ) -> CopyResolutionResult:
        result = CopyResolutionResult(
            instruction=instruction,
            sources=sources,
            target=target,
            valid=True,
        )

        for src in sources:
            # Glob patterns and "copy-all" sources cannot be validated statically
            if any(c in src for c in ["*", "?", "[", "]"]):
                continue
            if src in (".", "./", "/"):
                continue
            if self._is_virtual_source(src):
                continue

            if abs_context is not None:
                # Filesystem mode — definitive
                if not (abs_context / src).exists():
                    result.valid = False
                    result.issues.append(
                        f"COPY source '{src}' does not exist under build context '{build_context}'"
                    )
            elif known_files is not None:
                # Metadata mode — heuristic
                if not self._file_known(src, known_files, build_context):
                    result.valid = False
                    result.issues.append(
                        f"COPY source '{src}' not found in repository "
                        f"(build context: '{build_context}')"
                    )

        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _file_known(
        self, src: str, known_files: List[str], build_context: str
    ) -> bool:
        normalized = src.lstrip("./")
        ctx = build_context.strip("/").lstrip("./")
        ctx_prefix = ctx + "/" if ctx else ""

        for f in known_files:
            nf = f.lstrip("./")
            if nf == normalized:
                return True
            if nf.startswith(normalized + "/"):
                return True
            if ctx_prefix and nf == ctx_prefix + normalized:
                return True
            if ctx_prefix and nf.startswith(ctx_prefix + normalized + "/"):
                return True
        return False

    def _is_virtual_source(self, src: str) -> bool:
        """True for generated/gitignored paths that won't appear in known_files."""
        parts = Path(src.lstrip("./")).parts
        root = parts[0] if parts else ""
        return root in _VIRTUAL_SOURCES or src.lstrip("./") in _VIRTUAL_SOURCES

    def _detect_monorepo(
        self, build_context: str, known_files: Optional[List[str]]
    ) -> bool:
        ctx = build_context.strip().strip("/").lstrip(".")
        if ctx and ctx != ".":
            return True  # Non-root build context implies monorepo layout

        if known_files:
            top_dirs: set = set()
            for f in known_files:
                parts = Path(f.lstrip("./")).parts
                if len(parts) > 1:
                    top_dirs.add(parts[0])
            service_dirs = top_dirs & {
                "backend", "frontend", "api", "web", "services", "apps",
                "client", "server", "gateway", "worker", "ui",
            }
            if len(service_dirs) >= 2:
                return True

        return False

    def _check_dependency_files(
        self,
        dockerfile: str,
        known_files: Optional[List[str]],
        build_context: str,
    ) -> List[str]:
        """Warn when Dockerfile COPYs a dependency file that isn't in the repo."""
        if known_files is None:
            return []

        warnings: List[str] = []
        ctx = build_context.strip("/").lstrip("./")
        ctx_prefix = ctx + "/" if ctx else ""

        for dep_file, pattern in _DEP_FILES.items():
            if not re.search(pattern, dockerfile, re.IGNORECASE):
                continue

            # Check whether the file (with or without build-context prefix) exists
            candidates = [dep_file]
            if ctx_prefix:
                candidates.append(ctx_prefix + dep_file)

            found = any(
                any(nf == c or nf.endswith("/" + c) for nf in known_files)
                for c in candidates
            )
            if not found:
                warnings.append(
                    f"Dockerfile COPYs '{dep_file}' but it was not detected in the repository."
                )

        return warnings
