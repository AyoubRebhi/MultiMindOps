from pathlib import Path
from typing import Any


class InfraDependencyDetectorService:
    DEPENDENCY_RULES = {
        "postgres": ("postgres", "database_url", "psycopg2", "sqlalchemy"),
        "mysql": ("mysql", "pymysql", "mysqlclient"),
        "redis": ("redis", "cache_url"),
        "rabbitmq": ("rabbitmq", "amqp", "broker_url"),
        "celery": ("celery",),
        "minio": ("minio", "s3", "bucket"),
        "elasticsearch": ("elasticsearch",),
        "nginx": ("nginx",),
    }

    def detect(
        self,
        *,
        file_tree: list[str],
        key_files_content: dict[str, str],
        environment_variables: list[dict[str, Any]],
        runtime: dict[str, Any],
        commands: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        combined_text = "\n".join(key_files_content.values()).lower()
        env_names = {item["name"].lower() for item in environment_variables}
        command_text = "\n".join(command["command"] for command in commands).lower()
        runtime_text = "\n".join(runtime.get("dependency_files", []) + runtime.get("frameworks", [])).lower()

        detections: list[dict[str, Any]] = []
        for dependency_name, keywords in self.DEPENDENCY_RULES.items():
            matched_keywords = [
                keyword
                for keyword in keywords
                if keyword in combined_text or keyword in env_names or keyword in command_text or keyword in runtime_text
            ]
            if matched_keywords:
                detections.append(
                    {
                        "name": dependency_name,
                        "type": self._dependency_type(dependency_name),
                        "confidence": "high" if len(matched_keywords) > 1 else "medium",
                        "signals": sorted(set(matched_keywords)),
                    }
                )

        if any(Path(path).name in {"Dockerfile", "docker-compose.yml", "docker-compose.yaml"} for path in file_tree):
            detections.append(
                {
                    "name": "docker_compose",
                    "type": "orchestration",
                    "confidence": "high",
                    "signals": ["existing_docker_files"],
                }
            )

        return self._deduplicate(detections)

    def _dependency_type(self, dependency_name: str) -> str:
        if dependency_name in {"postgres", "mysql"}:
            return "database"
        if dependency_name == "redis":
            return "cache"
        if dependency_name in {"rabbitmq", "celery"}:
            return "queue"
        if dependency_name == "minio":
            return "object_storage"
        if dependency_name == "elasticsearch":
            return "search"
        if dependency_name == "nginx":
            return "reverse_proxy"
        return "service"

    def _deduplicate(self, detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for detection in detections:
            existing = merged.get(detection["name"])
            if not existing:
                merged[detection["name"]] = detection
                continue
            existing["signals"] = sorted(set(existing["signals"]) | set(detection["signals"]))
            if existing["confidence"] == "medium" and detection["confidence"] == "high":
                existing["confidence"] = "high"
        return sorted(merged.values(), key=lambda item: item["name"])
