import hashlib
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


class RepositoryFingerprintService:
    def normalize_repo_url(self, repo_url: str) -> str:
        parsed = urlparse(repo_url.strip())
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return f"https://{host}{path}"

    def build_identity(
        self,
        repo_url: str,
        branch: str | None = None,
        commit_sha: str | None = None,
    ) -> dict:
        return {
            "normalized_url": self.normalize_repo_url(repo_url),
            "branch": branch or "HEAD",
            "commit_sha": commit_sha,
        }

    def build_content_fingerprint(
        self,
        repo_path: str,
        candidate_files: Iterable[str],
        max_files: int = 40,
    ) -> str | None:
        repo = Path(repo_path)
        digest = hashlib.sha256()
        included = 0

        for rel_path in sorted(set(candidate_files)):
            if included >= max_files:
                break

            path = repo / rel_path
            if not path.exists() or not path.is_file():
                continue

            try:
                content = path.read_bytes()
            except Exception:
                continue

            digest.update(rel_path.encode("utf-8", errors="ignore"))
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")
            included += 1

        if included == 0:
            return None

        return digest.hexdigest()
