"""RepositoryInstallationService — install generated workflows into a repo.

Pure git + PR orchestration (NO database access — the orchestrator persists the
phase, mirroring the GitHubActionsGenerationService split). Given the generated
``bootstrap.yml`` + ``deploy.yml`` and a GitHub token, it:

    clone → checkout base branch → create installation branch → write the two
    files → stage ONLY those files → commit → push (never force) → (optional) PR

Safety invariants (enforced here, not assumed by the caller):

* the installation branch is NEVER ``main`` / ``master`` / ``develop`` etc.
  (:data:`PROTECTED_BRANCHES`) — a request that resolves to one is rejected;
* only the provided ``.github/workflows/*.yml`` paths are written + staged —
  nothing else in the repository is read, changed, or deleted;
* no force-push — a rerun adds a fast-forward commit or is an idempotent no-op;
* the cloned working copy (which holds the token in ``.git/config``) is always
  removed in a ``finally`` block;
* operational git/PR failures are CAPTURED (``success=False`` + sanitized
  ``error``), not raised — only missing/unsafe preconditions raise
  :class:`InstallationPrerequisiteError`.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional

from backend.app.services.repository.github_service import (
    GitHubService,
    resolve_workspace_dir,
)
from backend.app.services.repository_installation.git_client import (
    GitClient,
    GitCommandError,
)
from backend.app.services.repository_installation.models import (
    BOT_EMAIL,
    BOT_NAME,
    DEFAULT_BASE_BRANCH,
    DEFAULT_COMMIT_MESSAGE,
    DEFAULT_INSTALL_BRANCH,
    DEFAULT_PR_TITLE,
    PROTECTED_BRANCHES,
    InstallationPrerequisiteError,
    InstallationResult,
    PullRequestOutcome,
)
from backend.app.services.repository_installation.pull_request_client import (
    open_pull_request,
)

logger = logging.getLogger(__name__)

# A callable matching ``open_pull_request`` — injectable so tests never hit the
# network and the orchestrator can disable PR creation by passing a no-op.
PrOpener = Callable[..., PullRequestOutcome]


class RepositoryInstallationService:
    @staticmethod
    def install(
        *,
        repo_url: Optional[str],
        github_token: Optional[str],
        files: Dict[str, str],
        base_branch: Optional[str] = None,
        install_branch: Optional[str] = None,
        commit_message: Optional[str] = None,
        create_pr: bool = True,
        pr_title: Optional[str] = None,
        pr_body: Optional[str] = None,
        workspace_dir: Optional[str] = None,
        git: Optional[GitClient] = None,
        pr_opener: Optional[PrOpener] = None,
    ) -> InstallationResult:
        """Install ``files`` onto a dedicated branch of ``repo_url``.

        ``files`` maps on-disk path → content (e.g.
        ``{".github/workflows/bootstrap.yml": "...", ".../deploy.yml": "..."}``).

        Raises :class:`InstallationPrerequisiteError` for missing/unsafe inputs;
        returns a non-success :class:`InstallationResult` for operational git/PR
        failures (the workflow stays open so the user can retry after a fix).
        """
        base_branch = (base_branch or DEFAULT_BASE_BRANCH).strip() or DEFAULT_BASE_BRANCH
        install_branch = (install_branch or DEFAULT_INSTALL_BRANCH).strip() or DEFAULT_INSTALL_BRANCH
        commit_message = commit_message or DEFAULT_COMMIT_MESSAGE
        pr_title = pr_title or DEFAULT_PR_TITLE

        RepositoryInstallationService._validate_preconditions(
            repo_url=repo_url,
            github_token=github_token,
            files=files,
            base_branch=base_branch,
            install_branch=install_branch,
        )

        # github.com-only validation + token-embedded clone URL (reused from the
        # battle-tested GitHubService helpers). A malformed / non-github.com URL
        # is a caller-fixable precondition, so surface it as such.
        try:
            clone_url = GitHubService._build_authenticated_url(repo_url, github_token)  # type: ignore[arg-type]
            owner, repo = GitHubService._extract_owner_and_repo(repo_url)  # type: ignore[arg-type]
        except ValueError as exc:
            raise InstallationPrerequisiteError(str(exc)) from exc

        git = git or GitClient(redact=github_token)
        pr_opener = pr_opener or open_pull_request

        workspace = resolve_workspace_dir(workspace_dir)
        dest = workspace / f"install_{repo}_{uuid.uuid4().hex[:8]}"

        result = InstallationResult(
            success=False,
            repo_url=GitHubService.normalize_repo_url(repo_url),
            base_branch=base_branch,
            install_branch=install_branch,
        )

        try:
            RepositoryInstallationService._run_git_install(
                git=git,
                clone_url=clone_url,
                dest=dest,
                files=files,
                base_branch=base_branch,
                install_branch=install_branch,
                commit_message=commit_message,
                result=result,
            )
        except GitCommandError as exc:
            result.success = False
            result.error = str(exc)
            result.logs.append(f"Installation failed during git {exc.command}: {exc}")
            logger.warning(
                "[RepoInstall] git %s failed for %s: %s",
                exc.command, result.repo_url, exc,
            )
            return result
        finally:
            # The clone holds the token in .git/config — always remove it.
            shutil.rmtree(dest, ignore_errors=True)

        # ── Optional Pull Request (best-effort, never fails the install) ──────
        if create_pr and (result.pushed or result.no_changes):
            RepositoryInstallationService._open_pr(
                pr_opener=pr_opener,
                owner=owner,
                repo=repo,
                token=github_token,  # type: ignore[arg-type]
                head=install_branch,
                base=base_branch,
                title=pr_title,
                body=pr_body or RepositoryInstallationService.default_pr_body(files),
                result=result,
            )
        elif not create_pr:
            result.pr_skipped_reason = "pull request creation disabled"

        result.success = True
        result.logs.append("Installation completed.")
        logger.info(
            "[RepoInstall] %s → branch=%s commit=%s pushed=%s pr=%s",
            result.repo_url, install_branch, result.commit_sha, result.pushed,
            result.pr_url or result.pr_skipped_reason,
        )
        return result

    # ── Steps ────────────────────────────────────────────────────────────────

    @staticmethod
    def _run_git_install(
        *,
        git: GitClient,
        clone_url: str,
        dest: Path,
        files: Dict[str, str],
        base_branch: str,
        install_branch: str,
        commit_message: str,
        result: InstallationResult,
    ) -> None:
        """Clone → branch → write → stage → commit → push. Mutates ``result``."""
        # 1. Does the installation branch already exist on the remote? If so, we
        #    clone IT and add on top (fast-forward) so reruns never force-push.
        remote_has_install = git.remote_branch_exists(clone_url, install_branch)

        result.logs.append("Cloning repository...")
        if remote_has_install:
            git.clone(clone_url, dest, branch=install_branch)
            result.logs.append(
                f"Installation branch '{install_branch}' already exists — updating it."
            )
        else:
            git.clone(clone_url, dest, branch=base_branch)
            git.checkout_new_branch(dest, install_branch)
            result.logs.append(
                f"Created installation branch '{install_branch}' from '{base_branch}'."
            )

        git.set_identity(dest, BOT_NAME, BOT_EMAIL)

        # 2. Write ONLY the provided workflow files.
        result.logs.append("Creating workflow directory...")
        for path, content in files.items():
            target = dest / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            result.files_written.append(path)
            result.logs.append(f"Writing {Path(path).name}...")

        # 3. Stage ONLY those paths (never `git add -A`).
        git.stage(dest, list(files.keys()))

        # 4. Commit only when something actually changed (idempotent rerun).
        if git.has_staged_changes(dest):
            result.logs.append("Creating commit...")
            result.commit_sha = git.commit(dest, commit_message)
            result.committed = True
        else:
            result.no_changes = True
            result.commit_sha = git.head_sha(dest)
            result.logs.append("No changes — workflows already up to date.")

        # 5. Push. Needed when we made a new commit OR when the install branch
        #    does not yet exist on the remote (a brand-new branch identical to
        #    base still needs its ref created so a PR can be opened).
        if result.committed or not remote_has_install:
            result.logs.append("Pushing branch...")
            git.push(dest, install_branch)
            result.pushed = True
        else:
            result.logs.append("Nothing to push — installation branch is up to date.")

    @staticmethod
    def _open_pr(
        *,
        pr_opener: PrOpener,
        owner: str,
        repo: str,
        token: str,
        head: str,
        base: str,
        title: str,
        body: str,
        result: InstallationResult,
    ) -> None:
        try:
            outcome = pr_opener(
                owner=owner, repo=repo, token=token,
                head=head, base=base, title=title, body=body,
            )
        except Exception as exc:  # noqa: BLE001 — PR must never fail the install
            result.pr_skipped_reason = (
                f"pull request step errored ({exc.__class__.__name__})"
            )
            result.logs.append(f"Pull request skipped: {result.pr_skipped_reason}")
            return
        result.pr_created = outcome.created
        result.pr_url = outcome.url
        result.pr_skipped_reason = outcome.skipped_reason
        if outcome.url:
            result.logs.append(
                f"Pull request {'opened' if outcome.created else 'already open'}: {outcome.url}"
            )
        else:
            result.logs.append(f"Pull request skipped: {outcome.skipped_reason}")

    # ── Validation ───────────────────────────────────────────────────────────

    @staticmethod
    def _validate_preconditions(
        *,
        repo_url: Optional[str],
        github_token: Optional[str],
        files: Dict[str, str],
        base_branch: str,
        install_branch: str,
    ) -> None:
        if not repo_url:
            raise InstallationPrerequisiteError(
                "the project has no repository URL — cannot install workflows."
            )
        if not github_token:
            raise InstallationPrerequisiteError(
                "a GitHub token is required to clone and push to the repository."
            )
        if not files or not all((c or "").strip() for c in files.values()):
            raise InstallationPrerequisiteError(
                "the generated workflow files are missing or empty — run "
                "GitHub Actions Generation first."
            )
        if install_branch.lower() in PROTECTED_BRANCHES:
            raise InstallationPrerequisiteError(
                f"refusing to install onto protected branch '{install_branch}' — "
                "workflows are installed on a dedicated branch for review."
            )
        if install_branch == base_branch:
            raise InstallationPrerequisiteError(
                f"the installation branch must differ from the base branch "
                f"('{base_branch}')."
            )

    # ── PR body ──────────────────────────────────────────────────────────────

    @staticmethod
    def default_pr_body(files: Dict[str, str]) -> str:
        paths = sorted(files.keys())
        lines = [
            "This pull request adds the MultiMinds-generated DevOps pipelines.",
            "",
            "**Files**",
        ]
        for p in paths:
            lines.append(f"- `{p}`")
        lines += [
            "",
            "**Pipelines**",
            "- `bootstrap.yml` — Infrastructure pipeline: provisions/updates "
            "Terraform infrastructure and runs the first deploy (manual "
            "`workflow_dispatch`).",
            "- `deploy.yml` — Delivery pipeline: continuous delivery on every "
            "push (no Terraform).",
            "",
            "**Consumed by the pipelines**",
            "- `terraform/*` — infrastructure-as-code bootstrap.yml runs "
            "`terraform init/apply` against.",
            "- `Dockerfile` — the image both pipelines build and push.",
            "",
            "Review and merge when ready. Only the files listed above are added "
            "or updated — no other repository content is modified.",
        ]
        return "\n".join(lines)
