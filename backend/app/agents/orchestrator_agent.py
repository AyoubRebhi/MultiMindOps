from pathlib import Path

from langgraph.graph import END, START, StateGraph

from backend.app.agents.base_agent import BaseAgent
from backend.app.agents.codebase_analysis_agent import CodebaseAnalysisAgent
from backend.app.agents.infrastructure_agent import InfrastructureAgent
from backend.app.agents.planner_agent import PlannerAgent
from backend.app.agents.state import OrchestratorState
from backend.app.agents import CICDAgent
from backend.app.services.cicd.artifact_contract_service import ArtifactContractService
from backend.app.services.cicd.artifact_quality_validator import ArtifactQualityValidator


class OrchestratorAgent(BaseAgent):
    def __init__(
        self,
        planner_prompt: str | None = None,
        infrastructure_prompt: str | None = None,
    ):
        super().__init__(name="OrchestratorAgent")

        prompts_dir = Path(__file__).resolve().parents[1] / "prompts"

        def _read_prompt_file(filename: str, fallback: str) -> str:
            path = prompts_dir / filename
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
            return fallback

        default_planner = (
            'You are a DevSecOps planning agent. Respond with ONLY a valid JSON object — no markdown, no prose, no code fences. '
            'The JSON must have keys: "agent" (string), "input_prompt" (string), "steps" (array of strings), '
            '"required_artifacts" (array of file path strings), "estimated_complexity" ("low"|"medium"|"high"), '
            '"reasoning_summary" (string).'
        )
        default_infrastructure = (
            'You are a DevSecOps infrastructure generation agent. Respond with ONLY a valid JSON object — no markdown, no prose, no code fences. '
            'The JSON must have an "artifacts" key (object) whose values are plain strings for each artifact: '
            '"dockerfile", "dockerignore", "docker_compose", "env_example", "terraform_main", "terraform_variables", '
            '"terraform_outputs", "kubernetes_deployment", "kubernetes_service", "kubernetes_configmap", '
            '"kubernetes_manifests", "security_notes". '
            'Also include "generated_artifacts" (array of generated keys) and "summary" (string). '
            'Only include artifacts relevant to the approved list. Never inject real secrets.'
        )

        planner_prompt = planner_prompt or _read_prompt_file(
            "planner_prompt.txt",
            default_planner,
        )
        infrastructure_prompt = infrastructure_prompt or _read_prompt_file(
            "infrastructure_prompt.txt",
            default_infrastructure,
        )

        self.planner_agent = PlannerAgent(prompt_template=planner_prompt)
        self.codebase_agent = CodebaseAnalysisAgent()
        self.infrastructure_agent = InfrastructureAgent(
            prompt_template=infrastructure_prompt
        )
        self.cicd_agent = CICDAgent()
        self.artifact_quality_validator = ArtifactQualityValidator()
        self.artifact_contract_service = ArtifactContractService()
        self.graph = self._build_graph()

    def _initialize_node(self, state: OrchestratorState) -> OrchestratorState:
        logs = list(state.get("logs", []))
        logs.append(
            {
                "step": "orchestrator",
                "message": "Workflow started",
            }
        )
        return {
            **state,
            "status": "in_progress",
            "logs": logs,
        }

    def _route_repository(self, state: OrchestratorState) -> str:
        repo_url = state.get("repo_url")
        return "analyze_repository" if repo_url else "planner"

    def _route_after_repository_analysis(self, state: OrchestratorState) -> str:
        security_result = state.get("repository_security") or {}
        if security_result.get("status") == "blocked":
            return "finalize"
        return "planner"

    def _analyze_repository_node(self, state: OrchestratorState) -> OrchestratorState:
        analysis = self.codebase_agent.run(
            repo_url=state["repo_url"],  # type: ignore[index]
            repository_visibility=state.get("repository_visibility", "public"),
            github_token=state.get("github_token"),
            uploaded_env=state.get("uploaded_env_input"),
        )

        logs = list(state.get("logs", []))
        security_result = analysis.get("security")
        repository_analysis = analysis.get("repository_analysis") or {}
        cache_status = repository_analysis.get("cache_status")

        if cache_status == "reused":
            logs.append(
                {
                    "step": "repository_registry",
                    "message": "Existing repository analysis reused from cache",
                }
            )
        elif cache_status == "recomputed_after_change":
            logs.append(
                {
                    "step": "repository_registry",
                    "message": "Repository changed since last analysis; analysis recomputed",
                }
            )
        elif cache_status == "new_analysis":
            logs.append(
                {
                    "step": "repository_registry",
                    "message": "Repository analyzed for the first time and persisted",
                }
            )

        if security_result and security_result.get("status") == "blocked":
            logs.append(
                {
                    "step": "repository_security",
                    "message": "Repository blocked by security gate",
                }
            )
            logs.append(
                {
                    "step": "codebase_analysis",
                    "message": "Repository analysis stopped after security block",
                }
            )
        elif security_result and security_result.get("status") == "safe_with_warnings":
            logs.append(
                {
                    "step": "repository_security",
                    "message": "Repository passed with warnings",
                }
            )
            logs.append(
                {
                    "step": "codebase_analysis",
                    "message": "Repository analyzed successfully",
                }
            )
        else:
            logs.append(
                {
                    "step": "repository_security",
                    "message": "Repository passed security checks",
                }
            )
            logs.append(
                {
                    "step": "codebase_analysis",
                    "message": "Repository analyzed successfully",
                }
            )

        return {
            **state,
            "repository_security": security_result,
            "repository_analysis": repository_analysis,
            "repo_summary": analysis.get("repo_summary"),
            "file_tree": analysis.get("file_tree"),
            "important_files": analysis.get("important_files"),
            "key_entrypoints": analysis.get("key_entrypoints"),
            "categorized_files": analysis.get("categorized_files"),
            "chunks": analysis.get("chunks"),
            "agent_context": analysis.get("agent_context"),
            "env_security_runtime": analysis.get("env_security_runtime"),
            "logs": logs,
        }

    def _planner_node(self, state: OrchestratorState) -> OrchestratorState:
        planner_context = (state.get("agent_context") or {}).get("planner_context")
        plan = self.planner_agent.run(state["prompt"], planner_context)

        logs = list(state.get("logs", []))
        logs.append(
            {
                "step": "planner",
                "message": "Plan generated successfully",
            }
        )

        return {
            **state,
            "plan": plan,
            "logs": logs,
        }

    def _infrastructure_node(self, state: OrchestratorState) -> OrchestratorState:
        infrastructure_context = (state.get("agent_context") or {}).get(
            "infrastructure_context"
        )

        infra = self.infrastructure_agent.run(
            prompt=state["prompt"],
            plan=state["plan"],  # type: ignore[index]
            infrastructure_context=infrastructure_context,
            approved_artifacts=state.get("approved_artifacts"),
        )

        logs = list(state.get("logs", []))
        logs.append(
            {
                "step": "infrastructure",
                "message": "Infrastructure artifacts generated",
            }
        )
        rag_info = infra.get("rag") or {}
        if rag_info:
            logs.append(
                {
                    "step": "rag",
                    "message": (
                        "RAG "
                        + ("enabled" if rag_info.get("enabled") else "disabled")
                        + f"; templates used: {len(rag_info.get('template_ids_used', []))}; "
                        + (
                            "fallback triggered"
                            if rag_info.get("fallback_used")
                            else "no fallback needed"
                        )
                    ),
                }
            )

        return {
            **state,
            "infra": infra,
            "logs": logs,
        }

    def _filter_generated_artifacts(self, state: OrchestratorState) -> OrchestratorState:
        approved = set(state.get("approved_artifacts") or [])
        infra = state.get("infra") or {}
        artifact_targets = ((infra.get("context_used") or {}).get("artifact_targets") or {})
        context_used = (infra.get("context_used") or {})
        uploaded_env_paths = set(context_used.get("resolved_env_artifact_paths") or [])
        env_source_of_truth = context_used.get("env_source_of_truth")

        artifacts = infra.get("artifacts", {})

        artifact_key_to_file = {
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
            "test_script": "scripts/test.sh",
            "security_scan_config": ".github/workflows/security-scan.yml",
            "readme_snippet": "README_infrastructure.md",
            "kubernetes_manifests": (
                (artifact_targets.get("kubernetes") or ["kubernetes/app.yaml"])[0]
            ),
            "kubernetes_deployment": self._find_target_path(
                artifact_targets.get("kubernetes") or [],
                "deployment.yaml",
            )
            or "kubernetes/deployment.yaml",
            "kubernetes_service": self._find_target_path(
                artifact_targets.get("kubernetes") or [],
                "service.yaml",
            )
            or "kubernetes/service.yaml",
            "kubernetes_configmap": self._find_target_path(
                artifact_targets.get("kubernetes") or [],
                "configmap.yaml",
            )
            or "kubernetes/configmap.yaml",
            "terraform_main": self._find_target_path(
                artifact_targets.get("terraform") or [],
                "main.tf",
            )
            or "terraform/main.tf",
            "terraform_variables": self._find_target_path(
                artifact_targets.get("terraform") or [],
                "variables.tf",
            )
            or "terraform/variables.tf",
            "terraform_outputs": self._find_target_path(
                artifact_targets.get("terraform") or [],
                "output.tf",
            )
            or self._find_target_path(
                artifact_targets.get("terraform") or [],
                "outputs.tf",
            )
            or "terraform/output.tf",
        }

        filtered_artifacts = {}
        filtered_generated = []

        for key, content in artifacts.items():
            file_name = artifact_key_to_file.get(key)
            if (
                file_name
                and str(content or "").strip()
                and not (env_source_of_truth == "uploaded" and file_name in uploaded_env_paths)
                and self._artifact_matches_requested(file_name, approved)
            ):
                filtered_artifacts[key] = content
                filtered_generated.append(file_name)

        # si le LLM a déclaré generated_artifacts, on peut aussi intersecter proprement
        filtered_generated = sorted(
            file_name
            for file_name in set(filtered_generated)
            if not (env_source_of_truth == "uploaded" and file_name in uploaded_env_paths)
            if self._artifact_matches_requested(file_name, approved)
        )

        infra["artifacts"] = filtered_artifacts
        infra["generated_artifacts"] = filtered_generated

        logs = list(state.get("logs", []))
        logs.append(
            {
                "step": "artifact_filtering",
                "message": f"{len(filtered_generated)} artifacts kept after filtering",
            }
        )

        return {
            **state,
            "infra": infra,
            "logs": logs,
        }

    def _artifact_validation_node(self, state: OrchestratorState) -> OrchestratorState:
        plan = state.get("plan") or {}
        infra = state.get("infra") or {}
        infrastructure_context = (state.get("agent_context") or {}).get(
            "infrastructure_context"
        )
        validation = self.artifact_quality_validator.validate(
            prompt=state["prompt"],
            plan=plan,
            infra=infra,
            infrastructure_context=infrastructure_context,
            approved_artifacts=state.get("approved_artifacts"),
            env_security_runtime=state.get("env_security_runtime"),
        )

        logs = list(state.get("logs", []))
        if validation.get("missing_artifacts"):
            logs.append(
                {
                    "step": "artifact_validation",
                    "message": "Missing artifacts detected: "
                    + ", ".join(validation["missing_artifacts"]),
                }
            )
        if validation.get("quality_issues"):
            logs.append(
                {
                    "step": "artifact_validation",
                    "message": "Artifact quality issues detected: "
                    + "; ".join(validation["quality_issues"]),
                }
            )
        if not validation.get("missing_artifacts") and not validation.get(
            "quality_issues"
        ):
            logs.append(
                {
                    "step": "artifact_validation",
                    "message": "All required artifacts were generated successfully",
                }
            )

        return {
            **state,
            "validation": validation,
            "logs": logs,
        }

    def _cicd_node(self, state: OrchestratorState) -> OrchestratorState:
        plan = state.get("plan") or {}
        infra = state.get("infra") or {}
        validation = state.get("validation") or {}
        categorized_files = state.get("categorized_files") or {}

        base_contract = self.artifact_contract_service.build_contract(
            repo_summary=state.get("repo_summary"),
            categorized_files=categorized_files,
            key_entrypoints=state.get("key_entrypoints"),
            plan=plan,
            infrastructure=infra,
            validation=validation,
        )

        cicd_handoff = {
            "repo_url": (
                (((state.get("repository_analysis") or {}).get("identity") or {}).get("normalized_url"))
                or state.get("repo_url")
            ),
            "repository_visibility": state.get("repository_visibility") or "public",
            "branch": (
                (((state.get("repository_analysis") or {}).get("identity") or {}).get("branch"))
                or "main"
            ),
            "repo_summary": state.get("repo_summary") or {},
            "categorized_files": categorized_files,
            "ci_cd_files": categorized_files.get("ci_cd_files") or [],
            "deployment_files": categorized_files.get("deployment_files") or [],
            "key_entrypoints": state.get("key_entrypoints") or [],
            "artifact_groups": base_contract.get("artifact_groups") or {},
            "artifact_targets": base_contract.get("artifact_targets") or {},
            "requested_artifacts": (
                state.get("approved_artifacts")
                or plan.get("approved_artifacts")
                or plan.get("required_artifacts")
                or []
            ),
            "artifact_statuses": base_contract.get("artifact_statuses") or [],
            "execution_policy": base_contract.get("execution_policy") or {},
            "prototype_scope": base_contract.get("prototype_scope") or "artifact_generation_only",
        }

        cicd = self.cicd_agent.run(
            handoff_context=cicd_handoff,
            github_token=state.get("github_token"),
        )
        verified_categorized_files = dict(categorized_files)
        verified_categorized_files["ci_cd_files"] = (
            ((cicd.get("handoff_context") or {}).get("ci_cd_files")) or []
        )

        logs = list(state.get("logs", []))
        logs.append(
            {
                "step": "cicd",
                "message": "CI/CD artifacts evaluated",
            }
        )
        cicd_validation = cicd.get("validation") or {}
        if cicd_validation.get("status"):
            logs.append(
                {
                    "step": "cicd_validation",
                    "message": (
                        f"CICD validation status: {cicd_validation.get('status')}"
                    ),
                }
            )

        return {
            **state,
            "cicd": cicd,
            "categorized_files": verified_categorized_files,
            "logs": logs,
        }

    def _artifact_matches_requested(
        self, generated_artifact: str, requested_artifacts: set[str]
    ) -> bool:
        if not requested_artifacts:
            return True
        for requested_artifact in requested_artifacts:
            if requested_artifact == generated_artifact:
                return True
            if "*" in requested_artifact:
                prefix = requested_artifact.split("*", 1)[0]
                if generated_artifact.startswith(prefix):
                    return True
        return False

    def _find_target_path(self, targets: list[str], filename: str) -> str | None:
        return next((target for target in targets if target.lower().endswith(filename.lower())), None)

    def _finalize_node(self, state: OrchestratorState) -> OrchestratorState:
        logs = list(state.get("logs", []))
        logs.append(
            {
                "step": "completed",
                "message": "Workflow completed successfully",
            }
        )

        infra_validation = state.get("validation") or {}
        cicd = state.get("cicd") or {}
        cicd_validation = cicd.get("validation") or {}
        security_result = state.get("repository_security") or {}

        merged_requested = sorted(
            set(
                (state.get("approved_artifacts") or [])
                or ((state.get("plan") or {}).get("approved_artifacts") or [])
                or ((state.get("plan") or {}).get("required_artifacts") or [])
            )
            | set(cicd.get("requested_artifacts") or [])
        )
        merged_targets = self._merge_artifact_targets(
            (((state.get("infra") or {}).get("context_used") or {}).get("artifact_targets") or {}),
            cicd.get("artifact_targets") or {},
        )
        merged_statuses = (
            (infra_validation.get("artifact_statuses") or [])
            + (cicd.get("artifact_statuses") or [])
        )
        final_contract = self.artifact_contract_service.build_contract(
            repo_summary=state.get("repo_summary"),
            categorized_files=state.get("categorized_files"),
            key_entrypoints=state.get("key_entrypoints"),
            plan=state.get("plan"),
            infrastructure={
                "generated_artifacts": sorted(
                    set((state.get("infra") or {}).get("generated_artifacts") or [])
                    | set(cicd.get("generated_artifacts") or [])
                ),
                "artifacts": (state.get("infra") or {}).get("artifacts") or {},
                "context_used": {
                    "requested_artifacts": merged_requested,
                    "artifact_targets": merged_targets,
                },
            },
            validation={
                "required_artifacts": merged_requested,
            },
            artifact_statuses=merged_statuses,
            artifact_targets=merged_targets,
            requested_artifacts=merged_requested,
        )
        final_validation = self._build_final_validation(
            infra_validation=infra_validation,
            cicd_validation=cicd_validation,
            final_contract=final_contract,
        )

        final_status = "completed"
        result_status = "success"

        if security_result.get("status") == "blocked":
            final_status = "blocked"
            result_status = "blocked"
        elif final_validation.get("status") == "invalid":
            final_status = "invalid"
            result_status = "invalid"
        elif final_validation.get("status") == "partial":
            final_status = "partial_success"
            result_status = "partial_success"

        result = {
            "agent": self.name,
            "status": result_status,
            "prototype_scope": "artifact_generation_only",
            "execution_policy": self.artifact_contract_service.default_execution_policy(),
            "repository_security": security_result,
            "repository_analysis": state.get("repository_analysis"),
            "repo_summary": final_contract["handoff_context"]["repo_summary"],
            "categorized_files": final_contract["handoff_context"]["categorized_files"],
            "key_entrypoints": state.get("key_entrypoints"),
            "plan": state.get("plan"),
            "infrastructure": state.get("infra"),
            "cicd": cicd,
            "validation": final_validation,
        }
        result["artifact_contract"] = final_contract

        return {
            **state,
            "status": final_status,
            "result": result,
            "logs": logs,
        }

    def _build_final_validation(
        self,
        *,
        infra_validation: dict,
        cicd_validation: dict,
        final_contract: dict,
    ) -> dict:
        quality_issues = sorted(
            set(infra_validation.get("quality_issues") or [])
            | set(cicd_validation.get("issues") or [])
        )
        warnings = sorted(
            set(infra_validation.get("warnings") or [])
            | set(cicd_validation.get("warnings") or [])
        )
        required_artifacts = final_contract.get("required_artifacts") or []
        missing_artifacts = final_contract.get("missing_artifacts") or []

        status = "valid"
        if missing_artifacts or quality_issues:
            status = "partial"
        if required_artifacts and len(missing_artifacts) == len(required_artifacts):
            status = "invalid"

        return {
            "status": status,
            "required_artifacts": required_artifacts,
            "requested_artifacts": final_contract.get("requested_artifacts") or [],
            "generated_artifacts": final_contract.get("generated_artifacts") or [],
            "missing_artifacts": missing_artifacts,
            "quality_issues": quality_issues,
            "warnings": warnings,
            "artifact_groups": final_contract.get("artifact_groups") or {},
            "artifact_group_status": final_contract.get("artifact_group_status") or {},
            "artifact_statuses": final_contract.get("artifact_statuses") or [],
            "artifact_family_statuses": final_contract.get("artifact_family_statuses") or [],
            "generated_with_rag": bool(infra_validation.get("generated_with_rag")),
            "fallback_used": bool(infra_validation.get("fallback_used")),
            "template_ids_used": infra_validation.get("template_ids_used", []),
        }

    def _merge_artifact_targets(self, left: dict, right: dict) -> dict:
        merged = self.artifact_contract_service.normalize_artifact_targets(left or {})
        right = self.artifact_contract_service.normalize_artifact_targets(right or {})
        for key, value in right.items():
            if key not in merged:
                merged[key] = value
                continue
            if isinstance(merged[key], list) and isinstance(value, list):
                merged[key] = sorted(set(merged[key]) | set(value))
            elif not merged[key]:
                merged[key] = value
        return merged

    def _build_graph(self):
        workflow = StateGraph(OrchestratorState)

        workflow.add_node("initialize", self._initialize_node)
        workflow.add_node("analyze_repository", self._analyze_repository_node)
        workflow.add_node("planner", self._planner_node)
        workflow.add_node("infrastructure", self._infrastructure_node)
        workflow.add_node("artifact_validation", self._artifact_validation_node)
        workflow.add_node("cicd", self._cicd_node)
        workflow.add_node("finalize", self._finalize_node)

        workflow.add_edge(START, "initialize")

        workflow.add_conditional_edges(
            "initialize",
            self._route_repository,
            {
                "analyze_repository": "analyze_repository",
                "planner": "planner",
            },
        )

        workflow.add_conditional_edges(
            "analyze_repository",
            self._route_after_repository_analysis,
            {
                "planner": "planner",
                "finalize": "finalize",
            },
        )

        workflow.add_edge("planner", "infrastructure")
        workflow.add_edge("infrastructure", "artifact_validation")
        workflow.add_edge("artifact_validation", "cicd")
        workflow.add_edge("cicd", "finalize")
        workflow.add_edge("finalize", END)

        return workflow.compile()

    def run(
        self,
        prompt: str,
        repo_url: str | None = None,
        repository_visibility: str = "public",
        github_token: str | None = None,
        uploaded_env_input: dict | None = None,
    ) -> dict:
        initial_state: OrchestratorState = {
            "prompt": prompt,
            "repo_url": repo_url,
            "repository_visibility": repository_visibility,
            "github_token": github_token,
            "uploaded_env_input": uploaded_env_input,
            "status": "pending",
            "logs": [],
            "repository_security": None,
            "repository_analysis": None,
            "repo_summary": None,
            "file_tree": None,
            "important_files": None,
            "agent_context": None,
            "env_security_runtime": None,
            "plan": None,
            "infra": None,
            "cicd": None,
            "validation": None,
            "result": None,
            "error_message": None,
        }
        return self.graph.invoke(initial_state)
    
    def run_plan_preview(
        self,
        prompt: str,
        repo_url: str | None = None,
        repository_visibility: str = "public",
        github_token: str | None = None,
        uploaded_env_input: dict | None = None,
    ) -> dict:
        state: OrchestratorState = {
            "prompt": prompt,
            "repo_url": repo_url,
            "repository_visibility": repository_visibility,
            "github_token": github_token,
            "uploaded_env_input": uploaded_env_input,
            "approved_artifacts": None,
            "status": "pending",
            "logs": [],
            "repository_security": None,
            "repository_analysis": None,
            "repo_summary": None,
            "file_tree": None,
            "important_files": None,
            "agent_context": None,
            "env_security_runtime": None,
            "plan": None,
            "infra": None,
            "cicd": None,
            "validation": None,
            "result": None,
            "error_message": None,
        }

        state = self._initialize_node(state)

        if repo_url:
            state = self._analyze_repository_node(state)
            security_result = state.get("repository_security") or {}
            if security_result.get("status") == "blocked":
                state["status"] = "blocked"
                return state

        state = self._planner_node(state)
        state["status"] = "awaiting_user_review"
        state["logs"] = list(state.get("logs", [])) + [
            {
                "step": "awaiting_user_review",
                "message": "Waiting for user approval of required artifacts",
            }
        ]
        return state

    def run_generation(
        self,
        prompt: str,
        approved_artifacts: list[str],
        repo_url: str | None = None,
        repository_visibility: str = "public",
        github_token: str | None = None,
        uploaded_env_input: dict | None = None,
    ) -> dict:
        preview_state = self.run_plan_preview(
            prompt=prompt,
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
            uploaded_env_input=uploaded_env_input,
        )

        if preview_state.get("status") == "blocked":
            return preview_state

        preview_state["approved_artifacts"] = approved_artifacts

        plan = preview_state.get("plan") or {}
        plan["approved_artifacts"] = approved_artifacts
        preview_state["plan"] = plan

        preview_state = self._infrastructure_node(preview_state)
        preview_state = self._filter_generated_artifacts(preview_state)
        preview_state = self._artifact_validation_node(preview_state)
        preview_state = self._cicd_node(preview_state)
        preview_state = self._finalize_node(preview_state)

        return preview_state
