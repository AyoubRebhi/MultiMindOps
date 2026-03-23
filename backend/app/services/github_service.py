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

    def clone_repository(self, repo_url: str) -> str:
        repo_name = self._extract_repo_name(repo_url)
        target_dir = self.workspace_dir / f"{repo_name}_{uuid.uuid4().hex[:8]}"

        if target_dir.exists():
            shutil.rmtree(target_dir)

        subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(target_dir)],
            check=True,
            capture_output=True,
            text=True,
        )

        return str(target_dir)

    @staticmethod
    def _extract_repo_name(repo_url: str) -> str:
        parsed = urlparse(repo_url)
        repo_name = os.path.basename(parsed.path.rstrip("/"))
        return repo_name.replace(".git", "") or "repository"