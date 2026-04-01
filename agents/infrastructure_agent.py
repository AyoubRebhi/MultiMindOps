from typing import Any, Dict, List

from agents.base_agent import BaseAgent
from backend.app.services.llm_service import LLMService
from backend.app.services.infrastructure_artifact_builder_service import (
    InfrastructureArtifactBuilderService,
)
from backend.app.services.infrastructure_context_mapper import InfrastructureContextMapper


class InfrastructureAgent(BaseAgent):
    def __init__(self, prompt_template: str):
        super().__init__(name="InfrastructureAgent")
        self.llm = LLMService()
        self.prompt_template = prompt_template
        self.context_mapper = InfrastructureContextMapper()
        self.artifact_builder = InfrastructureArtifactBuilderService()

    def run(
        self,
        prompt: str,
        plan: Dict[str, Any],
        infrastructure_context: Dict[str, Any] | None = None,
        approved_artifacts: List[str] | None = None,
    ) -> Dict[str, Any]:
        mapped_context = self.context_mapper.map(
            prompt=prompt,
            plan=plan,
            infrastructure_context=infrastructure_context,
            approved_artifacts=approved_artifacts,
        )
        fallback_artifacts = self.artifact_builder.build_fallback_artifacts(mapped_context)

        user_prompt = f"""
User task:
{prompt}

Execution plan:
{plan}

Infrastructure context:
{infrastructure_context or {}}

Mapped infrastructure context:
{mapped_context}

Deterministic artifact hints:
{fallback_artifacts}

Approved artifacts to generate:
{approved_artifacts or []}
""".strip()

        response = self.llm.chat_json(
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=2200,
        )
        artifacts = response.setdefault("artifacts", {})

        if mapped_context.get("artifact_expectations", {}).get("needs_env_example"):
            artifacts["env_example"] = self._choose_best_artifact(
                generated=artifacts.get("env_example"),
                fallback=fallback_artifacts.get("env_example", ""),
            )

        artifacts["dockerignore"] = self._choose_best_artifact(
            generated=artifacts.get("dockerignore"),
            fallback=fallback_artifacts.get("dockerignore", ""),
        )

        artifacts["dockerfile"] = self._choose_best_artifact(
            generated=artifacts.get("dockerfile"),
            fallback=fallback_artifacts.get("dockerfile", ""),
        )

        if mapped_context.get("artifact_expectations", {}).get("needs_docker_compose"):
            artifacts["docker_compose"] = self._choose_best_artifact(
                generated=artifacts.get("docker_compose"),
                fallback=fallback_artifacts.get("docker_compose", ""),
            )

        if mapped_context.get("artifact_expectations", {}).get("needs_kubernetes"):
            artifacts["kubernetes_manifests"] = self._choose_best_artifact(
                generated=artifacts.get("kubernetes_manifests"),
                fallback=fallback_artifacts.get("kubernetes_manifests", ""),
            )

        if mapped_context.get("artifact_expectations", {}).get("needs_terraform"):
            artifacts["terraform_main"] = self._choose_best_artifact(
                generated=artifacts.get("terraform_main"),
                fallback=fallback_artifacts.get("terraform_main", ""),
            )
            artifacts["terraform_variables"] = self._choose_best_artifact(
                generated=artifacts.get("terraform_variables"),
                fallback=fallback_artifacts.get("terraform_variables", ""),
            )
            artifacts["terraform_outputs"] = self._choose_best_artifact(
                generated=artifacts.get("terraform_outputs"),
                fallback=fallback_artifacts.get("terraform_outputs", ""),
            )

        response["artifacts"] = artifacts
        response["context_used"] = mapped_context
        response["generated_artifacts"] = self._recompute_generated_artifacts(
            response.get("generated_artifacts", []),
            artifacts,
            mapped_context,
        )
        return response

    def _choose_best_artifact(self, generated: str | None, fallback: str) -> str:
        if not generated or self._looks_generic(generated):
            return fallback
        return generated

    def _looks_generic(self, content: str) -> bool:
        lowered = content.lower()
        generic_markers = [
            'cmd ["python", "app.py"]',
            "env_var=example",
            "your-image:latest",
        ]
        return any(marker in lowered for marker in generic_markers)

    def _recompute_generated_artifacts(
        self,
        generated_artifacts: List[str],
        artifacts: Dict[str, str],
        mapped_context: Dict[str, Any],
    ) -> List[str]:
        artifact_targets = mapped_context.get("artifact_targets") or {}
        key_to_file = {
            "dockerfile": artifact_targets.get("dockerfile") or "Dockerfile",
            "dockerignore": ".dockerignore",
            "docker_compose": artifact_targets.get("docker_compose") or "docker-compose.yml",
            "env_example": (
                (artifact_targets.get("env_files") or [".env.example"])[0]
                if artifact_targets.get("env_files")
                else ".env.example"
            ),
            "build_script": "scripts/build.sh",
            "deploy_script": "scripts/deploy.sh",
            "security_scan_config": ".github/workflows/security-scan.yml",
            "readme_snippet": "README_infrastructure.md",
            "kubernetes_manifests": (
                (artifact_targets.get("kubernetes") or ["kubernetes/app.yaml"])[0]
            ),
            "terraform_main": (
                self._find_target_path(artifact_targets.get("terraform") or [], "main.tf")
                or "terraform/main.tf"
            ),
            "terraform_variables": (
                self._find_target_path(artifact_targets.get("terraform") or [], "variables.tf")
                or "terraform/variables.tf"
            ),
            "terraform_outputs": (
                self._find_target_path(artifact_targets.get("terraform") or [], "output.tf")
                or self._find_target_path(artifact_targets.get("terraform") or [], "outputs.tf")
                or "terraform/output.tf"
            ),
        }
        generated = {
            artifact_name
            for artifact_name in (generated_artifacts or [])
            if artifact_name not in key_to_file.values()
        }
        for key, file_name in key_to_file.items():
            if str(artifacts.get(key) or "").strip():
                generated.add(file_name)
        return sorted(generated)

    def _find_target_path(self, targets: List[str], filename: str) -> str | None:
        return next((target for target in targets if target.lower().endswith(filename.lower())), None)
