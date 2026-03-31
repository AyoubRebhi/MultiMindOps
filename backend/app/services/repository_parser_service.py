from pathlib import Path
from typing import Any, Dict, List

from backend.app.services.chunking_service import ChunkingService


class RepositoryParserService:
    IMPORTANT_FILES = {
        "README.md",
        "requirements.txt",
        "package.json",
        "pyproject.toml",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "main.py",
        "app.py",
        "manage.py",
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
        "scripts",
    }

    def __init__(self):
        self.chunking_service = ChunkingService()

    def parse_repository(self, repo_path: str) -> Dict[str, Any]:
        repo = Path(repo_path)

        file_tree = self._build_file_tree(repo)
        important_files = self._find_important_files(repo)
        categorized_files = self._categorize_files(file_tree)
        stack = self._detect_stack(repo, file_tree)
        key_entrypoints = self._extract_key_entrypoints(file_tree)
        key_files_content = self._read_key_files(repo, important_files)
        chunks = self.chunking_service.build_chunks(repo_path, important_files)

        return {
            "repo_path": str(repo),
            "file_tree": file_tree,
            "important_files": important_files,
            "categorized_files": categorized_files,
            "detected_stack": stack,
            "key_entrypoints": key_entrypoints,
            "key_files_content": key_files_content,
            "chunks": chunks,
            "project_summary": self._build_project_summary(
                stack=stack,
                categorized_files=categorized_files,
                key_entrypoints=key_entrypoints,
                important_files=important_files,
            ),
        }

    def _build_file_tree(self, repo: Path, max_files: int = 250) -> List[str]:
        file_tree: List[str] = []

        for path in repo.rglob("*"):
            if ".git" in path.parts:
                continue
            if path.is_file():
                file_tree.append(str(path.relative_to(repo)).replace("\\", "/"))
            if len(file_tree) >= max_files:
                break

        return sorted(file_tree)

    def _find_important_files(self, repo: Path) -> List[str]:
        found: List[str] = []

        for path in repo.rglob("*"):
            if ".git" in path.parts:
                continue

            rel_path = str(path.relative_to(repo)).replace("\\", "/")

            if path.is_dir() and path.name in self.IMPORTANT_DIRS:
                found.append(rel_path)

            if path.is_file():
                if path.name in self.IMPORTANT_FILES:
                    found.append(rel_path)
                elif any(part in self.IMPORTANT_DIRS for part in path.parts):
                    found.append(rel_path)
                elif rel_path.startswith(".github/workflows/"):
                    found.append(rel_path)

        return sorted(set(found))[:120]

    def _categorize_files(self, file_tree: List[str]) -> Dict[str, List[str]]:
        infra_files = []
        ci_cd_files = []
        deployment_files = []
        dependency_files = []
        source_files = []

        for file_path in file_tree:
            lower = file_path.lower()

            if (
                "docker" in lower
                or lower.startswith("k8s/")
                or lower.startswith("kubernetes/")
                or lower.startswith("terraform/")
                or lower.endswith(".tf")
            ):
                infra_files.append(file_path)

            if (
                lower.startswith(".github/workflows/")
                or "jenkinsfile" in lower
                or ".gitlab-ci" in lower
            ):
                ci_cd_files.append(file_path)

            if "deploy" in lower or "helm" in lower or "release" in lower:
                deployment_files.append(file_path)

            if (
                lower.endswith("requirements.txt")
                or lower.endswith("package.json")
                or lower.endswith("pyproject.toml")
            ):
                dependency_files.append(file_path)

            if lower.endswith(".py") or lower.endswith(".js") or lower.endswith(".ts"):
                source_files.append(file_path)

        return {
            "infra_files": sorted(infra_files),
            "ci_cd_files": sorted(ci_cd_files),
            "deployment_files": sorted(deployment_files),
            "dependency_files": sorted(dependency_files),
            "source_files": sorted(source_files),
        }

    def _detect_stack(self, repo: Path, file_tree: List[str]) -> Dict[str, Any]:
        lower_files = [f.lower() for f in file_tree]

        languages = []
        frameworks = []
        package_managers = []
        devops_tools = []

        if any(f.endswith(".py") for f in lower_files):
            languages.append("Python")
        if any(f.endswith(".js") for f in lower_files):
            languages.append("JavaScript")
        if any(f.endswith(".ts") for f in lower_files):
            languages.append("TypeScript")
        if any(f.endswith(".java") for f in lower_files):
            languages.append("Java")

        if "requirements.txt" in lower_files or "pyproject.toml" in lower_files:
            package_managers.append("pip")
        if "package.json" in lower_files:
            package_managers.append("npm/yarn")
        if "pom.xml" in lower_files:
            package_managers.append("maven")
        if "build.gradle" in lower_files:
            package_managers.append("gradle")

        framework_markers = self._read_small_framework_markers(repo, file_tree)

        if "fastapi" in framework_markers:
            frameworks.append("FastAPI")
        if "flask" in framework_markers:
            frameworks.append("Flask")
        if "django" in framework_markers:
            frameworks.append("Django")
        if "springboot" in framework_markers or "spring-boot" in framework_markers:
            frameworks.append("Spring Boot")
        if "react" in framework_markers:
            frameworks.append("React")
        if "vue" in framework_markers:
            frameworks.append("Vue")

        if any("dockerfile" in f for f in lower_files):
            devops_tools.append("Docker")
        if any("docker-compose.yml" in f or "docker-compose.yaml" in f for f in lower_files):
            devops_tools.append("Docker Compose")
        if any(f.startswith(".github/workflows/") for f in lower_files):
            devops_tools.append("GitHub Actions")
        if any("jenkinsfile" in f for f in lower_files):
            devops_tools.append("Jenkins")
        if any(f.startswith("k8s/") or f.startswith("kubernetes/") for f in lower_files):
            devops_tools.append("Kubernetes")
        if any(f.endswith(".tf") or f.startswith("terraform/") for f in lower_files):
            devops_tools.append("Terraform")

        return {
            "languages": languages,
            "frameworks": frameworks,
            "package_managers": package_managers,
            "devops_tools": devops_tools,
        }

    def _read_small_framework_markers(self, repo: Path, file_tree: List[str]) -> str:
        markers = []

        candidate_files = [
            f for f in file_tree
            if f.endswith(("requirements.txt", "pyproject.toml", "package.json", "main.py", "app.py", "__init__.py"))
        ][:20]

        for rel_path in candidate_files:
            path = repo / rel_path
            if not path.exists() or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:3000].lower()
                markers.append(text)
            except Exception:
                continue

        return "\n".join(markers)

    def _extract_key_entrypoints(self, file_tree: List[str]) -> List[str]:
        entrypoint_candidates = []

        preferred_names = {
            "main.py",
            "app.py",
            "manage.py",
            "run.py",
            "__main__.py",
            "wsgi.py",
            "asgi.py",
        }

        for file_path in file_tree:
            name = Path(file_path).name.lower()
            lower = file_path.lower()

            if name in preferred_names:
                entrypoint_candidates.append(file_path)
            elif lower.endswith("/main.py") or lower.endswith("/app.py"):
                entrypoint_candidates.append(file_path)
            elif lower.startswith(".github/workflows/"):
                continue

        return sorted(set(entrypoint_candidates))[:20]

    def _read_key_files(self, repo: Path, important_files: List[str], max_chars: int = 1000) -> Dict[str, str]:
        contents: Dict[str, str] = {}

        priority_files = [
            "README.md",
            "requirements.txt",
            "pyproject.toml",
            "package.json",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "main.py",
            "app.py",
        ]

        selected_files = []
        for pf in priority_files:
            if pf in important_files:
                selected_files.append(pf)

        for rel_path in important_files:
            if rel_path not in selected_files and len(selected_files) < 10:
                selected_files.append(rel_path)

        for rel_path in selected_files:
            path = repo / rel_path
            if not path.exists() or not path.is_file():
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
                contents[rel_path] = text[:max_chars]
            except Exception:
                continue

        return contents

    def _build_project_summary(
        self,
        stack: Dict[str, Any],
        categorized_files: Dict[str, List[str]],
        key_entrypoints: List[str],
        important_files: List[str],
    ) -> Dict[str, Any]:
        return {
            "project_type": self._infer_project_type(stack),
            "stack": stack,
            "has_backend": any("backend" in f.lower() for f in important_files),
            "has_frontend": any("frontend" in f.lower() for f in important_files),
            "has_agents": any("agents" in f.lower() for f in important_files),
            "has_docker": len(categorized_files["infra_files"]) > 0,
            "has_ci_cd": len(categorized_files["ci_cd_files"]) > 0,
            "has_kubernetes": any("k8s" in f.lower() or "kubernetes" in f.lower() for f in categorized_files["infra_files"]),
            "has_terraform": any(f.lower().endswith(".tf") or "terraform" in f.lower() for f in categorized_files["infra_files"]),
            "key_entrypoints": key_entrypoints,
            "infra_files": categorized_files["infra_files"],
            "ci_cd_files": categorized_files["ci_cd_files"],
            "deployment_files": categorized_files["deployment_files"],
        }

    def _infer_project_type(self, stack: Dict[str, Any]) -> str:
        frameworks = stack.get("frameworks", [])
        languages = stack.get("languages", [])

        if "FastAPI" in frameworks:
            return "FastAPI backend"
        if "Flask" in frameworks:
            return "Flask backend"
        if "Django" in frameworks:
            return "Django backend"
        if "Spring Boot" in frameworks:
            return "Spring Boot backend"
        if "React" in frameworks:
            return "React frontend"
        if "Python" in languages:
            return "Python application"
        if languages:
            return f"{languages[0]} application"
        return "Unknown project type"