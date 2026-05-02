"""
InfrastructureAgent — Docker-only artifact generator (thin coordinator).

After the TerraformAgent / KubernetesAgent split this agent is responsible
ONLY for Docker artifacts:

    • Dockerfile
    • .dockerignore
    • docker-compose.yml  (when expected)
    • .env.example        (when expected)

Terraform HCL generation  → TerraformAgent
Kubernetes YAML generation → KubernetesAgent

All existing public surface (constructor, ``run()`` signature, return dict shape)
is preserved — no breaking changes to callers (OrchestratorAgent, etc.).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from backend.app.agents.base_agent import EnhancedBaseAgent
from backend.app.services.core.llm_service import LLMService
from backend.app.services.infrastructure.infrastructure_artifact_builder_service import (
    InfrastructureArtifactBuilderService,
)
from backend.app.services.cicd.artifact_contract_service import ArtifactContractService
from backend.app.services.infrastructure.infrastructure_context_mapper import InfrastructureContextMapper
from backend.app.services.rag.template_retrieval_service import TemplateRetrievalService
from backend.app.services.rag.rag_pipeline_service import RAGPipelineService

logger = logging.getLogger(__name__)


class InfrastructureAgent(EnhancedBaseAgent):
    """
    Generates Docker artifacts (Dockerfile, .dockerignore, docker-compose,
    .env.example) using a ReAct loop backed by LLM + RAG.

    Terraform and Kubernetes generation have been moved to TerraformAgent
    and KubernetesAgent respectively to eliminate DSL bleeding.

    Inherits from EnhancedBaseAgent — gains:
    • ``self.memory``     (AgentMemory)
    • ``self.validation`` (ValidationService)
    • ``react_loop()``    (Reasoning + Action with automatic retries)
    """

    def __init__(self, prompt_template: str):
        super().__init__(name="InfrastructureAgent", max_react_iterations=3)
        self.llm = LLMService()
        self.prompt_template = prompt_template
        self.context_mapper = InfrastructureContextMapper()
        self.artifact_builder = InfrastructureArtifactBuilderService()
        self.artifact_contract = ArtifactContractService()
        self.template_retrieval = TemplateRetrievalService()
        self._rag_pipeline = RAGPipelineService()

    # ── Public interface ──────────────────────────────────────────────────────

    def run(
        self,
        prompt: str,
        plan: Dict[str, Any],
        infrastructure_context: Optional[Dict[str, Any]] = None,
        approved_artifacts: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate Docker artifacts for the given prompt and plan.

        Returns the same dict shape as the previous implementation, plus:
        - ``react_iterations``   — number of ReAct iterations actually used.
        - ``validation_summary`` — per-artifact validation results.
        """
        # ── 1. Map context ────────────────────────────────────────────────────
        mapped_context = self.context_mapper.map(
            prompt=prompt,
            plan=plan,
            infrastructure_context=infrastructure_context,
            approved_artifacts=approved_artifacts,
        )
        fallback_artifacts = self.artifact_builder.build_fallback_artifacts(mapped_context)

        # ── 2. RAG retrieval (Qdrant → ChromaDB fallback) ─────────────────────
        artifact_keys = self._requested_artifact_keys(mapped_context)
        qdrant_result = self._rag_pipeline.retrieve_for_agent(mapped_context, artifact_keys)
        rag_result = (
            qdrant_result
            if qdrant_result.get("available")
            else self.template_retrieval.retrieve_for_context(mapped_context, artifact_keys)
        )

        # ── 3. Build compact prompt segments ─────────────────────────────────
        compact_plan = self._compact_plan(plan)
        compact_context = self._compact_mapped_context(mapped_context)
        compact_rag = self._compact_rag_result(rag_result)
        compact_fallback = self._compact_fallback_hints(fallback_artifacts)

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
Retrieved templates are guidance only — adapt to the repository.
Never copy templates blindly.
Always adapt paths, ports, commands, variables, dependencies, and build context.
Never inject real secrets.

RAG retrieval result:
{compact_rag}

Deterministic artifact hints:
{compact_fallback}

Approved artifacts to generate (Docker artifacts only):
{approved_artifacts or []}
""".strip()

        if qdrant_context_block:
            user_prompt += f"\n\nSemantic Knowledge Base Context:\n{qdrant_context_block}"

        # ── 4. ReAct loop ─────────────────────────────────────────────────────
        evaluate_fn = self._make_infra_evaluator(
            mapped_context=mapped_context,
            approved_artifacts=approved_artifacts or [],
        )

        iterations_used = [0]

        def _counted_evaluate(response: Dict[str, Any]) -> List[str]:
            iterations_used[0] += 1
            return evaluate_fn(response)

        response = self.react_loop(
            llm=self.llm,
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            evaluate_fn=_counted_evaluate,
            temperature=0.2,
            max_tokens=2200,
        )

        # ── 5. Artifact selection (generated vs. fallback) ────────────────────
        artifacts = response.setdefault("artifacts", {})
        fallback_reasons: Dict[str, str] = {}
        fallback_used = False

        expectations = mapped_context.get("artifact_expectations", {})

        if expectations.get("needs_env_example"):
            artifacts["env_example"], used, reason = self._choose_best_artifact(
                artifact_key="env_example",
                generated=artifacts.get("env_example"),
                fallback=fallback_artifacts.get("env_example", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or used
            if reason:
                fallback_reasons["env_example"] = reason

        for key in ("dockerignore", "dockerfile"):
            artifacts[key], used, reason = self._choose_best_artifact(
                artifact_key=key,
                generated=artifacts.get(key),
                fallback=fallback_artifacts.get(key, ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or used
            if reason:
                fallback_reasons[key] = reason

        if expectations.get("needs_docker_compose"):
            artifacts["docker_compose"], used, reason = self._choose_best_artifact(
                artifact_key="docker_compose",
                generated=artifacts.get("docker_compose"),
                fallback=fallback_artifacts.get("docker_compose", ""),
                rag_result=rag_result,
            )
            fallback_used = fallback_used or used
            if reason:
                fallback_reasons["docker_compose"] = reason

        # ── 6. Artifact-level validation ──────────────────────────────────────
        validation_results = self.validation.validate_artifacts(artifacts)
        validation_summary = self.validation.aggregate_validation(validation_results)

        # ── 7. Assemble response ──────────────────────────────────────────────
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
        response["react_iterations"] = iterations_used[0]
        response["validation_summary"] = validation_summary

        return response

    # ── ReAct quality evaluator ───────────────────────────────────────────────

    def _make_infra_evaluator(
        self,
        mapped_context: Dict[str, Any],
        approved_artifacts: List[str],
    ) -> Callable[[Dict[str, Any]], List[str]]:
        expectations = mapped_context.get("artifact_expectations", {})

        def evaluate(response: Dict[str, Any]) -> List[str]:
            return self._evaluate_docker_quality(response, expectations, approved_artifacts)

        return evaluate

    def _evaluate_docker_quality(
        self,
        response: Dict[str, Any],
        expectations: Dict[str, Any],
        approved_artifacts: List[str],
    ) -> List[str]:
        """
        Docker-focused quality checks.

        Terraform and Kubernetes checks have been removed — those DSLs
        are now handled by TerraformAgent and KubernetesAgent respectively.
        """
        issues: List[str] = []
        artifacts = (response or {}).get("artifacts") or {}

        issues.extend(self._default_evaluate(response))

        # Dockerfile: always required ─────────────────────────────────────────
        dockerfile = str(artifacts.get("dockerfile") or "").strip()
        if not dockerfile:
            issues.append("Artifact 'dockerfile' is missing or empty — it is always required")
        elif self.validation.is_generic_content(dockerfile):
            issues.append("Artifact 'dockerfile' appears to be generic/placeholder content")
        else:
            df_result = self.validation.validate_dockerfile(dockerfile)
            issues.extend(df_result.issues)

        # docker-compose: required when expected ──────────────────────────────
        if expectations.get("needs_docker_compose"):
            compose = str(artifacts.get("docker_compose") or "").strip()
            if not compose:
                issues.append("Artifact 'docker_compose' is missing but was expected")
            else:
                dc_result = self.validation.validate_docker_compose(compose)
                issues.extend(dc_result.issues)

        # Generic content check for all remaining Docker artifacts ────────────
        for key, content in artifacts.items():
            if key == "dockerfile":
                continue
            if content and self.validation.is_generic_content(str(content)):
                issues.append(
                    f"Artifact '{key}' appears to contain generic placeholder content"
                )

        return issues

    # ── Artifact selection helpers ────────────────────────────────────────────

    def _choose_best_artifact(
        self,
        *,
        artifact_key: str,
        generated: Optional[str],
        fallback: str,
        rag_result: Dict[str, Any],
    ) -> tuple[str, bool, Optional[str]]:
        if not str(generated or "").strip():
            return fallback, True, self._fallback_reason(artifact_key, rag_result, "empty_generation")
        if self._looks_generic(generated):  # type: ignore[arg-type]
            return fallback, True, self._fallback_reason(artifact_key, rag_result, "generic_generation")
        return generated, False, None  # type: ignore[return-value]

    def _fallback_reason(
        self,
        artifact_key: str,
        rag_result: Dict[str, Any],
        base_reason: str,
    ) -> str:
        if not rag_result.get("enabled"):
            return f"{base_reason}:rag_disabled"
        if not rag_result.get("available"):
            return f"{base_reason}:{rag_result.get('reason', 'rag_unavailable')}"
        if artifact_key not in (rag_result.get("retrievals") or {}):
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

    # ── Context / prompt helpers ──────────────────────────────────────────────

    def _requested_artifact_keys(self, mapped_context: Dict[str, Any]) -> List[str]:
        """Return Docker-scoped artifact keys only."""
        expectations = mapped_context.get("artifact_expectations") or {}
        keys = ["dockerfile", "dockerignore", "docker_compose"]
        if expectations.get("needs_env_example"):
            keys.append("env_example")
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
        }
        generated = {
            name
            for name in (generated_artifacts or [])
            if name not in key_to_file.values()
        }
        for key, file_name in key_to_file.items():
            if str(artifacts.get(key) or "").strip():
                generated.add(file_name)
        return sorted(generated)

    def _strip_uploaded_env_artifact(
        self, artifacts: Dict[str, str], mapped_context: Dict[str, Any]
    ) -> None:
        if mapped_context.get("env_source_of_truth") != "uploaded":
            return
        artifacts.pop("env_example", None)

    def _find_target_path(self, targets: List[str], filename: str) -> Optional[str]:
        return next(
            (t for t in targets if t.lower().endswith(filename.lower())), None
        )

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
                    "name": svc.get("name"),
                    "type": svc.get("type"),
                    "framework": svc.get("framework"),
                    "language": svc.get("language"),
                    "entrypoint": svc.get("entrypoint"),
                    "run_command": svc.get("run_command"),
                    "port": svc.get("port"),
                    "dependencies": svc.get("dependencies"),
                    "environment_variables": svc.get("environment_variables"),
                }
                for svc in (mapped_context.get("services") or [])[:4]
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
                "sensitive_variables_count": sanitized_env_context.get("sensitive_variables_count", 0),
                "used_for_generation_count": sanitized_env_context.get("used_for_generation_count", 0),
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
                    "command": cmd.get("command"),
                    "service": cmd.get("service"),
                    "source_file": cmd.get("source_file"),
                }
                for cmd in (mapped_context.get("commands") or [])[:8]
            ],
        }

    def _compact_rag_result(self, rag_result: Dict[str, Any]) -> Dict[str, Any]:
        compact_retrievals: Dict[str, Any] = {}
        for artifact_key, retrieval in (rag_result.get("retrievals") or {}).items():
            templates = []
            for tmpl in (retrieval.get("templates") or [])[:1]:
                templates.append(
                    {
                        "id": tmpl.get("id"),
                        "metadata": {
                            "artifact_type": (tmpl.get("metadata") or {}).get("artifact_type"),
                            "language": (tmpl.get("metadata") or {}).get("language"),
                            "framework": (tmpl.get("metadata") or {}).get("framework"),
                            "dependencies": (tmpl.get("metadata") or {}).get("dependencies"),
                            "description": (tmpl.get("metadata") or {}).get("description"),
                        },
                        "content_preview": self._truncate_text(tmpl.get("content", ""), 600),
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
