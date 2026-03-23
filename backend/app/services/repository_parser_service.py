from pathlib import Path
from typing import Any, Dict, List


class RepositoryParserService:
    IMPORTANT_FILES = {
        "README.md",
        "requirements.txt",
        "package.json",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "main.py",
        "app.py",
        "Jenkinsfile",
    }

    IMPORTANT_DIRS = {
        ".github",
        "k8s",
        "kubernetes",
        "terraform",
        "infra",
        "helm",
        "backend",
        "frontend",
        "agents",
    }

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
        ".dockerfile",
    }

    def parse_repository(self, repo_path: str) -> Dict[str, Any]:
        repo = Path(repo_path)

        file_tree = self._build_file_tree(repo)
        important_files = self._find_important_files(repo)
        stack = self._detect_stack(file_tree, important_files)
        key_files_content = self._read_key_files(repo, important_files)

        return {
            "repo_path": str(repo),
            "file_tree": file_tree,
            "important_files": important_files,
            "detected_stack": stack,
            "key_files_content": key_files_content,
            "project_summary": self._build_project_summary(stack, important_files),
        }

    def _build_file_tree(self, repo: Path, max_files: int = 300) -> List[str]:
        file_tree: List[str] = []

        for path in repo.rglob("*"):
            if ".git" in path.parts:
                continue
            if path.is_file():
                file_tree.append(str(path.relative_to(repo)))
            if len(file_tree) >= max_files:
                break

        return sorted(file_tree)

    def _find_important_files(self, repo: Path) -> List[str]:
        found: List[str] = []

        for path in repo.rglob("*"):
            if ".git" in path.parts:
                continue

            if path.is_dir() and path.name in self.IMPORTANT_DIRS:
                found.append(str(path.relative_to(repo)))

            if path.is_file():
                if path.name in self.IMPORTANT_FILES:
                    found.append(str(path.relative_to(repo)))
                elif any(part in self.IMPORTANT_DIRS for part in path.parts):
                    found.append(str(path.relative_to(repo)))

        return sorted(set(found))

    def _detect_stack(self, file_tree: List[str], important_files: List[str]) -> Dict[str, Any]:
        lower_files = [f.lower() for f in file_tree]

        languages = []
        frameworks = []
        devops_tools = []

        if any(f.endswith(".py") for f in lower_files):
            languages.append("Python")
        if any(f.endswith(".js") or f.endswith(".ts") for f in lower_files):
            languages.append("JavaScript/TypeScript")

        if any("fastapi" in f for f in lower_files) or "requirements.txt" in lower_files:
            frameworks.append("FastAPI/Python backend")
        if "package.json" in lower_files:
            frameworks.append("Node.js frontend/backend")

        if any("dockerfile" in f for f in lower_files):
            devops_tools.append("Docker")
        if any("docker-compose.yml" in f or "docker-compose.yaml" in f for f in lower_files):
            devops_tools.append("Docker Compose")
        if any(f.startswith(".github/workflows/") for f in lower_files):
            devops_tools.append("GitHub Actions")
        if any(f.startswith("k8s/") or f.startswith("kubernetes/") for f in lower_files):
            devops_tools.append("Kubernetes")
        if any(f.startswith("terraform/") or f.endswith(".tf") for f in lower_files):
            devops_tools.append("Terraform")

        return {
            "languages": languages,
            "frameworks": frameworks,
            "devops_tools": devops_tools,
        }

    def _read_key_files(self, repo: Path, important_files: List[str], max_chars: int = 6000) -> Dict[str, str]:
        contents: Dict[str, str] = {}

        for rel_path in important_files:
            path = repo / rel_path
            if not path.is_file():
                continue

            if path.suffix.lower() not in self.TEXT_EXTENSIONS and path.name not in {
                "Dockerfile",
                "Jenkinsfile",
                "README.md",
                "requirements.txt",
            }:
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                contents[rel_path] = text[:max_chars]
            except Exception:
                continue

        return contents

    def _build_project_summary(self, stack: Dict[str, Any], important_files: List[str]) -> Dict[str, Any]:
        return {
            "has_backend": any("backend" in f for f in important_files),
            "has_frontend": any("frontend" in f for f in important_files),
            "has_agents": any("agents" in f for f in important_files),
            "has_docker": any("docker" in f.lower() for f in important_files),
            "has_ci_cd": any(".github/workflows" in f for f in important_files),
            "has_kubernetes": any("k8s" in f.lower() or "kubernetes" in f.lower() for f in important_files),
            "has_terraform": any("terraform" in f.lower() or f.endswith(".tf") for f in important_files),
            "stack": stack,
        }