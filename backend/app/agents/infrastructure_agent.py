from typing import Any, Dict, List

from backend.app.agents.base_agent import BaseAgent
from backend.app.services.core.llm_service import LLMService
from backend.app.services.infrastructure.infrastructure_artifact_builder_service import (
    InfrastructureArtifactBuilderService,
)
from backend.app.services.cicd.artifact_contract_service import ArtifactContractService
from backend.app.services.infrastructure.infrastructure_context_mapper import InfrastructureContextMapper
from backend.app.services.rag.template_retrieval_service import TemplateRetrievalService
from backend.app.services.rag.rag_pipeline_service import RAGPipelineService


class InfrastructureAgent(BaseAgent):
    def __init__(self, prompt_template: str):
        super().__init__(name="InfrastructureAgent")
        self.llm = LLMService()
        self.prompt_template = prompt_template
        self.context_mapper = InfrastructureContextMapper()
        self.artifact_builder = InfrastructureArtifactBuilderService()
        self.artifact_contract = ArtifactContractService()
        self.template_retrieval = TemplateRetrievalService()
        # Nouveau pipeline RAG sémantique (Qdrant + Ollama)
        self._rag_pipeline = RAGPipelineService()

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

        # ── RAG : essayer Qdrant d'abord, ChromaDB en fallback ───────────────
        artifact_keys = self._requested_artifact_keys(mapped_context)
        qdrant_result = self._rag_pipeline.retrieve_for_agent(mapped_context, artifact_keys)
        if qdrant_result.get("available"):
            rag_result = qdrant_result
        else:
            rag_result = self.template_retrieval.retrieve_for_context(
                mapped_context, artifact_keys
            )

        compact_plan = self._compact_plan(plan)
        compact_context = self._compact_mapped_context(mapped_context)
        compact_rag = self._compact_rag_result(rag_result)
        compact_fallback = self._compact_fallback_hints(fallback_artifacts)

        # Bloc de contexte sémantique Qdrant (si disponible)
        qdrant_context_block = ""
        if qdrant_result.get("available"):
            all_results = [
                r
                for retrieval in qdrant_result.get("retrievals", {}).values()
                for r in retrieval.get("templates", [])
            ]
            if all_results:
                qdrant_context_block = self._rag_pipeline.build_llm_prompt_with_context(
                    system_prompt="",
                    user_query=prompt,
                    rag_results=[
                        {
                            "content": t.get("content", ""),
                            "source": (t.get("metadata") or {}).get("source", ""),
                            "doc_type": (t.get("metadata") or {}).get("artifact_type", ""),
                            "score": t.get("score", 0),
                        }
                        for t in all_results[:6]
                    ],
                    max_context_chars=2000,
                )[0]

        user_prompt = f"""
User task:
{prompt}

Execution plan:
{compact_plan}

Mapped infrastructure context:
{compact_context}

Repository context is the source of truth.
Retrieved templates are guidance only and must be adapted to the repository.
Never copy templates blindly.
Always adapt paths, ports, commands, variables, dependencies, and build context.
Never inject real secrets.

RAG retrieval result:
{compact_rag}

Deterministic artifact hints:
{compact_fallback}

Approved artifacts to generate:
{approved_artifacts or []}
""".strip()

        if qdrant_context_block:
            user_prompt += f"\n\nSemantic Knowledge Base Context:\n{qdrant_context_block}"

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
            artifacts["kubernetes_deployment"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
                artifact_key="kubernetes_deployment",
                generated=artifacts.get("kubernetes_deployment"),
                fallback=fallback_artifacts.get("kubernetes_deployment", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or artifact_fallback_used
            if fallback_reason:
                fallback_reasons["kubernetes_deployment"] = fallback_reason
            artifacts["kubernetes_service"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
                artifact_key="kubernetes_service",
                generated=artifacts.get("kubernetes_service"),
                fallback=fallback_artifacts.get("kubernetes_service", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or artifact_fallback_used
            if fallback_reason:
                fallback_reasons["kubernetes_service"] = fallback_reason
            artifacts["kubernetes_configmap"], artifact_fallback_used, fallback_reason = self._choose_best_artifact(
                artifact_key="kubernetes_configmap",
                generated=artifacts.get("kubernetes_configmap"),
                fallback=fallback_artifacts.get("kubernetes_configmap", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or artifact_fallback_used
            if fallback_reason:
                fallback_reasons["kubernetes_configmap"] = fallback_reason

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
        self._strip_uploaded_env_artifact(response["artifacts"], mapped_context)
        response["context_used"] = mapped_context
        response["rag"] = {
            **compact_rag,
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
        response["requested_artifacts"] = mapped_context.get("requested_artifacts", [])
        response["artifact_targets"] = mapped_context.get("artifact_targets") or {}
        response["artifact_groups"] = self.artifact_contract.group_artifacts(
            response.get("generated_artifacts", [])
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
            keys.extend(
                [
                    "kubernetes_manifests",
                    "kubernetes_deployment",
                    "kubernetes_service",
                    "kubernetes_configmap",
                ]
            )
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
        if mapped_context.get("env_source_of_truth") == "uploaded":
            artifacts.pop("env_example", None)

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
            "kubernetes_deployment": (
                self._find_target_path(artifact_targets.get("kubernetes") or [], "deployment.yaml")
                or "kubernetes/deployment.yaml"
            ),
            "kubernetes_service": (
                self._find_target_path(artifact_targets.get("kubernetes") or [], "service.yaml")
                or "kubernetes/service.yaml"
            ),
            "kubernetes_configmap": (
                self._find_target_path(artifact_targets.get("kubernetes") or [], "configmap.yaml")
                or "kubernetes/configmap.yaml"
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

    def _strip_uploaded_env_artifact(
        self,
        artifacts: Dict[str, str],
        mapped_context: Dict[str, Any],
    ) -> None:
        if mapped_context.get("env_source_of_truth") != "uploaded":
            return
        artifacts.pop("env_example", None)

    def _find_target_path(self, targets: List[str], filename: str) -> str | None:
        return next((target for target in targets if target.lower().endswith(filename.lower())), None)

    def _compact_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "steps": (plan.get("steps") or [])[:8],
            "required_artifacts": plan.get("required_artifacts", []),
            "approved_artifacts": plan.get("approved_artifacts", []),
            "estimated_complexity": plan.get("estimated_complexity"),
        }

    def _compact_mapped_context(self, mapped_context: Dict[str, Any]) -> Dict[str, Any]:
        runtime = mapped_context.get("runtime") or {}
        sanitized_env_context = mapped_context.get("sanitized_env_context") or {}
        return {
            "project_type": mapped_context.get("project_type"),
            "build_context": mapped_context.get("build_context"),
            "service_root": mapped_context.get("service_root"),
            "artifact_targets": mapped_context.get("artifact_targets"),
            "artifact_expectations": mapped_context.get("artifact_expectations"),
            "main_service": mapped_context.get("main_service"),
            "services": [
                {
                    "name": service.get("name"),
                    "type": service.get("type"),
                    "framework": service.get("framework"),
                    "language": service.get("language"),
                    "entrypoint": service.get("entrypoint"),
                    "run_command": service.get("run_command"),
                    "port": service.get("port"),
                    "dependencies": service.get("dependencies"),
                    "environment_variables": service.get("environment_variables"),
                }
                for service in (mapped_context.get("services") or [])[:4]
            ],
            "environment_template": (mapped_context.get("environment_template") or [])[:20],
            "sanitized_env_context": {
                "env_detected": sanitized_env_context.get("env_detected", False),
                "env_fingerprint": sanitized_env_context.get("env_fingerprint"),
                "files": [
                    {
                        "path": item.get("path"),
                        "variable_count": item.get("variable_count"),
                        "sensitive_variables_count": item.get("sensitive_variables_count"),
                    }
                    for item in (sanitized_env_context.get("files") or [])[:5]
                ],
                "variable_names": (sanitized_env_context.get("variable_names") or [])[:25],
                "sensitive_variables_count": sanitized_env_context.get(
                    "sensitive_variables_count",
                    0,
                ),
                "used_for_generation_count": sanitized_env_context.get(
                    "used_for_generation_count",
                    0,
                ),
            },
            "infrastructure_dependencies": mapped_context.get("infrastructure_dependencies", []),
            "infrastructure_needs": mapped_context.get("infrastructure_needs", []),
            "runtime": {
                "languages": runtime.get("languages", []),
                "frameworks": runtime.get("frameworks", []),
                "package_managers": runtime.get("package_managers", []),
                "dependency_files": runtime.get("dependency_files", [])[:8],
                "python_version": runtime.get("python_version"),
                "java_version": runtime.get("java_version"),
                "node_version": runtime.get("node_version"),
                "system_dependencies": runtime.get("system_dependencies", [])[:5],
            },
            "commands": [
                {
                    "command": command.get("command"),
                    "service": command.get("service"),
                    "source_file": command.get("source_file"),
                }
                for command in (mapped_context.get("commands") or [])[:8]
            ],
        }

    def _compact_rag_result(self, rag_result: Dict[str, Any]) -> Dict[str, Any]:
        compact_retrievals: Dict[str, Any] = {}
        for artifact_key, retrieval in (rag_result.get("retrievals") or {}).items():
            templates = []
            for template in (retrieval.get("templates") or [])[:1]:
                templates.append(
                    {
                        "id": template.get("id"),
                        "metadata": {
                            "artifact_type": (template.get("metadata") or {}).get("artifact_type"),
                            "language": (template.get("metadata") or {}).get("language"),
                            "framework": (template.get("metadata") or {}).get("framework"),
                            "dependencies": (template.get("metadata") or {}).get("dependencies"),
                            "description": (template.get("metadata") or {}).get("description"),
                        },
                        "content_preview": self._truncate_text(
                            template.get("content", ""),
                            600,
                        ),
                    }
                )
            if templates:
                compact_retrievals[artifact_key] = templates

        return {
            "enabled": rag_result.get("enabled"),
            "available": rag_result.get("available"),
            "reason": rag_result.get("reason"),
            "template_ids": rag_result.get("template_ids", []),
            "retrievals": compact_retrievals,
        }

    def _compact_fallback_hints(self, fallback_artifacts: Dict[str, str]) -> Dict[str, Any]:
        return {
            key: {
                "available": bool(str(value or "").strip()),
                "preview": self._truncate_text(value, 220) if str(value or "").strip() else "",
            }
            for key, value in fallback_artifacts.items()
            if str(value or "").strip()
        }

    def _truncate_text(self, value: str, limit: int) -> str:
        text = (value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."
