"""Tests for the Repository Installation phase.

Two layers:

1. ``RepositoryInstallationService`` orchestration + safety, exercised with an
   in-memory FakeGitClient + FakePrOpener so the logic (branch strategy, write,
   stage, commit, push, idempotency, PR) is pinned WITHOUT a real remote.
2. ``GitClient`` against a REAL local bare repository (skipped if ``git`` is not
   installed) — proves clone / branch / commit / push / idempotent rerun /
   existing-branch replacement work end-to-end with actual git.

Covers the required cases: missing token, invalid repository, branch creation,
file writing, commit creation, push failure, idempotent reruns, and existing
workflow replacement.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.services.repository_installation.git_client import (
    GitClient,
    GitCommandError,
)
from backend.app.services.repository_installation.installation_service import (
    RepositoryInstallationService,
)
from backend.app.services.repository_installation.models import (
    BOOTSTRAP_PATH,
    DEFAULT_INSTALL_BRANCH,
    DEPLOY_PATH,
    InstallationPrerequisiteError,
    PullRequestOutcome,
)

REPO_URL = "https://github.com/acme/widget"
TOKEN = "ghp_secrettoken123"
FILES = {BOOTSTRAP_PATH: "name: bootstrap\n", DEPLOY_PATH: "name: deploy\n"}


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeGitClient:
    """Records git calls; simulates remote/branch/staged-changes state.

    ``stage`` reads the files on disk so a test can assert the service actually
    WROTE the workflow content before staging it.
    """

    def __init__(self, *, remote_has_install=False, staged=True, push_error=False):
        self.remote_has_install = remote_has_install
        self._staged = staged
        self._push_error = push_error
        self.calls = []
        self.cloned_branch = None
        self.created_branch = None
        self.staged_files = {}
        self.committed_message = None
        self.pushed_branch = None

    def remote_branch_exists(self, clone_url, branch):
        self.calls.append(("remote_branch_exists", branch))
        return self.remote_has_install

    def clone(self, clone_url, dest, *, branch=None, depth=1):
        self.calls.append(("clone", branch))
        self.cloned_branch = branch
        # The service writes into dest; make sure it exists like a real clone.
        Path(dest).mkdir(parents=True, exist_ok=True)

    def checkout_new_branch(self, repo_dir, branch):
        self.calls.append(("checkout_new_branch", branch))
        self.created_branch = branch

    def set_identity(self, repo_dir, name, email):
        self.calls.append(("set_identity", name))

    def stage(self, repo_dir, paths):
        self.calls.append(("stage", tuple(paths)))
        for p in paths:
            self.staged_files[p] = (Path(repo_dir) / p).read_text(encoding="utf-8")

    def has_staged_changes(self, repo_dir):
        return self._staged

    def commit(self, repo_dir, message):
        self.calls.append(("commit", message))
        self.committed_message = message
        return "fakesha1234567"

    def head_sha(self, repo_dir):
        return "headsha000000"

    def push(self, repo_dir, branch, *, remote="origin"):
        self.calls.append(("push", branch))
        if self._push_error:
            raise GitCommandError("remote rejected", command="push", returncode=1)
        self.pushed_branch = branch


class FakePrOpener:
    def __init__(self, outcome=None, raises=False):
        self.outcome = outcome or PullRequestOutcome(created=True, url="https://github.com/acme/widget/pull/1")
        self.raises = raises
        self.called_with = None

    def __call__(self, **kwargs):
        self.called_with = kwargs
        if self.raises:
            raise RuntimeError("boom")
        return self.outcome


def _names(calls):
    return [c[0] for c in calls]


# ── Preconditions / safety ───────────────────────────────────────────────────

def test_missing_token_raises_prerequisite():
    with pytest.raises(InstallationPrerequisiteError, match="GitHub token"):
        RepositoryInstallationService.install(
            repo_url=REPO_URL, github_token=None, files=FILES, git=FakeGitClient()
        )


def test_missing_repo_url_raises_prerequisite():
    with pytest.raises(InstallationPrerequisiteError, match="repository URL"):
        RepositoryInstallationService.install(
            repo_url=None, github_token=TOKEN, files=FILES, git=FakeGitClient()
        )


def test_missing_files_raises_prerequisite():
    with pytest.raises(InstallationPrerequisiteError, match="missing or empty"):
        RepositoryInstallationService.install(
            repo_url=REPO_URL, github_token=TOKEN, files={}, git=FakeGitClient()
        )


def test_invalid_repository_raises_prerequisite():
    # A non-github.com URL is rejected before any clone.
    git = FakeGitClient()
    with pytest.raises(InstallationPrerequisiteError):
        RepositoryInstallationService.install(
            repo_url="https://gitlab.com/acme/widget", github_token=TOKEN,
            files=FILES, git=git,
        )
    assert git.calls == []  # never touched git


def test_protected_install_branch_refused():
    with pytest.raises(InstallationPrerequisiteError, match="protected branch"):
        RepositoryInstallationService.install(
            repo_url=REPO_URL, github_token=TOKEN, files=FILES,
            install_branch="main", git=FakeGitClient(),
        )


# ── Branch creation + file writing + commit + push ───────────────────────────

def test_branch_creation_writes_commits_pushes(tmp_path):
    git = FakeGitClient(remote_has_install=False, staged=True)
    pr = FakePrOpener()
    result = RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=FILES,
        base_branch="main", workspace_dir=str(tmp_path), git=git, pr_opener=pr,
    )

    assert result.success is True
    # Cloned the BASE branch, then created the dedicated install branch.
    assert git.cloned_branch == "main"
    assert git.created_branch == DEFAULT_INSTALL_BRANCH
    # File writing: the exact workflow content reached disk + was staged.
    assert git.staged_files[BOOTSTRAP_PATH] == FILES[BOOTSTRAP_PATH]
    assert git.staged_files[DEPLOY_PATH] == FILES[DEPLOY_PATH]
    assert sorted(result.files_written) == sorted(FILES.keys())
    # Commit + push.
    assert result.committed is True
    assert result.commit_sha == "fakesha1234567"
    assert result.pushed is True
    assert git.pushed_branch == DEFAULT_INSTALL_BRANCH
    # PR opened.
    assert result.pr_created is True
    assert result.pr_url.endswith("/pull/1")
    assert pr.called_with["head"] == DEFAULT_INSTALL_BRANCH
    assert pr.called_with["base"] == "main"


def test_only_workflow_paths_are_staged(tmp_path):
    git = FakeGitClient()
    RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=FILES,
        workspace_dir=str(tmp_path), git=git, pr_opener=FakePrOpener(),
    )
    staged = next(c[1] for c in git.calls if c[0] == "stage")
    assert set(staged) == set(FILES.keys())  # never a broad `git add -A`


def test_installs_nested_terraform_dir_and_root_dockerfile(tmp_path):
    """The runnable file set (pipelines + terraform/*.tf + Dockerfile) is written
    to disk under its real paths and staged — nested dirs are created."""
    files = {
        BOOTSTRAP_PATH: "name: bootstrap\n",
        DEPLOY_PATH: "name: deploy\n",
        "terraform/main.tf": 'resource "aws_eks_cluster" "m" {}\n',
        "terraform/terraform.tfvars": 'project_name = "app"\n',
        "Dockerfile": "FROM python:3.12-slim\n",
    }
    git = FakeGitClient()
    result = RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=files,
        workspace_dir=str(tmp_path), git=git, pr_opener=FakePrOpener(),
    )

    assert result.success is True
    # Every path was written (with content) and staged — exactly this set.
    assert git.staged_files["terraform/main.tf"] == files["terraform/main.tf"]
    assert git.staged_files["Dockerfile"] == files["Dockerfile"]
    staged = next(c[1] for c in git.calls if c[0] == "stage")
    assert set(staged) == set(files.keys())
    assert sorted(result.files_written) == sorted(files.keys())


def test_clone_dir_is_cleaned_up(tmp_path):
    git = FakeGitClient()
    RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=FILES,
        workspace_dir=str(tmp_path), git=git, pr_opener=FakePrOpener(),
    )
    # The token-bearing clone must not linger in the workspace.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("install_")]
    assert leftovers == []


# ── Push failure ─────────────────────────────────────────────────────────────

def test_push_failure_is_captured_not_raised(tmp_path):
    git = FakeGitClient(remote_has_install=False, staged=True, push_error=True)
    pr = FakePrOpener()
    result = RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=FILES,
        workspace_dir=str(tmp_path), git=git, pr_opener=pr,
    )
    assert result.success is False
    assert "remote rejected" in (result.error or "")
    assert result.pushed is False
    assert pr.called_with is None  # no PR attempted on a failed push


# ── Idempotent rerun (no changes) ────────────────────────────────────────────

def test_idempotent_rerun_no_changes(tmp_path):
    # Install branch already exists remotely AND content is unchanged.
    git = FakeGitClient(remote_has_install=True, staged=False)
    pr = FakePrOpener(outcome=PullRequestOutcome(created=False, url="https://github.com/acme/widget/pull/1"))
    result = RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=FILES,
        workspace_dir=str(tmp_path), git=git, pr_opener=pr,
    )
    assert result.success is True
    assert result.no_changes is True
    assert result.committed is False
    assert result.pushed is False              # nothing to push
    assert "commit" not in _names(git.calls)
    assert "push" not in _names(git.calls)
    # Cloned the existing install branch directly (no new branch created).
    assert git.cloned_branch == DEFAULT_INSTALL_BRANCH
    assert git.created_branch is None


# ── Existing workflow replacement ────────────────────────────────────────────

def test_existing_branch_replacement_adds_commit(tmp_path):
    # Install branch exists remotely; the new workflows DIFFER → a new commit on
    # top (fast-forward), never a force-push or a fresh branch.
    git = FakeGitClient(remote_has_install=True, staged=True)
    result = RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=FILES,
        workspace_dir=str(tmp_path), git=git, pr_opener=FakePrOpener(),
    )
    assert result.success is True
    assert git.cloned_branch == DEFAULT_INSTALL_BRANCH   # worked ON the existing branch
    assert git.created_branch is None                    # did NOT recreate it
    assert result.committed is True
    assert result.pushed is True


# ── PR optionality + graceful degradation ────────────────────────────────────

def test_pr_disabled_records_reason(tmp_path):
    pr = FakePrOpener()
    result = RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=FILES, create_pr=False,
        workspace_dir=str(tmp_path), git=FakeGitClient(), pr_opener=pr,
    )
    assert result.success is True
    assert result.pr_created is False
    assert result.pr_skipped_reason == "pull request creation disabled"
    assert pr.called_with is None


def test_pr_error_does_not_fail_install(tmp_path):
    pr = FakePrOpener(raises=True)
    result = RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=FILES,
        workspace_dir=str(tmp_path), git=FakeGitClient(), pr_opener=pr,
    )
    assert result.success is True              # the install itself still succeeds
    assert result.pr_created is False
    assert "errored" in (result.pr_skipped_reason or "")


def test_token_never_leaks_into_logs(tmp_path):
    result = RepositoryInstallationService.install(
        repo_url=REPO_URL, github_token=TOKEN, files=FILES,
        workspace_dir=str(tmp_path), git=FakeGitClient(), pr_opener=FakePrOpener(),
    )
    blob = "\n".join(result.logs) + (result.error or "")
    assert TOKEN not in blob


# ── Real git integration (skipped if git is unavailable) ─────────────────────

def _git_available():
    return shutil.which("git") is not None


def _run(args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def bare_remote(tmp_path):
    """A real bare repo (the 'remote') seeded with one commit on ``main``."""
    remote = tmp_path / "remote.git"
    _run(["git", "init", "--bare", "-b", "main", str(remote)], cwd=tmp_path)

    seed = tmp_path / "seed"
    _run(["git", "clone", str(remote), str(seed)], cwd=tmp_path)
    _run(["git", "config", "user.email", "seed@test"], cwd=seed)
    _run(["git", "config", "user.name", "Seed"], cwd=seed)
    (seed / "README.md").write_text("hello\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=seed)
    _run(["git", "commit", "-m", "seed"], cwd=seed)
    _run(["git", "push", "origin", "main"], cwd=seed)
    return remote


@pytest.mark.skipif(not _git_available(), reason="git not installed")
def test_gitclient_end_to_end_branch_commit_push(bare_remote, tmp_path):
    git = GitClient(redact=None)
    url = str(bare_remote)
    assert git.remote_branch_exists(url, DEFAULT_INSTALL_BRANCH) is False

    dest = tmp_path / "work"
    git.clone(url, dest, branch="main")
    git.checkout_new_branch(dest, DEFAULT_INSTALL_BRANCH)
    git.set_identity(dest, "Bot", "bot@test")

    for path, content in FILES.items():
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git.stage(dest, list(FILES.keys()))

    assert git.has_staged_changes(dest) is True
    sha = git.commit(dest, "feat: add MultiMinds DevOps pipelines")
    assert len(sha) >= 7
    git.push(dest, DEFAULT_INSTALL_BRANCH)

    # The remote now has the install branch.
    assert git.remote_branch_exists(url, DEFAULT_INSTALL_BRANCH) is True


@pytest.mark.skipif(not _git_available(), reason="git not installed")
def test_gitclient_idempotent_second_run_has_no_changes(bare_remote, tmp_path):
    git = GitClient(redact=None)
    url = str(bare_remote)

    # First install on a fresh branch.
    d1 = tmp_path / "w1"
    git.clone(url, d1, branch="main")
    git.checkout_new_branch(d1, DEFAULT_INSTALL_BRANCH)
    git.set_identity(d1, "Bot", "bot@test")
    for path, content in FILES.items():
        (d1 / path).parent.mkdir(parents=True, exist_ok=True)
        (d1 / path).write_text(content, encoding="utf-8")
    git.stage(d1, list(FILES.keys()))
    git.commit(d1, "feat: add MultiMinds DevOps pipelines")
    git.push(d1, DEFAULT_INSTALL_BRANCH)

    # Second run: clone the EXISTING install branch, write identical files.
    d2 = tmp_path / "w2"
    git.clone(url, d2, branch=DEFAULT_INSTALL_BRANCH)
    git.set_identity(d2, "Bot", "bot@test")
    for path, content in FILES.items():
        (d2 / path).parent.mkdir(parents=True, exist_ok=True)
        (d2 / path).write_text(content, encoding="utf-8")
    git.stage(d2, list(FILES.keys()))
    assert git.has_staged_changes(d2) is False  # idempotent — nothing to commit


@pytest.mark.skipif(not _git_available(), reason="git not installed")
def test_gitclient_push_failure_raises(tmp_path):
    git = GitClient(redact=None)
    # Clone a real repo, then point a push at a nonexistent remote URL.
    remote = tmp_path / "r.git"
    _run(["git", "init", "--bare", "-b", "main", str(remote)], cwd=tmp_path)
    seed = tmp_path / "seed"
    _run(["git", "clone", str(remote), str(seed)], cwd=tmp_path)
    _run(["git", "config", "user.email", "s@t"], cwd=seed)
    _run(["git", "config", "user.name", "s"], cwd=seed)
    (seed / "f").write_text("x", encoding="utf-8")
    _run(["git", "add", "f"], cwd=seed)
    _run(["git", "commit", "-m", "s"], cwd=seed)
    _run(["git", "push", "origin", "main"], cwd=seed)

    work = tmp_path / "work"
    git.clone(str(remote), work, branch="main")
    git.set_identity(work, "Bot", "bot@test")
    # Repoint origin at a path that does not exist → push must fail.
    _run(["git", "remote", "set-url", "origin", str(tmp_path / "does_not_exist.git")], cwd=work)
    git.checkout_new_branch(work, DEFAULT_INSTALL_BRANCH)
    (work / "g").write_text("y", encoding="utf-8")
    git.stage(work, ["g"])
    git.commit(work, "c")
    with pytest.raises(GitCommandError):
        git.push(work, DEFAULT_INSTALL_BRANCH)
