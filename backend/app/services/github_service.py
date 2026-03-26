import os
import shutil
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlparse


class GitHubService:
    def __init__(self, workspace_dir: str = "workspace/repos") -> None:
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def clone_repository(
        self,
        repo_url: str,
        repository_visibility: str = "public",
        github_token: str | None = None,
    ) -> str:
        repo_name = self._extract_repo_name(repo_url)
        target_dir = self.workspace_dir / f"{repo_name}_{uuid.uuid4().hex[:8]}"

        if target_dir.exists():
            shutil.rmtree(target_dir)

        clone_url = repo_url

        if repository_visibility == "private":
            if not github_token:
                raise ValueError("GitHub token is required for private repositories.")
            clone_url = self._build_authenticated_url(repo_url, github_token)

        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", clone_url, str(target_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            raise RuntimeError(
                f"Git clone failed: {self._sanitize_git_error(stderr)}"
            ) from e

        return str(target_dir)

    @staticmethod
    def _extract_repo_name(repo_url: str) -> str:
        parsed = urlparse(repo_url)
        repo_name = os.path.basename(parsed.path.rstrip("/"))
        return repo_name.replace(".git", "") or "repository"

    @staticmethod
    def _build_authenticated_url(repo_url: str, github_token: str) -> str:
        parsed = urlparse(repo_url)

        if parsed.netloc not in {"github.com", "www.github.com"}:
            raise ValueError("Only github.com repositories are supported.")

        clean_path = parsed.path
        return f"https://{github_token}@github.com{clean_path}"

    @staticmethod
    def _sanitize_git_error(stderr: str) -> str:
        return stderr.replace("\n", " ").replace("\r", " ").strip()