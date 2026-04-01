from typing import Any, Dict, List

from agents.base_agent import BaseAgent
from backend.app.services.llm_service import LLMService
from backend.app.services.infrastructure_artifact_builder_service import (
    InfrastructureArtifactBuilderService,
)
from backend.app.services.infrastructure_context_mapper import InfrastructureContextMapper
from backend.app.services.template_retrieval_service import TemplateRetrievalService


class InfrastructureAgent(BaseAgent):
    def __init__(self, prompt_template: str):
        super().__init__(name="InfrastructureAgent")
        self.llm = LLMService()
        self.prompt_template = prompt_template
        self.context_mapper = InfrastructureContextMapper()
        self.artifact_builder = InfrastructureArtifactBuilderService()
        self.template_retrieval = TemplateRetrievalService()

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
        rag_result = self.template_retrieval.retrieve_for_context(
            mapped_context,
            self._requested_artifact_keys(mapped_context),
        )

        user_prompt = f"""
User task:
{prompt}

Execution plan:
{plan}

Infrastructure context:
{infrastructure_context or {}}

Mapped infrastructure context:
{mapped_context}

Repository context is the source of truth.
Retrieved templates are guidance only and must be adapted to the repository.
Never copy templates blindly.
Always adapt paths, ports, commands, variables, dependencies, and build context.
Never inject real secrets.

RAG retrieval result:
{rag_result}

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
        fallback_reasons: dict[str, str] = {}
        fallback_used = False

        if mapped_context.get("artifact_expectations", {}).get("needs_env_example"):
            artifacts["env_example"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
                artifact_key="env_example",
                generated=artifacts.get("env_example"),
                fallback=fallback_artifacts.get("env_example", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or artifact_fallback_used
            if fallback_reason:
                fallback_reasons["env_example"] = fallback_reason

        artifacts["dockerignore"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
            artifact_key="dockerignore",
            generated=artifacts.get("dockerignore"),
            fallback=fallback_artifacts.get("dockerignore", ""),
            rag_result=rag_result,
        )
        fallback_used = fallback_used or artifact_fallback_used
        if fallback_reason:
            fallback_reasons["dockerignore"] = fallback_reason

        artifacts["dockerfile"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
            artifact_key="dockerfile",
            generated=artifacts.get("dockerfile"),
            fallback=fallback_artifacts.get("dockerfile", ""),
            rag_result=rag_result,
        )
        fallback_used = fallback_used or artifact_fallback_used
        if fallback_reason:
            fallback_reasons["dockerfile"] = fallback_reason

        if mapped_context.get("artifact_expectations", {}).get("needs_docker_compose"):
            artifacts["docker_compose"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
                artifact_key="docker_compose",
                generated=artifacts.get("docker_compose"),
                fallback=fallback_artifacts.get("docker_compose", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or artifact_fallback_used
            if fallback_reason:
                fallback_reasons["docker_compose"] = fallback_reason

        if mapped_context.get("artifact_expectations", {}).get("needs_kubernetes"):
            artifacts["kubernetes_manifests"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
                artifact_key="kubernetes_manifests",
                generated=artifacts.get("kubernetes_manifests"),
                fallback=fallback_artifacts.get("kubernetes_manifests", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or artifact_fallback_used
            if fallback_reason:
                fallback_reasons["kubernetes_manifests"] = fallback_reason

        if mapped_context.get("artifact_expectations", {}).get("needs_terraform"):
            artifacts["terraform_main"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
                artifact_key="terraform_main",
                generated=artifacts.get("terraform_main"),
                fallback=fallback_artifacts.get("terraform_main", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or artifact_fallback_used
            if fallback_reason:
                fallback_reasons["terraform_main"] = fallback_reason
            artifacts["terraform_variables"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
                artifact_key="terraform_variables",
                generated=artifacts.get("terraform_variables"),
                fallback=fallback_artifacts.get("terraform_variables", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or artifact_fallback_used
            if fallback_reason:
                fallback_reasons["terraform_variables"] = fallback_reason
            artifacts["terraform_outputs"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
                artifact_key="terraform_outputs",
                generated=artifacts.get("terraform_outputs"),
                fallback=fallback_artifacts.get("terraform_outputs", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or artifact_fallback_used
            if fallback_reason:
                fallback_reasons["terraform_outputs"] = fallback_reason

        response["artifacts"] = artifacts
        response["context_used"] = mapped_context
        response["rag"] = {
            **rag_result,
            "template_ids_used": rag_result.get("template_ids", []),
            "generated_with_rag": bool(rag_result.get("retrievals")),
            "fallback_used": fallback_used,
            "fallback_reasons": fallback_reasons,
        }
        response["generated_artifacts"] = self._recompute_generated_artifacts(
            response.get("generated_artifacts", []),
            artifacts,
            mapped_context,
        )
        return response

    def _choose_best_artifact(
        self,
        *,
        artifact_key: str,
        generated: str | None,
        fallback: str,
        rag_result: Dict[str, Any],
    ) -> tuple[str, bool, str | None]:
        if not str(generated or "").strip():
            return fallback, True, self._fallback_reason(artifact_key, rag_result, "empty_generation")
        if self._looks_generic(generated):
            return fallback, True, self._fallback_reason(artifact_key, rag_result, "generic_generation")
        return generated, False, None

    def _fallback_reason(
        self,
        artifact_key: str,
        rag_result: Dict[str, Any],
        base_reason: str,
    ) -> str:
        retrievals = rag_result.get("retrievals") or {}
        if not rag_result.get("enabled"):
            return f"{base_reason}:rag_disabled"
        if not rag_result.get("available"):
            return f"{base_reason}:{rag_result.get('reason', 'rag_unavailable')}"
        if artifact_key not in retrievals:
            return f"{base_reason}:no_relevant_templates"
        return f"{base_reason}:template_guidance_insufficient"

    def _looks_generic(self, content: str) -> bool:
        lowered = content.lower()
        generic_markers = [
            'cmd ["python", "app.py"]',
            "env_var=example",
            "your-image:latest",
            "lorem ipsum",
        ]
        return any(marker in lowered for marker in generic_markers)

    def _requested_artifact_keys(self, mapped_context: Dict[str, Any]) -> List[str]:
        expectations = mapped_context.get("artifact_expectations") or {}
        keys = ["dockerfile", "dockerignore", "docker_compose"]
        if expectations.get("needs_env_example"):
            keys.append("env_example")
        if expectations.get("needs_kubernetes"):
            keys.append("kubernetes_manifests")
        if expectations.get("needs_terraform"):
            keys.extend(["terraform_main", "terraform_variables", "terraform_outputs"])
        keys.append("security_notes")
        return keys

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
