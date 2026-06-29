"""GitClient — a thin, synchronous wrapper over the system ``git`` CLI.

Why subprocess (not GitPython, not asyncio)
-------------------------------------------
* No new dependency — ``git`` is already required by ``GitHubService``.
* SYNCHRONOUS ``subprocess.run`` is safe on every event loop, including the
  SelectorEventLoop that ``uvicorn --reload`` forces on Windows (the same reason
  ``docker_connectivity`` falls back to sync subprocesses — see the Windows
  subprocess loop fix). The installation phase runs inline in a sync route, so
  there is no event loop to worry about, but staying sync keeps it portable.

Security
--------
Every captured output is scrubbed of the configured secret (the GitHub token,
which is embedded in an authenticated remote URL) BEFORE it is logged or raised,
so a token can never leak through a git error message or a verbose log line.

The client is intentionally a small, mockable seam: the installation service
talks ONLY to these methods, so tests can inject a fake to exercise the
orchestration logic without a real git remote, while the real client is covered
by integration tests against a local bare repository.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Union

logger = logging.getLogger(__name__)

_PathLike = Union[str, Path]


class GitCommandError(RuntimeError):
    """A ``git`` invocation returned a non-zero exit code (or timed out).

    ``stderr`` is already redacted of the secret.
    """

    def __init__(
        self,
        message: str,
        *,
        command: str,
        returncode: int,
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.stderr = stderr


class GitClient:
    """Minimal git operations needed to install workflow files on a branch."""

    def __init__(self, *, redact: Optional[str] = None, timeout: int = 180) -> None:
        # The secret to scrub from all output (typically the GitHub token).
        self._redact = redact or None
        self._timeout = timeout

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _scrub(self, text: Optional[str]) -> str:
        if not text:
            return ""
        out = text
        if self._redact:
            out = out.replace(self._redact, "***")
        return out.replace("\r", " ").replace("\n", " ").strip()

    def _run(self, args: Sequence[str], *, cwd: Optional[_PathLike] = None) -> str:
        """Run ``git <args>``; raise :class:`GitCommandError` on failure."""
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=str(cwd) if cwd is not None else None,
                check=True,
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.CalledProcessError as exc:
            stderr = self._scrub(exc.stderr)
            raise GitCommandError(
                stderr or f"git {args[0]} failed (exit {exc.returncode})",
                command=str(args[0]),
                returncode=exc.returncode,
                stderr=stderr,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError(
                f"git {args[0]} timed out after {self._timeout}s",
                command=str(args[0]),
                returncode=-1,
            ) from exc
        except FileNotFoundError as exc:  # git not installed
            raise GitCommandError(
                "git executable not found on PATH",
                command=str(args[0]),
                returncode=-1,
            ) from exc
        return proc.stdout or ""

    # ── Read operations ──────────────────────────────────────────────────────

    def remote_branch_exists(self, clone_url: str, branch: str) -> bool:
        """True iff ``branch`` already exists on the remote (``ls-remote --heads``)."""
        out = self._run(["ls-remote", "--heads", clone_url, branch])
        return bool(out.strip())

    def head_sha(self, repo_dir: _PathLike) -> str:
        return self._run(["rev-parse", "HEAD"], cwd=repo_dir).strip()

    def current_branch(self, repo_dir: _PathLike) -> str:
        return self._run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir).strip()

    def has_staged_changes(self, repo_dir: _PathLike) -> bool:
        """True when the index differs from HEAD.

        Uses ``diff --cached --quiet`` whose exit code IS the answer (1 = there
        are staged changes), so a non-zero return here is expected, not an error
        — hence the direct subprocess call rather than :meth:`_run`.
        """
        proc = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        return proc.returncode != 0

    # ── Mutating operations ──────────────────────────────────────────────────

    def clone(
        self,
        clone_url: str,
        dest: _PathLike,
        *,
        branch: Optional[str] = None,
        depth: Optional[int] = 1,
    ) -> None:
        args: List[str] = ["clone"]
        if depth:
            args += ["--depth", str(depth)]
        if branch:
            args += ["--branch", branch]
        args += [clone_url, str(dest)]
        self._run(args)

    def checkout_new_branch(self, repo_dir: _PathLike, branch: str) -> None:
        # -B: create or reset the LOCAL branch. Safe — this is a throwaway clone,
        # and it is never force-pushed (see push()).
        self._run(["checkout", "-B", branch], cwd=repo_dir)

    def set_identity(self, repo_dir: _PathLike, name: str, email: str) -> None:
        self._run(["config", "user.name", name], cwd=repo_dir)
        self._run(["config", "user.email", email], cwd=repo_dir)

    def stage(self, repo_dir: _PathLike, paths: Sequence[str]) -> None:
        # ``-f`` forces the explicit paths past a repository ``.gitignore`` that
        # excludes ``.github`` (common in app repos that don't track their own CI
        # — git otherwise refuses with "paths are ignored by one of your
        # .gitignore files"). This is safe ONLY because the ``--`` pathspec
        # separator + the explicit, enumerated workflow paths guarantee we stage
        # exactly the files we just wrote — never a wildcard or ``git add -A`` —
        # so ``-f`` cannot pull in any other ignored file.
        self._run(["add", "-f", "--", *paths], cwd=repo_dir)

    def commit(self, repo_dir: _PathLike, message: str) -> str:
        self._run(["commit", "-m", message], cwd=repo_dir)
        return self.head_sha(repo_dir)

    def push(self, repo_dir: _PathLike, branch: str, *, remote: str = "origin") -> None:
        # NEVER --force. A brand-new branch, or a fast-forward of the dedicated
        # installation branch — a non-fast-forward is rejected by git, which is
        # the desired safety behaviour (we surface it, we don't clobber).
        self._run(["push", "--set-upstream", remote, branch], cwd=repo_dir)
