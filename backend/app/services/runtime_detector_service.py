import json
import re
from pathlib import Path
from typing import Any


class RuntimeDetectorService:
    def detect(self, repo_path: str, file_tree: list[str], stack: dict[str, Any]) -> dict[str, Any]:
        repo = Path(repo_path)
        dependency_files = [
            path
            for path in file_tree
            if Path(path).name.lower()
            in {
                "requirements.txt",
                "requirements-backend.txt",
                "pyproject.toml",
                "package.json",
                "pom.xml",
                "build.gradle",
                "build.gradle.kts",
                "mvnw",
                "poetry.lock",
                "pdm.lock",
                "runtime.txt",
            }
        ]

        runtime = {
            "languages": stack.get("languages", []),
            "frameworks": stack.get("frameworks", []),
            "package_managers": stack.get("package_managers", []),
            "dependency_files": dependency_files,
            "python_version": None,
            "node_version": None,
            "java_version": None,
            "system_dependencies": [],
            "copy_paths": self._infer_copy_paths(file_tree),
            "exclude_paths": self._infer_exclude_paths(file_tree),
            "build": {
                "multi_stage_recommended": False,
                "native_compilation_likely": False,
            },
        }

        for rel_path in dependency_files:
            path = repo / rel_path
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            file_name = Path(rel_path).name
            if file_name == "runtime.txt":
                runtime["python_version"] = content.strip() or runtime["python_version"]
            elif file_name == "pyproject.toml":
                runtime["python_version"] = runtime["python_version"] or self._extract_python_constraint(content)
            elif file_name == "package.json":
                runtime["node_version"] = self._extract_node_version(content)
            elif file_name == "pom.xml":
                runtime["java_version"] = runtime["java_version"] or self._extract_java_version(content)

        dockerfile_path = repo / "Dockerfile"
        if dockerfile_path.exists():
            try:
                dockerfile_content = dockerfile_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                dockerfile_content = ""
            runtime["system_dependencies"] = self._extract_system_dependencies(dockerfile_content)
            runtime["build"]["multi_stage_recommended"] = dockerfile_content.upper().count("FROM ") > 1

        dependency_text = self._collect_dependency_text(repo, dependency_files).lower()
        native_markers = ("psycopg2", "cryptography", "lxml", "pillow", "numpy", "scipy", "torch")
        runtime["build"]["native_compilation_likely"] = any(marker in dependency_text for marker in native_markers)

        return runtime

    def _collect_dependency_text(self, repo: Path, dependency_files: list[str]) -> str:
        parts = []
        for rel_path in dependency_files:
            path = repo / rel_path
            try:
                parts.append(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
        return "\n".join(parts)

    def _extract_python_constraint(self, content: str) -> str | None:
        match = re.search(r"python\s*=\s*[\"']([^\"']+)[\"']", content, flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _extract_node_version(self, content: str) -> str | None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        engines = parsed.get("engines", {})
        return engines.get("node") if isinstance(engines.get("node"), str) else None

    def _extract_java_version(self, content: str) -> str | None:
        match = re.search(
            r"<(?:java\.version|maven\.compiler\.(?:source|target))>\s*([^<\s]+)\s*</",
            content,
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else None

    def _extract_system_dependencies(self, dockerfile_content: str) -> list[str]:
        dependencies = []
        for line in dockerfile_content.splitlines():
            stripped = line.strip().lower()
            if "apt-get install" in stripped or "apk add" in stripped:
                dependencies.append(stripped)
        return dependencies

    def _infer_copy_paths(self, file_tree: list[str]) -> list[str]:
        preferred = [name for name in ("backend", "frontend", "agents", "scripts") if any(path.startswith(f"{name}/") for path in file_tree)]
        return preferred or ["."]

    def _infer_exclude_paths(self, file_tree: list[str]) -> list[str]:
        candidates = ["venv", "__pycache__", ".git", ".history", "workspace", ".pytest_cache", "node_modules"]
        return [name for name in candidates if any(path.startswith(f"{name}/") or path == name for path in file_tree)]
