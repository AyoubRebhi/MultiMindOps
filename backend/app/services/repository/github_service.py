import base64
import os
import shutil
import subprocess
import uuid
from typing import Any
from pathlib import Path
from urllib.parse import urlparse

import requests


class GitHubService:
    MAX_VIEWABLE_FILE_BYTES = 200 * 1024

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

    def get_remote_repository_metadata(
        self,
        repo_url: str,
        repository_visibility: str = "public",
        github_token: str | None = None,
    ) -> dict[str, Any]:
        clone_url = repo_url
        if repository_visibility == "private":
            if not github_token:
                raise ValueError("GitHub token is required for private repositories.")
            clone_url = self._build_authenticated_url(repo_url, github_token)

        result = subprocess.run(
            ["git", "ls-remote", "--symref", clone_url, "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )

        branch = "HEAD"
        commit_sha = None

        for line in result.stdout.splitlines():
            if line.startswith("ref: ") and "\tHEAD" in line:
                ref_name = line.split("\t", 1)[0].replace("ref: ", "").strip()
                branch = ref_name.replace("refs/heads/", "")
            elif line.endswith("\tHEAD"):
                commit_sha = line.split("\t", 1)[0].strip()

        return {
            "normalized_url": self.normalize_repo_url(repo_url),
            "branch": branch,
            "commit_sha": commit_sha,
        }

    def get_repository_file_content(
        self,
        repo_url: str,
        file_path: str,
        branch: str = "main",
        repository_visibility: str = "public",
        github_token: str | None = None,
    ) -> dict[str, str]:
        owner, repo = self._extract_owner_and_repo(repo_url)
        normalized_path = str(file_path or "").replace("\\", "/").strip().lstrip("/")
        if not normalized_path:
            raise ValueError("file_path is required.")

        headers = {
            "Accept": "application/vnd.github+json",
        }
        if repository_visibility == "private":
            if not github_token:
                raise PermissionError("GitHub token is required for private repositories.")
            headers["Authorization"] = f"Bearer {github_token}"

        endpoint = f"https://api.github.com/repos/{owner}/{repo}/contents/{normalized_path}"
        response = requests.get(
            endpoint,
            headers=headers,
            params={"ref": branch or "main"},
            timeout=30,
        )

        if response.status_code == 404:
            raise FileNotFoundError(f"GitHub file not found: {normalized_path}")
        if response.status_code in {401, 403}:
            raise PermissionError("Unable to access the requested GitHub file.")
        if not response.ok:
            raise RuntimeError(
                f"GitHub contents API failed with status {response.status_code}."
            )

        payload = response.json()
        if payload.get("type") != "file":
            raise ValueError(f"GitHub path is not a file: {normalized_path}")

        size = int(payload.get("size") or 0)
        if size > self.MAX_VIEWABLE_FILE_BYTES:
            raise ValueError(
                f"GitHub file is too large to display safely ({size} bytes)."
            )

        encoded_content = str(payload.get("content") or "")
        encoding = str(payload.get("encoding") or "base64").lower()
        if encoding != "base64":
            raise ValueError(f"Unsupported GitHub content encoding: {encoding}")

        decoded_bytes = base64.b64decode(encoded_content, validate=False)
        if len(decoded_bytes) > self.MAX_VIEWABLE_FILE_BYTES:
            raise ValueError(
                f"GitHub file is too large to display safely ({len(decoded_bytes)} bytes)."
            )

        return {
            "path": normalized_path,
            "content": decoded_bytes.decode("utf-8"),
            "encoding": "utf-8",
        }

    def verify_existing_github_workflow(
        self,
        repo_url: str,
        file_path: str,
        branch: str = "main",
        repository_visibility: str = "public",
        github_token: str | None = None,
    ) -> bool:
        normalized_path = str(file_path or "").replace("\\", "/").strip()
        if not normalized_path.startswith(".github/workflows/") or not normalized_path.endswith(
            (".yml", ".yaml")
        ):
            return False

        try:
            self.get_repository_file_content(
                repo_url=repo_url,
                file_path=normalized_path,
                branch=branch,
                repository_visibility=repository_visibility,
                github_token=github_token,
            )
            return True
        except (FileNotFoundError, PermissionError, ValueError, RuntimeError):
            return False

    @staticmethod
    def _extract_repo_name(repo_url: str) -> str:
        parsed = urlparse(repo_url)
        repo_name = os.path.basename(parsed.path.rstrip("/"))
        return repo_name.replace(".git", "") or "repository"

    @staticmethod
    def _extract_owner_and_repo(repo_url: str) -> tuple[str, str]:
        parsed = urlparse(repo_url.strip())
        path_parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(path_parts) < 2:
            raise ValueError("Invalid GitHub repository URL.")
        owner = path_parts[0]
        repo = path_parts[1].replace(".git", "")
        return owner, repo

    @staticmethod
    def normalize_repo_url(repo_url: str) -> str:
        parsed = urlparse(repo_url.strip())
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return f"https://{parsed.netloc.lower()}{path}"

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
