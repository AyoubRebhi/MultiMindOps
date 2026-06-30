"""Typed results + errors for the Repository Installation phase."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# Canonical on-disk paths for the generated pipelines. These mirror the
# GITHUB_ACTIONS_GENERATION artifact subtypes (the deployment service writes the
# files under exactly these paths), so installation reads + writes the same keys.
BOOTSTRAP_PATH = ".github/workflows/bootstrap.yml"
DEPLOY_PATH = ".github/workflows/deploy.yml"
# The Infrastructure Destroy phase commits this single workflow (reusing the same
# installation machinery as bootstrap/deploy).
DESTROY_PATH = ".github/workflows/destroy.yml"

# Defaults — overridable per call / per project.
DEFAULT_INSTALL_BRANCH = "multiminds/devops-pipelines"
DEFAULT_BASE_BRANCH = "main"
DEFAULT_COMMIT_MESSAGE = "feat: add MultiMinds DevOps pipelines"
DEFAULT_PR_TITLE = "Add MultiMinds DevOps pipelines"

# Dedicated branch + messages for the destroy workflow installation. A separate
# branch keeps the (destructive) destroy.yml change reviewable on its own and
# never collides with an open pipelines-install PR.
DEFAULT_DESTROY_BRANCH = "multiminds/infrastructure-destroy"
DEFAULT_DESTROY_COMMIT_MESSAGE = "chore: add MultiMinds infrastructure destroy workflow"
DEFAULT_DESTROY_PR_TITLE = "Add MultiMinds infrastructure destroy workflow"

# Bot identity used for the installation commit. A fresh clone in CI has no
# global git identity, so the commit sets these locally.
BOT_NAME = "MultiMinds Bot"
BOT_EMAIL = "bot@multiminds.ai"

# Branch names we will NEVER push the generated workflows directly onto. The
# entire point of the phase is a reviewable, non-destructive change set, so a
# request that resolves the installation branch to one of these is rejected
# before any clone happens.
PROTECTED_BRANCHES = frozenset(
    {"main", "master", "develop", "development", "release", "trunk"}
)

# Recognised values for a project's configured default (base) branch.
KNOWN_DEFAULT_BRANCHES = frozenset({"main", "master", "develop"})


class RepositoryInstallationError(Exception):
    """Base error for the installation phase."""


class InstallationPrerequisiteError(RepositoryInstallationError):
    """A required input is missing or unsafe.

    Raised for: no repository URL, no GitHub token, the generated workflow files
    are missing, or the resolved installation branch is a protected branch. These
    are caller-fixable preconditions, so the orchestrator surfaces them as an
    HTTP 400 — distinct from an *operational* git/PR failure, which is captured
    non-raising in :class:`InstallationResult` (the workflow stays open to retry).
    """


@dataclass
class PullRequestOutcome:
    """Result of the optional Pull Request step (always non-fatal)."""

    created: bool = False
    url: Optional[str] = None
    skipped_reason: Optional[str] = None


@dataclass
class WorkflowDispatchOutcome:
    """Result of the post-install bootstrap.yml dispatch (FIX 1, always non-fatal).

    The GitHub workflow_dispatch endpoint returns ``204 No Content`` with no
    body, so ``run_id`` is only set if a caller resolves one separately (no
    polling/waiting here). ``dispatched`` reflects whether GitHub accepted the
    trigger; ``error`` carries a human, non-leaking reason when it did not.
    """

    dispatched: bool = False
    run_id: Optional[int] = None
    status_code: Optional[int] = None
    error: Optional[str] = None

    def to_record(self, *, ref: str, workflow_file: str) -> dict:
        """Compact dict persisted into the installation phase + artifact."""
        return {
            "dispatched": self.dispatched,
            "run_id": self.run_id,
            "ref": ref,
            "workflow_file": workflow_file,
            "status_code": self.status_code,
            "error": self.error,
        }


@dataclass
class InstallationResult:
    """Outcome of an installation attempt.

    ``success`` reflects whether the repository now has the workflows on the
    installation branch (clone + write + commit + push completed, OR everything
    was already present — an idempotent no-op). PR creation never affects
    ``success`` — a missing PR is a documented degradation, not a failure.
    """

    success: bool
    repo_url: str
    base_branch: str
    install_branch: str
    files_written: List[str] = field(default_factory=list)
    committed: bool = False
    commit_sha: Optional[str] = None
    pushed: bool = False
    no_changes: bool = False
    pr_created: bool = False
    pr_url: Optional[str] = None
    pr_skipped_reason: Optional[str] = None
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_artifact_dict(self) -> dict:
        """Compact, durable record persisted as the ``installation.json`` artifact."""
        return {
            "branch": self.install_branch,
            "base_branch": self.base_branch,
            "commit": self.commit_sha,
            "pr_url": self.pr_url,
            "pr_created": self.pr_created,
            "pr_skipped_reason": self.pr_skipped_reason,
            "pushed": self.pushed,
            "committed": self.committed,
            "no_changes": self.no_changes,
            "files": list(self.files_written),
            "success": self.success,
            "error": self.error,
        }
