import ast
import re
from pathlib import Path
from typing import Any


class EnvironmentVariableExtractorService:
    ENV_FILE_NAMES = {
        ".env",
        ".env.example",
        ".env.local",
        "config.py",
        "settings.py",
        "constants.py",
        "docker-compose.yml",
        "docker-compose.yaml",
        "Dockerfile",
    }

    PYTHON_EXTENSIONS = {".py"}
    TEXT_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".yml", ".yaml", ".toml", ".env", ".txt", ".properties"}

    def extract(self, repo_path: str, file_tree: list[str]) -> list[dict[str, Any]]:
        repo = Path(repo_path)
        detections: list[dict[str, Any]] = []

        for rel_path in file_tree:
            path = repo / rel_path
            if not path.exists() or not path.is_file():
                continue

            should_scan = (
                path.suffix.lower() in self.TEXT_EXTENSIONS
                or path.name in self.ENV_FILE_NAMES
                or "config" in path.name.lower()
                or "settings" in path.name.lower()
            )
            if not should_scan:
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            if path.suffix.lower() in self.PYTHON_EXTENSIONS:
                detections.extend(self._extract_from_python(rel_path, content))

            detections.extend(self._extract_from_text(rel_path, path.name, content))

        return self._deduplicate(detections)

    def _extract_from_python(self, rel_path: str, content: str) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return detections

        for node in ast.walk(tree):
            detected = self._extract_from_python_call(rel_path, node)
            if detected:
                detections.append(detected)

            if isinstance(node, ast.Subscript):
                detected = self._extract_from_python_subscript(rel_path, node)
                if detected:
                    detections.append(detected)

            if isinstance(node, ast.ClassDef) and self._is_basesettings_class(node):
                detections.extend(self._extract_basesettings_fields(rel_path, node))

        return detections

    def _extract_from_python_call(self, rel_path: str, node: ast.AST) -> dict[str, Any] | None:
        if not isinstance(node, ast.Call):
            return None

        env_name = None
        default_value = None

        if self._is_attribute_call(node.func, ("os",), ("getenv",)):
            env_name = self._literal_string(node.args[0]) if node.args else None
            default_value = self._literal_value(node.args[1]) if len(node.args) > 1 else None
        elif self._is_attribute_call(node.func, ("os", "environ"), ("get",)):
            env_name = self._literal_string(node.args[0]) if node.args else None
            default_value = self._literal_value(node.args[1]) if len(node.args) > 1 else None
        elif self._is_attribute_call(node.func, (), ("getenv",)):
            env_name = self._literal_string(node.args[0]) if node.args else None
            default_value = self._literal_value(node.args[1]) if len(node.args) > 1 else None

        if not env_name:
            return None

        return self._build_detection(
            name=env_name,
            source_file=rel_path,
            line_number=getattr(node, "lineno", None),
            required=default_value is None,
            default=default_value,
        )

    def _extract_from_python_subscript(self, rel_path: str, node: ast.Subscript) -> dict[str, Any] | None:
        if not isinstance(node.value, ast.Attribute):
            return None
        if not (
            isinstance(node.value.value, ast.Name)
            and node.value.value.id == "os"
            and node.value.attr == "environ"
        ):
            return None

        env_name = self._literal_string(node.slice)
        if not env_name:
            return None

        return self._build_detection(
            name=env_name,
            source_file=rel_path,
            line_number=getattr(node, "lineno", None),
            required=True,
            default=None,
        )

    def _extract_basesettings_fields(self, rel_path: str, node: ast.ClassDef) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []

        for child in node.body:
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                env_name = child.target.id
                if not env_name.isupper():
                    continue
                default_value = self._literal_value(child.value) if child.value else None
                detections.append(
                    self._build_detection(
                        name=env_name,
                        source_file=rel_path,
                        line_number=getattr(child, "lineno", None),
                        required=child.value is None,
                        default=default_value,
                    )
                )
            elif isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        detections.append(
                            self._build_detection(
                                name=target.id,
                                source_file=rel_path,
                                line_number=getattr(child, "lineno", None),
                                required=False,
                                default=self._literal_value(child.value),
                            )
                        )

        return detections

    def _extract_from_text(self, rel_path: str, file_name: str, content: str) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []
        lines = content.splitlines()
        compose_pattern = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?:(:-|-)([^}]*))?\}")
        dotenv_pattern = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)$")
        allow_dotenv_pattern = (
            file_name.startswith(".env")
            or file_name in {"docker-compose.yml", "docker-compose.yaml", "Dockerfile"}
            or file_name.endswith((".yml", ".yaml", ".toml"))
        )

        for line_index, line in enumerate(lines, start=1):
            for match in compose_pattern.finditer(line):
                detections.append(
                    self._build_detection(
                        name=match.group(1),
                        source_file=rel_path,
                        line_number=line_index,
                        required=match.group(2) is None,
                        default=match.group(3) or None,
                    )
                )

            dotenv_match = dotenv_pattern.match(line) if allow_dotenv_pattern else None
            if dotenv_match:
                detections.append(
                    self._build_detection(
                        name=dotenv_match.group(1),
                        source_file=rel_path,
                        line_number=line_index,
                        required=False,
                        default=dotenv_match.group(2).strip() or None,
                    )
                )

        return detections

    def _build_detection(
        self,
        *,
        name: str,
        source_file: str,
        line_number: int | None,
        required: bool,
        default: Any,
    ) -> dict[str, Any]:
        category = self._categorize(name)
        return {
            "name": name,
            "source_file": source_file,
            "line_number": line_number,
            "required": required,
            "default": self._sanitize_default(name, category, default),
            "service": self._infer_service(source_file),
            "category": category,
        }

    def _deduplicate(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for detection in detections:
            key = (detection["name"], detection["source_file"])
            existing = by_key.get(key)
            if not existing:
                by_key[key] = detection
                continue
            existing["required"] = existing["required"] or detection["required"]
            if existing.get("default") is None and detection.get("default") is not None:
                existing["default"] = detection["default"]
        return sorted(by_key.values(), key=lambda item: (item["service"], item["name"], item["source_file"]))

    def _infer_service(self, source_file: str) -> str:
        lowered = source_file.lower()
        if lowered.startswith("backend/"):
            return "backend"
        if lowered.startswith("frontend/"):
            return "frontend"
        if "worker" in lowered:
            return "worker"
        if "scheduler" in lowered or "beat" in lowered:
            return "scheduler"
        return "application"

    def _categorize(self, env_name: str) -> str:
        name = env_name.upper()
        if any(token in name for token in ("POSTGRES", "MYSQL", "MONGO", "DB_", "DATABASE", "SQLALCHEMY")):
            return "database"
        if any(token in name for token in ("REDIS", "CACHE", "MEMCACHED")):
            return "cache"
        if any(token in name for token in ("RABBIT", "QUEUE", "BROKER", "CELERY")):
            return "queue"
        if any(token in name for token in ("SECRET", "PASSWORD", "TOKEN", "KEY")):
            return "secret"
        if any(token in name for token in ("API", "WEBHOOK", "GROQ", "OPENAI", "STRIPE", "SLACK")):
            return "external_api"
        if any(token in name for token in ("HOST", "PORT", "ENV", "DEBUG", "DEPLOY", "KUBE")):
            return "deployment"
        return "app"

    def _is_basesettings_class(self, node: ast.ClassDef) -> bool:
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "BaseSettings":
                return True
            if isinstance(base, ast.Attribute) and base.attr == "BaseSettings":
                return True
        return False

    def _is_attribute_call(self, func: ast.AST, object_chain: tuple[str, ...], attr_names: tuple[str, ...]) -> bool:
        if not isinstance(func, ast.Attribute) or func.attr not in attr_names:
            return False
        parts = []
        current: ast.AST | None = func.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        parts.reverse()
        return tuple(parts) == object_chain

    def _literal_string(self, node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def _literal_value(self, node: ast.AST | None) -> Any:
        if node is None:
            return None
        if isinstance(node, ast.Constant):
            return node.value
        return None

    def _sanitize_default(self, env_name: str, category: str, value: Any) -> Any:
        if isinstance(value, str):
            if category == "secret":
                return None
            upper_name = env_name.upper()
            if upper_name in {"DATABASE_URL", "BROKER_URL", "CACHE_URL", "REDIS_URL"}:
                return None
            upper = value.upper()
            if any(token in upper for token in ("SECRET", "PASSWORD", "TOKEN", "KEY")):
                return None
            return value
        return value
