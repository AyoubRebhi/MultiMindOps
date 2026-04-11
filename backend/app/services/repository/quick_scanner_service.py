"""Lightweight repository scanner — no LLM, no file reads, just structure."""
import os
from pathlib import Path
from typing import Any, Dict, List


class QuickScannerService:
    """
    Scans a repository structure without reading file contents.
    Produces a compact summary used by LLMPriorityEngine to select critical files.
    """

    IGNORED_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", ".history", "workspace"}

    # Extensions that hint at language
    LANGUAGE_EXTENSIONS: Dict[str, str] = {
        ".py": "Python",
        ".js": "JavaScript",
        ".ts": "TypeScript",
        ".java": "Java",
        ".go": "Go",
        ".rs": "Rust",
        ".rb": "Ruby",
        ".php": "PHP",
        ".cs": "C#",
        ".cpp": "C++",
        ".c": "C",
    }

    # Files that signal important project roles (no reading needed)
    SIGNAL_FILES = {
        "Dockerfile", "dockerfile",
        "docker-compose.yml", "docker-compose.yaml",
        "package.json", "package-lock.json",
        "requirements.txt", "requirements-backend.txt",
        "pyproject.toml", "setup.py", "setup.cfg",
        "pom.xml", "build.gradle", "build.gradle.kts",
        "Makefile", "makefile",
        "README.md", "readme.md",
        "main.py", "app.py", "manage.py", "server.py",
        "main.ts", "main.js", "index.ts", "index.js",
        "main.go", "main.java",
        "terraform.tf", "main.tf", "variables.tf", "outputs.tf",
        "Chart.yaml", "values.yaml",
        "skaffold.yaml", "tilt.yml",
        ".env.example", ".env.template",
    }

    def scan(self, repo_path: str, max_depth: int = 4) -> Dict[str, Any]:
        """
        Returns a lightweight summary of repo structure for LLM consumption.

        Does NOT read file contents — only walks the directory tree.
        """
        repo = Path(repo_path)
        root_files: List[str] = []
        all_dirs: Dict[str, List[str]] = {}  # dir_path → list of filenames
        extension_counts: Dict[str, int] = {}
        signal_files_found: List[str] = []
        total_files = 0

        for dirpath, dirnames, filenames in os.walk(repo):
            # Prune ignored dirs in-place
            dirnames[:] = [
                d for d in dirnames
                if d not in self.IGNORED_DIRS and not d.startswith(".")
            ]

            rel_dir = str(Path(dirpath).relative_to(repo)).replace("\\", "/")
            depth = rel_dir.count("/") + (0 if rel_dir == "." else 1)

            if depth > max_depth:
                dirnames.clear()
                continue

            for filename in filenames:
                total_files += 1
                ext = Path(filename).suffix.lower()
                extension_counts[ext] = extension_counts.get(ext, 0) + 1

                rel_file = (
                    filename if rel_dir == "."
                    else f"{rel_dir}/{filename}"
                )

                if rel_dir == ".":
                    root_files.append(filename)

                if filename in self.SIGNAL_FILES or filename.lower() in self.SIGNAL_FILES:
                    signal_files_found.append(rel_file)

                # Collect .github/workflows files
                if rel_dir.startswith(".github/workflows") and filename.endswith((".yml", ".yaml")):
                    signal_files_found.append(rel_file)

                # Collect k8s/terraform files
                if ext in (".tf", ".tfvars") or rel_dir.startswith(("k8s/", "kubernetes/", "terraform/")):
                    signal_files_found.append(rel_file)

            if depth <= 2:
                all_dirs[rel_dir] = filenames[:30]  # cap per-dir listing

        languages_hinted = sorted({
            self.LANGUAGE_EXTENSIONS[ext]
            for ext in extension_counts
            if ext in self.LANGUAGE_EXTENSIONS
        })

        top_dirs = sorted(
            d for d in all_dirs
            if d != "." and "/" not in d  # top-level dirs only
        )

        size_category = (
            "small" if total_files < 100
            else "medium" if total_files < 1000
            else "large" if total_files < 5000
            else "very_large"
        )

        is_monorepo = self._detect_monorepo(root_files, top_dirs, signal_files_found)

        return {
            "root_files": sorted(root_files),
            "top_level_dirs": top_dirs,
            "signal_files": sorted(set(signal_files_found))[:60],
            "languages_hinted": languages_hinted,
            "extension_counts": dict(sorted(extension_counts.items(), key=lambda x: -x[1])[:20]),
            "total_files_scanned": total_files,
            "size_category": size_category,
            "hints": {
                "is_monorepo": is_monorepo,
                "has_docker": any("dockerfile" in f.lower() or "docker-compose" in f.lower() for f in signal_files_found),
                "has_ci_cd": any(".github/workflows" in f for f in signal_files_found),
                "has_kubernetes": any(f.startswith(("k8s/", "kubernetes/")) or "chart.yaml" in f.lower() for f in signal_files_found),
                "has_terraform": any(f.endswith(".tf") or f.startswith("terraform/") for f in signal_files_found),
                "has_env_template": any(".env.example" in f or ".env.template" in f for f in signal_files_found),
            },
        }

    def _detect_monorepo(
        self,
        root_files: List[str],
        top_dirs: List[str],
        signal_files: List[str],
    ) -> bool:
        # Multiple package.json at different depths → monorepo
        pkg_json_count = sum(1 for f in signal_files if f.endswith("package.json"))
        if pkg_json_count >= 2:
            return True

        # Multiple requirements.txt at different depths
        req_count = sum(1 for f in signal_files if "requirements.txt" in f)
        if req_count >= 2:
            return True

        # Typical monorepo top-level dirs
        monorepo_dirs = {"packages", "apps", "services", "modules", "libs", "frontend", "backend"}
        overlap = monorepo_dirs & set(top_dirs)
        if len(overlap) >= 2:
            return True

        return False
