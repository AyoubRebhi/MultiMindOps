import re
from pathlib import Path
from typing import Any

from backend.app.services.environment.env_hashing_service import EnvHashingService


class EnvSanitizerService:
    SENSITIVE_PATTERNS = (
        "KEY",
        "SECRET",
        "TOKEN",
        "PASSWORD",
        "PASS",
        "DATABASE_URL",
        "API_KEY",
        "JWT_SECRET",
        "ACCESS_TOKEN",
        "REFRESH_TOKEN",
        "PRIVATE_KEY",
        "BROKER_URL",
        "REDIS_URL",
        "CACHE_URL",
    )

    SAFE_VALUE_NAMES = {
        "APP_ENV",
        "ENV",
        "FLASK_ENV",
        "NODE_ENV",
        "PORT",
        "DEBUG",
        "LOG_LEVEL",
        "APP_NAME",
        "HOST",
    }

    SAFE_LITERAL_PATTERN = re.compile(r"^(true|false|dev|prod|test|local|staging|\d+)$", re.IGNORECASE)

    def __init__(self):
        self.hashing_service = EnvHashingService()

    def extract(
        self,
        repo_path: str,
        env_files: list[dict[str, Any]],
        uploaded_env: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        repo = Path(repo_path)
        file_summaries = []
        variable_records = []
        sensitive_values: list[str] = []

        for env_file in env_files:
            rel_path = str(env_file["path"])
            path = repo / rel_path
            if not path.exists() or not path.is_file():
                continue

            try:
                raw_content = path.read_text(encoding="utf-8", errors="ignore")
                raw_bytes = path.read_bytes()
            except Exception:
                continue

            parsed_variables = self._parse_env_content(rel_path, raw_content)
            sensitive_count = sum(1 for item in parsed_variables if item["is_sensitive"])
            file_summaries.append(
                {
                    "path": rel_path,
                    "name": path.name,
                    "source": "repository",
                    "file_hash": self.hashing_service.hash_bytes(raw_bytes),
                    "variable_count": len(parsed_variables),
                    "sensitive_variables_count": sensitive_count,
                }
            )
            variable_records.extend(parsed_variables)
            sensitive_values.extend(
                item["_runtime_value"]
                for item in parsed_variables
                if item.get("_runtime_value") and item.get("is_sensitive")
            )

        if uploaded_env and uploaded_env.get("content"):
            upload_name = uploaded_env.get("filename") or ".env.uploaded"
            upload_rel_path = f"uploaded/{upload_name}"
            upload_content = self._decode_uploaded_content(uploaded_env["content"])
            parsed_uploaded_variables = self._parse_env_content(
                upload_rel_path,
                upload_content,
                source="uploaded",
            )
            file_summaries.append(
                {
                    "path": upload_rel_path,
                    "name": upload_name,
                    "source": "uploaded",
                    "file_hash": self.hashing_service.hash_bytes(uploaded_env["content"]),
                    "variable_count": len(parsed_uploaded_variables),
                    "sensitive_variables_count": sum(
                        1 for item in parsed_uploaded_variables if item["is_sensitive"]
                    ),
                }
            )
            variable_records.extend(parsed_uploaded_variables)
            sensitive_values.extend(
                item["_runtime_value"]
                for item in parsed_uploaded_variables
                if item.get("_runtime_value") and item.get("is_sensitive")
            )

        env_fingerprint = self._build_env_fingerprint(file_summaries)
        sanitized_variables = self._deduplicate_variables(variable_records)
        runtime_values = [
            item.get("_runtime_value")
            for item in sanitized_variables
            if item.get("_runtime_value")
        ]
        persisted_variables = [
            {key: value for key, value in item.items() if not key.startswith("_")}
            for item in sanitized_variables
        ]

        return {
            "env_files": file_summaries,
            "env_variables": persisted_variables,
            "env_fingerprint": env_fingerprint,
            "sanitized_env_context": {
                "env_detected": bool(file_summaries),
                "env_fingerprint": env_fingerprint,
                "source": self._infer_context_source(file_summaries),
                "files": file_summaries,
                "variables": persisted_variables,
                "variable_names": [item["name"] for item in persisted_variables],
                "sensitive_variables_count": sum(
                    1 for item in persisted_variables if item.get("is_sensitive")
                ),
                "used_for_generation_count": sum(
                    1 for item in persisted_variables if item.get("used_for_generation")
                ),
            },
            "runtime_security": {
                "sensitive_values": sorted(set(filter(None, sensitive_values))),
                "all_values": sorted(set(filter(None, runtime_values))),
            },
        }

    def _parse_env_content(
        self,
        rel_path: str,
        content: str,
        *,
        source: str = "repository",
    ) -> list[dict[str, Any]]:
        variables = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            if stripped.startswith("export "):
                stripped = stripped[7:].strip()

            name, raw_value = stripped.split("=", 1)
            name = name.strip()
            if not re.match(r"^[A-Z][A-Z0-9_]*$", name):
                continue

            value = self._normalize_value(raw_value)
            has_value = value != ""
            is_sensitive = self._is_sensitive(name)
            category = self._categorize(name)
            sanitized_value = self._sanitize_value(name, value, is_sensitive)

            variables.append(
                {
                    "name": name,
                    "source_file": rel_path,
                    "line_number": line_number,
                    "category": category,
                    "service": self._infer_service(rel_path),
                    "required": False,
                    "default": sanitized_value,
                    "existing_in_env": True,
                    "has_value": has_value,
                    "is_sensitive": is_sensitive,
                    "value_hash": (
                        self.hashing_service.hash_text(value) if has_value else None
                    ),
                    "sanitized_value": sanitized_value,
                    "used_for_generation": True,
                    "env_source": source,
                    "_source_priority": self._source_priority(source),
                    "_runtime_value": value if has_value else None,
                }
            )

        return variables

    def _deduplicate_variables(
        self,
        variables: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for item in variables:
            existing = deduped.get(item["name"])
            if not existing:
                deduped[item["name"]] = item
                continue

            previous_source = existing.get("env_source")
            existing["existing_in_env"] = existing.get("existing_in_env") or item.get(
                "existing_in_env"
            )
            existing["has_value"] = existing.get("has_value") or item.get("has_value")
            existing["is_sensitive"] = existing.get("is_sensitive") or item.get(
                "is_sensitive"
            )
            existing["used_for_generation"] = existing.get(
                "used_for_generation"
            ) or item.get("used_for_generation")
            existing_priority = existing.get("_source_priority", 0)
            item_priority = item.get("_source_priority", 0)
            if item_priority > existing_priority:
                existing["source_file"] = item.get("source_file")
                existing["line_number"] = item.get("line_number")
                existing["env_source"] = item.get("env_source")
                existing["_source_priority"] = item_priority
                if item.get("sanitized_value") is not None:
                    existing["sanitized_value"] = item["sanitized_value"]
                    existing["default"] = item["sanitized_value"]
                if item.get("value_hash") is not None:
                    existing["value_hash"] = item["value_hash"]
                if item.get("_runtime_value") is not None:
                    existing["_runtime_value"] = item["_runtime_value"]
            if existing.get("sanitized_value") is None and item.get("sanitized_value") is not None:
                existing["sanitized_value"] = item["sanitized_value"]
                existing["default"] = item["sanitized_value"]
            if existing.get("value_hash") is None and item.get("value_hash") is not None:
                existing["value_hash"] = item["value_hash"]
            if existing.get("_runtime_value") is None and item.get("_runtime_value") is not None:
                existing["_runtime_value"] = item["_runtime_value"]
            if existing.get("has_value") is False and item.get("has_value"):
                existing["source_file"] = item.get("source_file")
                existing["line_number"] = item.get("line_number")
                existing["env_source"] = item.get("env_source")
            if previous_source and previous_source != item.get("env_source"):
                existing["env_source"] = "merged"

        return sorted(deduped.values(), key=lambda item: (item["service"], item["name"]))

    def _build_env_fingerprint(self, file_summaries: list[dict[str, Any]]) -> str | None:
        if not file_summaries:
            return None
        payload = "|".join(
            f"{item['source']}:{item['path']}:{item['file_hash']}" for item in file_summaries
        )
        return self.hashing_service.hash_text(payload)

    def _decode_uploaded_content(self, content: bytes) -> str:
        return content.decode("utf-8", errors="ignore")

    def _infer_context_source(self, file_summaries: list[dict[str, Any]]) -> str:
        sources = {item.get("source", "repository") for item in file_summaries}
        if not sources:
            return "none"
        if len(sources) == 1:
            return next(iter(sources))
        return "merged"

    def _source_priority(self, source: str) -> int:
        return 2 if source == "uploaded" else 1

    def _normalize_value(self, value: str) -> str:
        cleaned = value.strip()
        if cleaned.startswith(("'", '"')) and cleaned.endswith(("'", '"')) and len(cleaned) >= 2:
            cleaned = cleaned[1:-1]
        if " #" in cleaned:
            cleaned = cleaned.split(" #", 1)[0].rstrip()
        return cleaned.strip()

    def _sanitize_value(self, name: str, value: str, is_sensitive: bool) -> str | None:
        if not value or is_sensitive:
            return None
        upper_name = name.upper()
        if upper_name in self.SAFE_VALUE_NAMES:
            return value
        if self.SAFE_LITERAL_PATTERN.match(value):
            return value
        return None

    def _is_sensitive(self, name: str) -> bool:
        upper_name = name.upper()
        return any(pattern in upper_name for pattern in self.SENSITIVE_PATTERNS)

    def _categorize(self, env_name: str) -> str:
        name = env_name.upper()
        if any(token in name for token in ("POSTGRES", "MYSQL", "MONGO", "DB_", "DATABASE", "SQLALCHEMY")):
            return "database"
        if any(token in name for token in ("REDIS", "CACHE", "MEMCACHED")):
            return "cache"
        if any(token in name for token in ("RABBIT", "QUEUE", "BROKER", "CELERY")):
            return "queue"
        if any(token in name for token in ("SECRET", "PASSWORD", "TOKEN", "KEY", "PRIVATE_KEY")):
            return "secret"
        if any(token in name for token in ("API", "WEBHOOK", "GROQ", "OPENAI", "STRIPE", "SLACK")):
            return "external_api"
        if any(token in name for token in ("HOST", "PORT", "ENV", "DEBUG", "DEPLOY", "KUBE", "LOG_LEVEL", "APP_NAME")):
            return "deployment"
        return "app"

    def _infer_service(self, source_file: str) -> str:
        lowered = source_file.lower()
        if lowered.startswith("backend/"):
            return "backend"
        if lowered.startswith("frontend/"):
            return "frontend"
        return "application"
