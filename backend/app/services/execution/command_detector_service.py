import json
import re
from pathlib import Path
from typing import Any


class CommandDetectorService:
    COMMAND_PATTERNS = [
        re.compile(r"\buvicorn\s+[^\n\r]+"),
        re.compile(r"\bstreamlit\s+run\s+[^\n\r]+"),
        re.compile(r"\bgunicorn\s+[^\n\r]+"),
        re.compile(r"\bpython\s+[^\n\r]+"),
        re.compile(r"\bcelery\s+[^\n\r]+"),
        re.compile(r"\bnpm\s+run\s+[^\n\r]+"),
        re.compile(r"\b(?:\./mvnw|mvn)\s+spring-boot:run\b[^\n\r]*"),
        re.compile(r"\bjava\s+-jar\s+[^\n\r]+"),
    ]

    CANDIDATE_FILES = {
        "README.md",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "Makefile",
        "package.json",
        "pyproject.toml",
    }

    def detect(self, repo_path: str, file_tree: list[str]) -> list[dict[str, Any]]:
        repo = Path(repo_path)
        commands: list[dict[str, Any]] = []

        for rel_path in file_tree:
            path = repo / rel_path
            if not path.exists() or not path.is_file():
                continue

            should_scan = (
                path.name in self.CANDIDATE_FILES
                or rel_path.startswith("scripts/")
                or path.suffix.lower() in {".sh", ".ps1", ".cmd"}
            )
            if not should_scan:
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if path.name == "package.json":
                commands.extend(self._extract_package_json_commands(rel_path, content))

            commands.extend(self._extract_pattern_commands(rel_path, content))
            if path.name == "Dockerfile":
                commands.extend(self._extract_dockerfile_commands(rel_path, content))
            if path.name in {"docker-compose.yml", "docker-compose.yaml"}:
                commands.extend(self._extract_compose_commands(rel_path, content))

        return self._deduplicate(commands)

    def _extract_package_json_commands(self, rel_path: str, content: str) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return []

        scripts = parsed.get("scripts", {})
        commands = []
        for script_name, command in scripts.items():
            if isinstance(command, str):
                commands.append(
                    {
                        "command": command.strip(),
                        "source_file": rel_path,
                        "source_type": "package_script",
                        "service": self._infer_service(rel_path, command),
                        "script_name": script_name,
                    }
                )
        return commands

    def _extract_pattern_commands(self, rel_path: str, content: str) -> list[dict[str, Any]]:
        commands = []
        for pattern in self.COMMAND_PATTERNS:
            for match in pattern.finditer(content):
                command = match.group(0).strip().strip("`").strip('"')
                commands.append(
                    {
                        "command": command,
                        "source_file": rel_path,
                        "source_type": "text_match",
                        "service": self._infer_service(rel_path, command),
                    }
                )
        return commands

    def _extract_dockerfile_commands(self, rel_path: str, content: str) -> list[dict[str, Any]]:
        commands = []
        for line in content.splitlines():
            stripped = line.strip()
            upper = stripped.upper()
            if upper.startswith("CMD ") or upper.startswith("ENTRYPOINT "):
                commands.append(
                    {
                        "command": stripped,
                        "source_file": rel_path,
                        "source_type": "dockerfile",
                        "service": self._infer_service(rel_path, stripped),
                    }
                )
        return commands

    def _extract_compose_commands(self, rel_path: str, content: str) -> list[dict[str, Any]]:
        commands = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("command:"):
                commands.append(
                    {
                        "command": stripped.split(":", 1)[1].strip().strip('"').strip("'"),
                        "source_file": rel_path,
                        "source_type": "compose",
                        "service": self._infer_service(rel_path, stripped),
                    }
                )
        return commands

    def _infer_service(self, source_file: str, command: str) -> str:
        lowered_source = source_file.lower()
        lowered_command = command.lower()

        if "streamlit" in lowered_command or lowered_source.startswith("frontend/"):
            return "frontend"
        if "celery" in lowered_command and "beat" in lowered_command:
            return "scheduler"
        if "celery" in lowered_command or "worker" in lowered_command:
            return "worker"
        if any(token in lowered_command for token in ("uvicorn", "gunicorn", "fastapi", "spring-boot:run", "java -jar")):
            return "backend"
        if "npm run" in lowered_command:
            return "frontend"
        return "application"

    def _deduplicate(self, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = set()
        deduped = []
        for command in commands:
            key = (command["command"], command["source_file"], command.get("script_name"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(command)
        return deduped
