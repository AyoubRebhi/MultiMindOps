from pathlib import Path
from typing import Any, Dict, List


class ChunkingService:
    TEXT_EXTENSIONS = {
        ".py",
        ".md",
        ".txt",
        ".yml",
        ".yaml",
        ".json",
        ".toml",
        ".ini",
        ".cfg",
        ".env",
        ".sh",
        ".tf",
        ".rst",
    }

    def build_chunks(
        self,
        repo_path: str,
        file_paths: List[str],
        max_chars_per_chunk: int = 1200,
        max_total_chunks: int = 60,
    ) -> List[Dict[str, Any]]:
        repo = Path(repo_path)
        chunks: List[Dict[str, Any]] = []

        for rel_path in file_paths:
            if len(chunks) >= max_total_chunks:
                break

            path = repo / rel_path
            if not path.exists() or not path.is_file():
                continue

            if path.suffix.lower() not in self.TEXT_EXTENSIONS and path.name not in {
                "Dockerfile",
                "Jenkinsfile",
                "README.md",
                "requirements.txt",
            }:
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            content = content.strip()
            if not content:
                continue

            for idx, chunk_text in enumerate(self._split_text(content, max_chars_per_chunk)):
                if len(chunks) >= max_total_chunks:
                    break

                chunks.append(
                    {
                        "file_path": rel_path,
                        "chunk_index": idx,
                        "content": chunk_text,
                        "category": self._categorize_file(rel_path),
                    }
                )

        return chunks

    def _split_text(self, text: str, max_chars: int) -> List[str]:
        if len(text) <= max_chars:
            return [text]

        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = start + max_chars
            chunks.append(text[start:end])
            start = end
        return chunks

    def _categorize_file(self, rel_path: str) -> str:
        path = rel_path.lower()

        if ".github/workflows" in path or "jenkinsfile" in path or ".gitlab-ci" in path:
            return "ci_cd"
        if "docker" in path or "k8s" in path or "kubernetes" in path or "terraform" in path:
            return "infrastructure"
        if "deploy" in path or "helm" in path:
            return "deployment"
        if "requirements" in path or "package.json" in path or "pyproject.toml" in path:
            return "dependencies"
        if path.endswith(".py"):
            return "source_code"
        return "general"