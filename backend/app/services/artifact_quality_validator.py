from typing import Any

from backend.app.services.infrastructure_context_mapper import InfrastructureContextMapper


class ArtifactQualityValidator:
    def __init__(self):
        self.mapper = InfrastructureContextMapper()

    def validate(
        self,
        *,
        prompt: str,
        plan: dict[str, Any],
        infra: dict[str, Any],
        infrastructure_context: dict[str, Any] | None,
        approved_artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        mapped = self.mapper.map(
            prompt=prompt,
            plan=plan,
            infrastructure_context=infrastructure_context,
            approved_artifacts=approved_artifacts,
        )
        required_artifacts = approved_artifacts or plan.get("approved_artifacts") or plan.get("required_artifacts", [])
        artifacts = infra.get("artifacts", {}) or {}
        generated_artifacts = infra.get("generated_artifacts", []) or []

        missing_artifacts = [
            artifact for artifact in required_artifacts
            if not self._is_artifact_generated(artifact, generated_artifacts)
        ]
        quality_issues = self._collect_quality_issues(mapped, artifacts, generated_artifacts)
        warnings = self._collect_warnings(mapped, artifacts)

        status = "valid"
        if missing_artifacts or quality_issues:
            status = "partial"
        if missing_artifacts and len(missing_artifacts) == len(required_artifacts or missing_artifacts):
            status = "invalid"

        return {
            "status": status,
            "required_artifacts": required_artifacts,
            "generated_artifacts": generated_artifacts,
            "missing_artifacts": missing_artifacts,
            "quality_issues": quality_issues,
            "warnings": warnings,
        }

    def _collect_quality_issues(self, mapped: dict[str, Any], artifacts: dict[str, str], generated_artifacts: list[str]) -> list[str]:
        issues = []
        env_template = mapped.get("environment_template") or []
        services = mapped.get("services") or []
        infra_dependencies = {item["name"] for item in mapped.get("infrastructure_dependencies") or []}
        artifact_targets = mapped.get("artifact_targets") or {}

        for artifact_name, content in artifacts.items():
            if not str(content or "").strip():
                issues.append(f"{artifact_name} was returned but is empty")

        if env_template and not self._has_generated_path(
            generated_artifacts,
            artifact_targets.get("env_files") or [".env.example", ".env"],
        ):
            issues.append(".env.example should be generated because environment variables were detected")
        if services and not self._has_generated_path(
            generated_artifacts,
            [artifact_targets.get("dockerfile") or "Dockerfile"],
        ):
            issues.append("Dockerfile should be generated because containerizable services were detected")
        if (len(services) > 1 or infra_dependencies) and not self._has_generated_path(
            generated_artifacts,
            [artifact_targets.get("docker_compose") or "docker-compose.yml"],
        ):
            issues.append("docker-compose.yml should be generated because multiple services or infra dependencies were detected")

        dockerfile = artifacts.get("dockerfile", "")
        if dockerfile and any(service.get("framework") == "FastAPI" for service in services) and 'python", "app.py' in dockerfile:
            issues.append("Dockerfile uses a generic python app.py command despite FastAPI detection")

        env_example = artifacts.get("env_example", "")
        if env_template:
            for item in env_template:
                if item["name"] not in env_example:
                    issues.append(f".env.example is missing detected variable {item['name']}")

        docker_compose = artifacts.get("docker_compose", "")
        if docker_compose:
            for item in env_template:
                if item["name"] in {env["name"] for env in env_template} and item["name"] not in docker_compose and item.get("service") != "application":
                    issues.append(f"docker-compose.yml does not reference detected variable {item['name']}")
            if any(secret_word in docker_compose.lower() for secret_word in ("password: postgres", "groq_api_key: gsk_")):
                issues.append("docker-compose.yml appears to contain hardcoded secrets")

        return sorted(set(issues))

    def _collect_warnings(self, mapped: dict[str, Any], artifacts: dict[str, str]) -> list[str]:
        warnings = []
        docker_compose = artifacts.get("docker_compose", "")
        if docker_compose and "example" in docker_compose.lower():
            warnings.append("docker-compose.yml still contains generic example-like placeholders")
        if not artifacts.get("dockerignore", "") and mapped.get("artifact_expectations", {}).get("needs_dockerfile"):
            warnings.append(".dockerignore was not generated alongside Dockerfile")
        return warnings

    def _is_artifact_generated(self, required_artifact: str, generated_artifacts: list[str]) -> bool:
        if required_artifact in generated_artifacts:
            return True
        if "*" in required_artifact:
            prefix = required_artifact.split("*", 1)[0]
            return any(item.startswith(prefix) for item in generated_artifacts)
        return False

    def _has_generated_path(self, generated_artifacts: list[str], candidates: list[str]) -> bool:
        normalized_generated = {item.lower() for item in generated_artifacts}
        for candidate in candidates:
            lowered = candidate.lower()
            if lowered in normalized_generated:
                return True
            if any(item.endswith(lowered) for item in normalized_generated):
                return True
        return False
