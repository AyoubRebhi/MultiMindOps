from typing import Any


class InfrastructureContextMapper:
    def map(
        self,
        *,
        prompt: str,
        plan: dict[str, Any],
        infrastructure_context: dict[str, Any] | None,
        approved_artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        context = infrastructure_context or {}
        services = context.get("services") or []
        env_vars = context.get("environment_variables") or []
        runtime = context.get("runtime") or {}
        commands = context.get("commands") or []
        infra_dependencies = context.get("infrastructure_dependencies") or []
        infra_needs = context.get("infrastructure_needs") or []
        requested_artifacts = approved_artifacts or plan.get("approved_artifacts") or plan.get("required_artifacts", [])

        container_services = [
            service
            for service in services
            if service.get("type") in {"api", "web_ui", "worker", "scheduler"}
        ]
        main_service = next((service for service in container_services if service.get("name") == "backend"), None)
        if not main_service and container_services:
            main_service = container_services[0]

        env_template = self._build_env_template(env_vars, infra_dependencies)
        service_root = self._infer_service_root(main_service)
        artifact_targets = self._build_artifact_targets(requested_artifacts, service_root)

        return {
            "prompt": prompt,
            "requested_artifacts": requested_artifacts,
            "services": container_services,
            "main_service": main_service,
            "service_root": service_root,
            "build_context": service_root or ".",
            "runtime": runtime,
            "commands": commands,
            "environment_variables": env_vars,
            "environment_template": env_template,
            "infrastructure_dependencies": infra_dependencies,
            "infrastructure_needs": infra_needs,
            "artifact_targets": artifact_targets,
            "artifact_expectations": {
                "needs_env_example": bool(env_template) or bool(artifact_targets["env_files"]),
                "needs_dockerfile": bool(container_services),
                "needs_docker_compose": len(container_services) > 1 or bool(infra_dependencies),
                "needs_kubernetes": bool(artifact_targets["kubernetes"]),
                "needs_terraform": bool(artifact_targets["terraform"]),
            },
        }

    def _build_env_template(
        self,
        environment_variables: list[dict[str, Any]],
        infra_dependencies: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for item in environment_variables:
            deduped[item["name"]] = {
                "name": item["name"],
                "category": item.get("category", "app"),
                "service": item.get("service"),
                "required": item.get("required", False),
                "default": item.get("default"),
            }

        dependency_names = {item["name"] for item in infra_dependencies}
        if "postgres" in dependency_names:
            for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
                deduped.setdefault(
                    name,
                    {
                        "name": name,
                        "category": "database",
                        "service": "backend",
                        "required": False,
                        "default": None,
                    },
                )
        if "mysql" in dependency_names:
            for name in ("MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_ROOT_PASSWORD"):
                deduped.setdefault(
                    name,
                    {
                        "name": name,
                        "category": "database",
                        "service": "backend",
                        "required": False,
                        "default": None,
                    },
                )

        return sorted(deduped.values(), key=lambda item: (item["category"], item["name"]))

    def _build_artifact_targets(
        self,
        requested_artifacts: list[str],
        service_root: str | None,
    ) -> dict[str, Any]:
        dockerfile_target = next(
            (artifact for artifact in requested_artifacts if artifact.lower().endswith("dockerfile")),
            f"{service_root}/Dockerfile" if service_root else "Dockerfile",
        )
        compose_target = next(
            (
                artifact
                for artifact in requested_artifacts
                if artifact.lower().endswith(("docker-compose.yml", "docker-compose.yaml"))
            ),
            "docker-compose.yml",
        )
        env_targets = [
            artifact
            for artifact in requested_artifacts
            if artifact.lower().endswith((".env", ".env.example"))
        ]
        kubernetes_targets = [
            artifact
            for artifact in requested_artifacts
            if self._is_kubernetes_artifact(artifact)
        ]
        terraform_targets = [
            artifact
            for artifact in requested_artifacts
            if artifact.lower().startswith("terraform/") and artifact.lower().endswith(".tf")
        ]

        return {
            "dockerfile": dockerfile_target,
            "docker_compose": compose_target,
            "env_files": env_targets,
            "kubernetes": kubernetes_targets,
            "terraform": terraform_targets,
        }

    def _infer_service_root(self, main_service: dict[str, Any] | None) -> str | None:
        entrypoint = (main_service or {}).get("entrypoint") or ""
        if not entrypoint:
            return None
        normalized = entrypoint.replace("\\", "/")
        for marker in ("/src/", "/backend/", "/frontend/"):
            if marker in normalized:
                return normalized.split(marker, 1)[0] or None
        return normalized.rsplit("/", 1)[0] if "/" in normalized else None

    def _is_kubernetes_artifact(self, artifact: str) -> bool:
        lowered = artifact.lower()
        if lowered.endswith(("docker-compose.yml", "docker-compose.yaml")):
            return False
        if not lowered.endswith((".yml", ".yaml")):
            return False
        kubernetes_markers = (
            "kubernetes/",
            "k8s/",
            "deployment",
            "service",
            "ingress",
            "configmap",
            "statefulset",
        )
        return any(marker in lowered for marker in kubernetes_markers)
