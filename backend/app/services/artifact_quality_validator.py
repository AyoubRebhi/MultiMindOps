from typing import Any
import re

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
        env_security_runtime: dict[str, Any] | None = None,
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
        rag_info = infra.get("rag") or {}

        missing_artifacts = [
            artifact for artifact in required_artifacts
            if not self._is_artifact_generated(artifact, generated_artifacts)
        ]
        quality_issues = self._collect_quality_issues(
            mapped,
            artifacts,
            generated_artifacts,
            env_security_runtime or {},
        )
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
            "generated_with_rag": bool(rag_info.get("generated_with_rag")),
            "fallback_used": bool(rag_info.get("fallback_used")),
            "template_ids_used": rag_info.get("template_ids_used", []),
        }

    def _collect_quality_issues(
        self,
        mapped: dict[str, Any],
        artifacts: dict[str, str],
        generated_artifacts: list[str],
        env_security_runtime: dict[str, Any],
    ) -> list[str]:
        issues = []
        env_template = mapped.get("environment_template") or []
        services = mapped.get("services") or []
        infra_dependencies = {item["name"] for item in mapped.get("infrastructure_dependencies") or []}
        artifact_targets = mapped.get("artifact_targets") or {}
        combined_artifact_text = "\n".join(
            str(content or "") for content in artifacts.values()
        )

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
        if dockerfile and any(service.get("framework") == "Spring Boot" for service in services) and "python" in dockerfile.lower():
            issues.append("Dockerfile is inconsistent with detected Spring Boot runtime")

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
        if "your-image:latest" in "\n".join(artifacts.values()).lower():
            issues.append("Generated artifacts still contain raw template placeholders such as your-image:latest")
        for sensitive_value in env_security_runtime.get("sensitive_values", []):
            if sensitive_value and len(sensitive_value) >= 4 and sensitive_value in combined_artifact_text:
                issues.append(
                    "A sensitive value from a detected .env file appears in generated artifacts"
                )
                break
        for item in env_template:
            if not item.get("is_sensitive"):
                continue
            pattern = f"{item['name']}="
            if pattern in artifacts.get("env_example", ""):
                line = next(
                    (
                        candidate
                        for candidate in artifacts.get("env_example", "").splitlines()
                        if candidate.startswith(pattern)
                    ),
                    "",
                )
                if line.strip() != pattern:
                    issues.append(
                        f".env.example appears to assign a concrete value to sensitive variable {item['name']}"
                    )
            if self._has_hardcoded_sensitive_assignment(
                artifacts.get("docker_compose", ""),
                item["name"],
            ):
                issues.append(
                    f"docker-compose.yml appears to hardcode sensitive variable {item['name']}"
                )
            if self._has_hardcoded_sensitive_assignment(
                artifacts.get("kubernetes_configmap", ""),
                item["name"],
            ) or self._has_hardcoded_sensitive_assignment(
                artifacts.get("kubernetes_manifests", ""),
                item["name"],
            ):
                issues.append(
                    f"Kubernetes manifests appear to expose sensitive variable {item['name']} in clear text"
                )
            if self._has_hardcoded_sensitive_assignment(
                artifacts.get("terraform_main", ""),
                item["name"],
            ) or self._has_hardcoded_sensitive_assignment(
                artifacts.get("terraform_variables", ""),
                item["name"],
            ):
                issues.append(
                    f"Terraform artifacts appear to assign a concrete value to sensitive variable {item['name']}"
                )

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

    def _has_hardcoded_sensitive_assignment(self, artifact_content: str, variable_name: str) -> bool:
        if not str(artifact_content or "").strip():
            return False

        patterns = [
            rf"^\s*{re.escape(variable_name)}\s*=\s*(.+)$",
            rf"^\s*{re.escape(variable_name)}\s*:\s*(.+)$",
            rf"^\s*-\s*{re.escape(variable_name)}\s*=\s*(.+)$",
        ]

        for line in artifact_content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for pattern in patterns:
                match = re.match(pattern, line)
                if not match:
                    continue
                assigned_value = match.group(1).strip().strip('"').strip("'")
                if not assigned_value:
                    continue
                if assigned_value in {"${" + variable_name + "}", variable_name}:
                    continue
                if "${" in assigned_value or "valueFrom:" in stripped:
                    continue
                return True

        return False
