"""
OrchestratorAgent — LangGraph-based multi-agent workflow coordinator.

Generation pipeline (after plan selection)
-------------------------------------------
Step 3  docker_phase      InfrastructureAgent  → Dockerfile, .dockerignore, docker-compose
Step 4  terraform_phase   TerraformAgent       → providers.tf, vpc.tf, eks.tf, outputs.tf …
Step 5  kubernetes_phase  KubernetesAgent      → deployment.yaml, service.yaml
                          (inputs terraform_outputs from step 4 — no hardcoded values)
Step 6  security_scan     Trivy placeholder    → security_notes (expandable)
Step 7  cicd              CICDAgent            → GitHub Actions workflows
Step 8  finalize          aggregate result

Graph topology (unchanged externally — generation_phase entry point preserved)
-------------------------------------------------------------------------------
START → initialize
      ├─ (repo_url?) → analyze_repository → planning_phase
      └─ (no url)   → planning_phase
planning_phase → human_validation → cost_estimation → multi_plan_phase
multi_plan_phase → plan_selection (interactive) | generation_phase (auto)
plan_selection  → generation_phase | finalize
generation_phase (docker) → terraform_phase → kubernetes_phase → security_scan_phase
  → validation_phase → cicd → finalize → END

All existing execution-mode methods are preserved:
  run(), run_plan_preview(), run_generation(),
  run_until_plan_selection(), resume_with_plan(), resume_with_human_decision()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from langgraph.graph import END, START, StateGraph

from backend.app.agents.architecture_decision_agent import ArchitectureDecisionAgent
from backend.app.agents.base_agent import BaseAgent
from backend.app.agents.codebase_analysis_agent import CodebaseAnalysisAgent
from backend.app.agents.cost_estimation_agent import CostEstimationAgent
from backend.app.agents.infrastructure_agent import InfrastructureAgent
from backend.app.agents.terraform_agent import TerraformAgent
from backend.app.agents.kubernetes_agent import KubernetesAgent
from backend.app.agents.multi_plan_agent import MultiPlanAgent
from backend.app.agents.planner_agent import PlannerAgent
from backend.app.agents.state import OrchestratorState
from backend.app.agents import CICDAgent
from backend.app.services.cicd.artifact_contract_service import ArtifactContractService
from backend.app.services.cicd.artifact_quality_validator import ArtifactQualityValidator
from backend.app.services.security.security_score_transformer import SecurityScoreTransformer

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """
    Adaptive multi-agent orchestrator.

    Generation sub-graph (new)
    --------------------------
    generation_phase → terraform_phase → kubernetes_phase
      → security_scan_phase → validation_phase → cicd → finalize
    """

    def __init__(
        self,
        planner_prompt: str | None = None,
        infrastructure_prompt: str | None = None,
    ):
        super().__init__(name="OrchestratorAgent")

        prompts_dir = Path(__file__).resolve().parents[1] / "prompts"

        def _read(filename: str, fallback: str) -> str:
            path = prompts_dir / filename
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
            return fallback

        default_planner = (
            "You are an infrastructure-first DevSecOps planning agent. "
            "Planning priority: Infrastructure → Deployment → CI/CD. Never generate CI/CD-only plans. "
            "ALWAYS include Terraform for infrastructure provisioning. "
            "Include Kubernetes manifests for microservices or scalable applications. "
            "GitHub Actions is used ONLY for automation, not as the primary output. "
            "Respond with ONLY a valid JSON object — no markdown, no prose, no code fences. "
            'The JSON must have keys: "agent" (string), "input_prompt" (string), '
            '"steps" (array of strings following this order: 1.Define Terraform infrastructure, '
            '2.Create Dockerfile, 3.Build container image, 4.Define Kubernetes manifests, '
            '5.Configure GitHub Actions CI/CD, 6.Deploy infrastructure and application), '
            '"required_artifacts" (array of file path strings — MUST include terraform/providers.tf '
            'and Dockerfile; include kubernetes/deployment.yaml for microservices), '
            '"estimated_complexity" ("low"|"medium"|"high"), '
            '"reasoning_summary" (string — MUST explain why Terraform is used and why '
            'Kubernetes is or is not chosen based on the application architecture).'
        )
        # Docker-only system prompt — Terraform and K8s handled by specialist agents
        default_infrastructure = (
            "You are a Docker artifact generation agent. Respond with ONLY a valid JSON "
            "object — no markdown, no prose, no code fences. "
            'The JSON must have an "artifacts" key (object) whose values are plain strings: '
            '"dockerfile", "dockerignore", "docker_compose", "env_example", "security_notes". '
            'Also include "generated_artifacts" (array of generated keys) and "summary" (string). '
            "Only include Docker artifacts — Terraform HCL and Kubernetes YAML are handled "
            "by specialist agents. Never inject real secrets."
        )

        planner_prompt = planner_prompt or _read("planner_prompt.txt", default_planner)
        infrastructure_prompt = infrastructure_prompt or _read(
            "infrastructure_prompt.txt", default_infrastructure
        )

        self.planner_agent = PlannerAgent(prompt_template=planner_prompt)
        self.codebase_agent = CodebaseAnalysisAgent()
        self.infrastructure_agent = InfrastructureAgent(prompt_template=infrastructure_prompt)
        self.terraform_agent = TerraformAgent(
            prompt_template=_read("terraform_prompt.txt", "")  # falls back to agent default
        )
        self.kubernetes_agent = KubernetesAgent(
            prompt_template=_read("kubernetes_prompt.txt", "")  # falls back to agent default
        )
        self.cicd_agent = CICDAgent()
        self.cost_estimation_agent = CostEstimationAgent()
        self.architecture_decision_agent = ArchitectureDecisionAgent(
            planner_agent=self.planner_agent,
            cost_agent=self.cost_estimation_agent,
        )
        self.multi_plan_agent = MultiPlanAgent()
        self.artifact_quality_validator = ArtifactQualityValidator()
        self.artifact_contract_service = ArtifactContractService()
        self.graph = self._build_graph()

    # ═══════════════════════════════════════════════════════════════════════════
    # Graph nodes — unchanged
    # ═══════════════════════════════════════════════════════════════════════════

    def _initialize_node(self, state: OrchestratorState) -> OrchestratorState:
        logs = list(state.get("logs", []))
        logs.append({"step": "orchestrator", "message": "Workflow started"})
        return {**state, "status": "in_progress", "logs": logs}

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

        _cache_msgs = {
            "reused": "Existing repository analysis reused from cache",
            "recomputed_after_change": "Repository changed since last analysis; recomputed",
            "new_analysis": "Repository analyzed for the first time and persisted",
        }
        if cache_status in _cache_msgs:
            logs.append({"step": "repository_registry", "message": _cache_msgs[cache_status]})

        if security_result and security_result.get("status") == "blocked":
            logs.append({"step": "repository_security", "message": "Repository blocked by security gate"})
            logs.append({"step": "codebase_analysis", "message": "Analysis stopped after security block"})
        else:
            sec_msg = (
                "Repository passed with warnings"
                if (security_result or {}).get("status") == "safe_with_warnings"
                else "Repository passed security checks"
            )
            logs.append({"step": "repository_security", "message": sec_msg})
            logs.append({"step": "codebase_analysis", "message": "Repository analyzed successfully"})

        application_profile = analysis.get("application_profile")
        cache_status = (analysis.get("repository_analysis") or {}).get("cache_status", "fresh")

        if application_profile is None:
            logger.error(
                "[OrchestratorAgent] application_profile key absent from analysis output (cache_status=%s)",
                cache_status,
            )
            raise Exception("Application profiling failed: key missing from analysis output")

        if not application_profile:
            logger.error(
                "[OrchestratorAgent] application_profile is an empty dict (cache_status=%s)",
                cache_status,
            )
            raise Exception("Application profiling failed: empty profile returned")

        logger.info(
            "[OrchestratorAgent] application_profile extracted — type=%s scalability=%s source=%s",
            application_profile.get("application_type"),
            application_profile.get("scalability_level"),
            cache_status,
        )

        agent_context = analysis.get("agent_context") or {}
        if "application_profile" not in agent_context:
            agent_context = dict(agent_context)
            agent_context["application_profile"] = application_profile

        # CRITICAL: propagate the cloned-repo on-disk path. DockerExecutor
        # mirrors this directory into the temp build context so COPY paths
        # like ``COPY requirements-backend.txt .`` resolve. Dropping this key
        # at the orchestrator boundary was the root cause of repo_mirrored=0.
        repo_path = analysis.get("repo_path")
        if repo_path:
            logger.info("[RepoTrace] repo_path propagated: %s (orchestrator → state)", repo_path)
        else:
            logger.warning("[RepoTrace] repo_path is None from codebase_analysis output — Docker build will need to re-clone")

        return {
            **state,
            "repository_security": security_result,
            "repository_analysis": repository_analysis,
            "repo_path": repo_path,
            "repo_summary": analysis.get("repo_summary"),
            "file_tree": analysis.get("file_tree"),
            "important_files": analysis.get("important_files"),
            "key_entrypoints": analysis.get("key_entrypoints"),
            "categorized_files": analysis.get("categorized_files"),
            "chunks": analysis.get("chunks"),
            "agent_context": agent_context,
            "application_profile": application_profile,
            "env_security_runtime": analysis.get("env_security_runtime"),
            "logs": logs,
        }

    def _planner_node(self, state: OrchestratorState) -> OrchestratorState:
        """Retained for backward-compat; delegates to _planning_phase_node."""
        return self._planning_phase_node(state)

    def _planning_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        logger.info("[OrchestratorAgent] Entering planning_phase")
        agent_context = state.get("agent_context") or {}
        planner_context = dict(agent_context.get("planner_context") or {})

        application_profile = (
            state.get("application_profile")
            or agent_context.get("application_profile")
        )
        planner_context = planner_context or {}
        planner_context["application_profile"] = application_profile

        if application_profile:
            logger.info(
                "[OrchestratorAgent] application_profile injected — type=%s scalability=%s",
                application_profile.get("application_type"),
                application_profile.get("scalability_level"),
            )
        else:
            logger.warning("[OrchestratorAgent] application_profile not found in agent_context or state")

        if state.get("repo_url") and not application_profile:
            raise Exception("Application profile missing in orchestrator state")

        base_prompt = state["prompt"]
        human_feedback = (state.get("human_feedback") or "").strip()
        if human_feedback:
            effective_prompt = (
                f"{base_prompt}\n\n"
                f"User requested the following modifications to the previous plan:\n"
                f"{human_feedback}"
            )
            logger.info("[OrchestratorAgent] human_feedback injected into planner prompt")
        else:
            effective_prompt = base_prompt

        plan = self.planner_agent.run(effective_prompt, planner_context or None)

        logs = list(state.get("logs", []))
        variant = plan.get("plan_variant")
        score = plan.get("plan_score")
        if variant and score is not None:
            logs.append({
                "step": "planning_phase",
                "message": (
                    f"Multi-plan generated — selected variant '{variant}' "
                    f"(score={score:.3f})"
                ),
            })
        else:
            logs.append({"step": "planning_phase", "message": "Planning phase completed"})

        return {**state, "plan": plan, "logs": logs, "requires_user_input": True}

    def _cost_estimation_node(self, state: OrchestratorState) -> OrchestratorState:
        logger.info("[OrchestratorAgent] Entering cost_estimation")
        plan = state.get("plan") or {}
        planner_context = (state.get("agent_context") or {}).get("planner_context") or {}
        application_profile = planner_context.get("application_profile")

        try:
            result = self.cost_estimation_agent.run(
                plan=plan,
                application_profile=application_profile,
            )
            cost_estimation = result.get("cost_estimation") or {}
        except Exception as exc:
            logger.warning("[OrchestratorAgent] CostEstimationAgent failed (%s) — skipping.", exc)
            cost_estimation = {}

        logs = list(state.get("logs", []))
        monthly = cost_estimation.get("monthly_cost")
        profile = cost_estimation.get("cost_profile", "unknown")
        if monthly is not None:
            logs.append({
                "step": "cost_estimation",
                "message": f"Estimated monthly cost: ${monthly:.2f} ({profile})",
            })
        else:
            logs.append({"step": "cost_estimation", "message": "Cost estimation skipped"})

        return {**state, "cost_estimation": cost_estimation, "logs": logs}

    def _multi_plan_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        logger.info("[OrchestratorAgent] Entering multi_plan_phase")
        plan = state.get("plan") or {}
        cost_estimation = state.get("cost_estimation")
        planner_context = (state.get("agent_context") or {}).get("planner_context") or {}
        application_profile = planner_context.get("application_profile")

        result = self.multi_plan_agent.run(
            plan=plan,
            cost_estimation=cost_estimation,
            prompt=state.get("prompt", ""),
            application_profile=application_profile,
        )

        plans: list[dict] = result.get("plans") or []
        recommended: str = result.get("recommended_plan") or "balanced"

        logs = list(state.get("logs", []))
        logs.append({
            "step": "multi_plan_phase",
            "message": (
                f"{len(plans)} plan variant(s) generated — "
                f"recommended: '{recommended}'"
            ),
        })
        return {**state, "plans": plans, "logs": logs}

    def _plan_selection_node(self, state: OrchestratorState) -> OrchestratorState:
        logs = list(state.get("logs", []))
        logs.append({
            "step": "plan_selection",
            "message": "Workflow paused — awaiting user plan selection",
        })
        logger.info("[OrchestratorAgent] plan_selection node reached — workflow paused")
        return {**state, "awaiting_user_input": True, "logs": logs}

    def _human_validation_node(self, state: OrchestratorState) -> OrchestratorState:
        logs = list(state.get("logs", []))

        if state.get("auto_mode"):
            logs.append({
                "step": "human_validation",
                "message": "Auto-mode active — plan auto-approved, proceeding to execution",
            })
            logger.info("[OrchestratorAgent] human_validation: auto-approved")
            return {**state, "human_decision": "approved", "requires_user_input": False, "logs": logs}

        decision = (state.get("human_decision") or "").strip().lower()

        if not decision:
            logs.append({
                "step": "human_validation",
                "message": "Workflow paused — awaiting human plan validation via API",
            })
            logger.info("[OrchestratorAgent] human_validation: paused, no decision received")
            return {**state, "requires_user_input": True, "logs": logs}

        if decision == "approved":
            logs.append({
                "step": "human_validation",
                "message": "Plan approved by user — proceeding to execution",
            })
            logger.info("[OrchestratorAgent] human_validation: approved")
            return {**state, "requires_user_input": False, "logs": logs}

        if decision == "rejected":
            reason = (state.get("human_feedback") or "No reason provided")
            logs.append({
                "step": "human_validation",
                "message": f"Plan rejected by user. Reason: {reason}",
            })
            logger.info("[OrchestratorAgent] human_validation: rejected")
            return {**state, "status": "rejected", "requires_user_input": False, "logs": logs}

        logs.append({
            "step": "human_validation",
            "message": "Modification requested — replanning required via API",
        })
        return {**state, "status": "awaiting_replanning", "requires_user_input": True, "logs": logs}

    # ═══════════════════════════════════════════════════════════════════════════
    # Generation sub-pipeline (Step 3–6)
    # ═══════════════════════════════════════════════════════════════════════════

    def _generation_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        """Step 3 — Docker artifacts (Dockerfile, .dockerignore, docker-compose)."""
        logger.info("[OrchestratorAgent] Entering generation_phase (docker)")
        return self._infrastructure_node(state)

    def _terraform_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        """Step 4 — Terraform HCL (providers.tf, vpc.tf, eks/ecs.tf, outputs.tf …)."""
        logger.info("[OrchestratorAgent] Entering terraform_phase")

        plan = state.get("plan") or {}
        required_artifacts = plan.get("required_artifacts") or []
        approved_artifacts = state.get("approved_artifacts") or []

        # Run terraform if: planner listed terraform files, OR user approved terraform files,
        # OR neither list has any entries (run-all default).
        needs_terraform = (
            any("terraform" in str(a).lower() for a in required_artifacts)
            or any("terraform" in str(a).lower() for a in approved_artifacts)
            or (not required_artifacts and not approved_artifacts)
        )

        if not needs_terraform:
            logs = list(state.get("logs", []))
            logs.append({
                "step": "terraform_skip",
                "message": "Terraform phase skipped: not in required_artifacts or approved_artifacts."
            })
            return {**state, "logs": logs}

        infrastructure_context = (state.get("agent_context") or {}).get("infrastructure_context")

        try:
            tf_result = self.terraform_agent.run(
                prompt=state["prompt"],
                plan=plan,
                infrastructure_context=infrastructure_context,
                approved_artifacts=state.get("approved_artifacts"),
                task_id=state.get("task_id"),
            )
        except Exception as exc:
            # Surface validation failures distinctly from generation failures
            # so the frontend can route on `terraform_validation_failed` vs
            # `terraform_failed`.
            from backend.app.agents.errors import (
                TerraformGenerationError,
                TerraformValidationError,
            )
            logs = list(state.get("logs", []))
            if isinstance(exc, TerraformValidationError):
                logs.append({
                    "step": "terraform_validation_error",
                    "message": (
                        f"Terraform failed validation pipeline: {exc.message} "
                        f"(critical_security={exc.metadata.get('security_critical_count', 0)}, "
                        f"errors={exc.metadata.get('error_count', 0)})"
                    ),
                })
                state["current_phase"] = "terraform_validation_failed"  # type: ignore[index]
                # Persist the structured failure payload so the UI can render
                # per-validator findings without re-running the pipeline.
                state["terraform_validation"] = exc.metadata  # type: ignore[index]
            elif isinstance(exc, TerraformGenerationError):
                logs.append({
                    "step": "terraform_error",
                    "message": f"Terraform generation failed: {exc.message}",
                })
                state["current_phase"] = "terraform_failed"  # type: ignore[index]
            else:
                logs.append({
                    "step": "terraform_error",
                    "message": f"Terraform generation failed: {str(exc)}",
                })
                state["current_phase"] = "terraform_failed"  # type: ignore[index]
            logger.exception("[OrchestratorAgent] TerraformAgent failed")
            state["logs"] = logs
            return state

        # Merge TerraformAgent artifacts into state["infra"]["artifacts"]
        infra = dict(state.get("infra") or {})
        infra_artifacts = dict(infra.get("artifacts") or {})
        tf_artifacts = tf_result.get("artifacts") or {}
        infra_artifacts.update(tf_artifacts)
        infra["artifacts"] = infra_artifacts

        # Extend generated_artifacts list
        existing_generated = set(infra.get("generated_artifacts") or [])
        new_generated = set(tf_result.get("generated_artifacts") or [])
        infra["generated_artifacts"] = sorted(existing_generated | new_generated)

        logs = list(state.get("logs", []))
        react_iters = tf_result.get("react_iterations", 0)
        arch_type = tf_result.get("architecture_type", "unknown")
        logs.append({
            "step": "terraform",
            "message": (
                f"Terraform artifacts generated — arch={arch_type} "
                f"(ReAct iterations: {react_iters})"
            ),
        })
        rag_info = tf_result.get("rag") or {}
        if rag_info.get("available"):
            logs.append({
                "step": "terraform_rag",
                "message": (
                    f"Terraform RAG enabled — {rag_info.get('results_count', 0)} "
                    "terraform-tagged chunks retrieved"
                ),
            })

        # Store structured contract so KubernetesAgent can consume it
        terraform_outputs = tf_result.get("terraform_outputs") or {}

        # Persist render + validation metadata for the UI / debugging.
        tf_validation = tf_result.get("validation")
        tf_metadata = tf_result.get("generation_metadata")
        render_mode = tf_result.get("render_mode")
        if render_mode:
            logs.append({
                "step": "terraform_render_mode",
                "message": f"Terraform render mode: {render_mode}",
            })
        if tf_validation:
            status = tf_validation.get("status", "unknown")
            logs.append({
                "step": "terraform_validation",
                "message": (
                    f"Terraform validation: {status} "
                    f"(errors={sum(1 for i in tf_validation.get('issues', []) if i.get('severity') in ('error','critical'))}, "
                    f"warnings={sum(1 for i in tf_validation.get('issues', []) if i.get('severity') == 'warning')}, "
                    f"security={len(tf_validation.get('security_issues') or [])})"
                ),
            })

        new_state: OrchestratorState = {
            **state,
            "infra": infra,
            "terraform_outputs": terraform_outputs,
            "logs": logs,
        }
        if tf_validation is not None:
            new_state["terraform_validation"] = tf_validation  # type: ignore[index]
        if tf_metadata is not None:
            new_state["terraform_generation_metadata"] = tf_metadata  # type: ignore[index]
        return new_state

    def _kubernetes_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        """Step 5 — Kubernetes YAML (deployment.yaml, service.yaml).

        CONSUMES terraform_outputs from state — no hardcoded values allowed.
        """
        logger.info("[OrchestratorAgent] Entering kubernetes_phase")

        plan = state.get("plan") or {}
        required_artifacts = plan.get("required_artifacts") or []
        approved_artifacts = state.get("approved_artifacts") or []

        def _has_k8s(lst: list) -> bool:
            return any("kubernetes" in str(a).lower() or "k8s" in str(a).lower() for a in lst)

        needs_kubernetes = (
            _has_k8s(required_artifacts)
            or _has_k8s(approved_artifacts)
            or (not required_artifacts and not approved_artifacts)
        )

        if not needs_kubernetes:
            logs = list(state.get("logs", []))
            logs.append({
                "step": "kubernetes_skip",
                "message": "Kubernetes phase skipped: not in required_artifacts or approved_artifacts."
            })
            return {**state, "logs": logs}

        terraform_outputs = state.get("terraform_outputs") or {}
        if not terraform_outputs:
            logger.warning(
                "[OrchestratorAgent] kubernetes_phase — terraform_outputs is empty; "
                "KubernetesAgent will use symbolic references"
            )

        # Build app_config from state context
        app_config = self._build_app_config(state)

        try:
            k8s_result = self.kubernetes_agent.run(
                terraform_outputs=terraform_outputs,
                app_config=app_config,
                plan=plan,
            )
        except Exception as exc:
            logs = list(state.get("logs", []))
            logs.append({
                "step": "kubernetes_error",
                "message": f"Kubernetes generation failed: {str(exc)}. Check if the LLM returned valid JSON."
            })
            logger.error("[OrchestratorAgent] KubernetesAgent failed (%s)", exc)
            return state

        # Merge into state["infra"]["artifacts"]
        infra = dict(state.get("infra") or {})
        infra_artifacts = dict(infra.get("artifacts") or {})
        k8s_artifacts = k8s_result.get("artifacts") or {}
        infra_artifacts.update(k8s_artifacts)
        infra["artifacts"] = infra_artifacts

        existing_generated = set(infra.get("generated_artifacts") or [])
        new_generated = set(k8s_result.get("generated_artifacts") or [])
        infra["generated_artifacts"] = sorted(existing_generated | new_generated)

        logs = list(state.get("logs", []))
        react_iters = k8s_result.get("react_iterations", 0)
        logs.append({
            "step": "kubernetes",
            "message": (
                f"Kubernetes manifests generated using terraform_outputs contract "
                f"(ReAct iterations: {react_iters})"
            ),
        })

        return {**state, "infra": infra, "logs": logs}

    def _security_scan_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        """Step 6 — Security scan placeholder (Trivy image scan).

        Full Trivy integration is out of scope.  This node logs the intent
        and attaches a security_notes artifact as a placeholder so the
        contract slot is always filled and CI/CD workflows can reference it.
        """
        logger.info("[OrchestratorAgent] Entering security_scan_phase (placeholder)")
        logs = list(state.get("logs", []))

        infra = dict(state.get("infra") or {})
        artifacts = dict(infra.get("artifacts") or {})

        if not artifacts.get("security_notes"):
            artifacts["security_notes"] = (
                "# Security Scan Placeholder\n"
                "# Run: trivy image <ecr_repository_url>:latest\n"
                "# Integrate into CI/CD pipeline (see .github/workflows/)\n"
                "# Recommended: fail build on CRITICAL/HIGH severity findings\n"
            )
            infra["artifacts"] = artifacts
            logs.append({
                "step": "security_scan",
                "message": "Trivy scan placeholder added — integrate in CI/CD pipeline",
            })

        return {**state, "infra": infra, "logs": logs}

    def _validation_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        """Phase alias → artifact validation."""
        logger.info("[OrchestratorAgent] Entering validation_phase")
        return self._artifact_validation_node(state)

    def _infrastructure_node(self, state: OrchestratorState) -> OrchestratorState:
        """Docker artifact generation (InfrastructureAgent — Docker-only)."""
        infrastructure_context = (state.get("agent_context") or {}).get("infrastructure_context")
        infra = self.infrastructure_agent.run(
            prompt=state["prompt"],
            plan=state["plan"],  # type: ignore[index]
            infrastructure_context=infrastructure_context,
            approved_artifacts=state.get("approved_artifacts"),
        )

        logs = list(state.get("logs", []))
        react_iters = infra.get("react_iterations", 0)
        logs.append({
            "step": "infrastructure",
            "message": (
                f"Docker artifacts generated "
                f"(ReAct iterations used: {react_iters})"
            ),
        })

        rag_info = infra.get("rag") or {}
        if rag_info:
            logs.append({
                "step": "rag",
                "message": (
                    "RAG " + ("enabled" if rag_info.get("enabled") else "disabled")
                    + f"; templates used: {len(rag_info.get('template_ids_used', []))}; "
                    + ("fallback triggered" if rag_info.get("fallback_used") else "no fallback needed")
                ),
            })

        val_summary = infra.get("validation_summary") or {}
        if val_summary.get("issues"):
            logs.append({
                "step": "infrastructure_validation",
                "message": (
                    f"Artifact validation: {val_summary.get('status')} — "
                    f"{len(val_summary['issues'])} issue(s)"
                ),
            })

        # Phase 1: persist structured generation trace from InfrastructureAgent
        infra_gen = infra.get("infrastructure_generation")
        if infra_gen:
            blueprint_used = infra_gen.get("blueprint_used", "unknown")
            meta = infra_gen.get("generation_metadata") or {}
            logs.append({
                "step": "structured_generation",
                "message": (
                    f"[StructuredGeneration] blueprint={blueprint_used} "
                    f"sections={meta.get('generated_sections', '?')} "
                    f"fallbacks={meta.get('fallback_sections', 0)} "
                    f"rag_hits={meta.get('rag_hits', 0)} "
                    f"time={meta.get('total_time_ms', 0):.0f}ms"
                ),
            })

        updated_state: OrchestratorState = {**state, "infra": infra, "logs": logs}  # type: ignore[assignment]
        if infra_gen is not None:
            updated_state["infrastructure_generation"] = infra_gen
        return updated_state

    def _filter_generated_artifacts(self, state: OrchestratorState) -> OrchestratorState:
        approved = set(state.get("approved_artifacts") or [])
        infra = state.get("infra") or {}
        artifact_targets = ((infra.get("context_used") or {}).get("artifact_targets") or {})
        context_used = (infra.get("context_used") or {})
        uploaded_env_paths = set(context_used.get("resolved_env_artifact_paths") or [])
        env_source_of_truth = context_used.get("env_source_of_truth")

        artifacts = infra.get("artifacts", {})

        artifact_key_to_file = {
            # ── Docker artifacts ──────────────────────────────────────────────
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
            "security_notes": "security_notes.txt",
            # ── Kubernetes artifacts (from KubernetesAgent) ───────────────────
            "kubernetes_manifests": (
                (artifact_targets.get("kubernetes") or ["kubernetes/app.yaml"])[0]
            ),
            "kubernetes_deployment": self._find_target_path(
                artifact_targets.get("kubernetes") or [], "deployment.yaml"
            ) or "kubernetes/deployment.yaml",
            "kubernetes_service": self._find_target_path(
                artifact_targets.get("kubernetes") or [], "service.yaml"
            ) or "kubernetes/service.yaml",
            "kubernetes_configmap": self._find_target_path(
                artifact_targets.get("kubernetes") or [], "configmap.yaml"
            ) or "kubernetes/configmap.yaml",
            # ── Terraform artifacts (from TerraformAgent — split files) ───────
            "terraform_providers": "terraform/providers.tf",
            "terraform_backend":   "terraform/backend.tf",
            "terraform_vpc":       "terraform/vpc.tf",
            "terraform_eks":       "terraform/eks.tf",
            "terraform_ecs":       "terraform/ecs.tf",
            "terraform_tfvars":    "terraform/terraform.tfvars",
            # backward-compat keys (same file paths as before)
            "terraform_main":      "terraform/main.tf",
            "terraform_variables": "terraform/variables.tf",
            "terraform_outputs":   "terraform/outputs.tf",
        }

        filtered_artifacts: dict = {}
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

        filtered_generated = sorted(
            file_name
            for file_name in set(filtered_generated)
            if not (env_source_of_truth == "uploaded" and file_name in uploaded_env_paths)
            if self._artifact_matches_requested(file_name, approved)
        )

        infra["artifacts"] = filtered_artifacts
        infra["generated_artifacts"] = filtered_generated

        logs = list(state.get("logs", []))
        logs.append({
            "step": "artifact_filtering",
            "message": f"{len(filtered_generated)} artifacts kept after filtering",
        })

        return {**state, "infra": infra, "logs": logs}

    def _artifact_validation_node(self, state: OrchestratorState) -> OrchestratorState:
        plan = state.get("plan") or {}
        infra = state.get("infra") or {}
        infrastructure_context = (state.get("agent_context") or {}).get("infrastructure_context")
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
            logs.append({
                "step": "artifact_validation",
                "message": "Missing artifacts: " + ", ".join(validation["missing_artifacts"]),
            })
        if validation.get("quality_issues"):
            logs.append({
                "step": "artifact_validation",
                "message": "Quality issues: " + "; ".join(validation["quality_issues"]),
            })
        if not validation.get("missing_artifacts") and not validation.get("quality_issues"):
            logs.append({
                "step": "artifact_validation",
                "message": "All required artifacts generated successfully",
            })

        return {**state, "validation": validation, "logs": logs}

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
            # Pass terraform_outputs so CI/CD workflows can reference them
            "terraform_outputs": state.get("terraform_outputs") or {},
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
        logs.append({"step": "cicd", "message": "CI/CD artifacts evaluated"})
        cicd_validation = cicd.get("validation") or {}
        if cicd_validation.get("status"):
            logs.append({
                "step": "cicd_validation",
                "message": f"CICD validation status: {cicd_validation.get('status')}",
            })

        return {**state, "cicd": cicd, "categorized_files": verified_categorized_files, "logs": logs}

    def _finalize_node(self, state: OrchestratorState) -> OrchestratorState:
        logs = list(state.get("logs", []))
        logs.append({"step": "completed", "message": "Workflow completed"})

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
            validation={"required_artifacts": merged_requested},
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

        security_analysis = SecurityScoreTransformer.transform(
            repository_security=security_result,
            env_security_runtime=state.get("env_security_runtime"),
        )

        result = {
            "agent": self.name,
            "status": result_status,
            "prototype_scope": "artifact_generation_only",
            "execution_policy": self.artifact_contract_service.default_execution_policy(),
            "repository_security": security_result,
            "security": security_analysis,
            "repository_analysis": state.get("repository_analysis"),
            "repo_summary": final_contract["handoff_context"]["repo_summary"],
            "categorized_files": final_contract["handoff_context"]["categorized_files"],
            "key_entrypoints": state.get("key_entrypoints"),
            "plan": state.get("plan"),
            "infrastructure": state.get("infra"),
            "terraform_outputs": state.get("terraform_outputs"),  # expose contract
            "cicd": cicd,
            "cost_estimation": state.get("cost_estimation"),
            "validation": final_validation,
            "artifact_contract": final_contract,
        }

        return {**state, "status": final_status, "result": result, "logs": logs}

    # ═══════════════════════════════════════════════════════════════════════════
    # Dynamic routing functions (unchanged)
    # ═══════════════════════════════════════════════════════════════════════════

    def _route_repository(self, state: OrchestratorState) -> str:
        return "analyze_repository" if state.get("repo_url") else "planning_phase"

    def _route_after_repository_analysis(self, state: OrchestratorState) -> str:
        security_result = state.get("repository_security") or {}
        if security_result.get("status") == "blocked":
            return "finalize"
        return "planning_phase"

    def _route_after_multi_plan(self, state: OrchestratorState) -> str:
        logs = list(state.get("logs", []))

        if state.get("auto_mode"):
            plans = state.get("plans") or []
            first_plan_id = (plans[0].get("plan_id") if plans else None) or "plan_0"
            state["selected_plan"] = first_plan_id
            state["awaiting_user_input"] = False
            logs.append({
                "step": "dynamic_routing",
                "message": f"auto_mode — automatically selected plan '{first_plan_id}'",
            })
            state["logs"] = logs
            logger.info("[OrchestratorAgent] auto_mode: selected plan '%s'", first_plan_id)
            return "generation_phase"

        state["awaiting_user_input"] = True
        logs.append({
            "step": "dynamic_routing",
            "message": "Waiting for user to select a plan",
        })
        state["logs"] = logs
        logger.info("[OrchestratorAgent] Pausing workflow — awaiting user plan selection")
        return "plan_selection"

    def _route_after_plan_selection(self, state: OrchestratorState) -> str:
        if state.get("selected_plan"):
            logger.info(
                "[OrchestratorAgent] Plan '%s' selected — resuming to generation_phase",
                state["selected_plan"],
            )
            return "generation_phase"
        logger.info("[OrchestratorAgent] No plan selected — stopping workflow")
        return "finalize"

    def _route_after_human_validation(self, state: OrchestratorState) -> str:
        if state.get("auto_mode"):
            return "cost_estimation"

        decision = (state.get("human_decision") or "").lower()
        if decision == "approved" and not state.get("requires_user_input"):
            return "cost_estimation"

        logs = list(state.get("logs", []))
        if decision == "rejected":
            logs.append({
                "step": "dynamic_routing",
                "message": "Plan rejected — stopping pipeline",
            })
        else:
            logs.append({
                "step": "dynamic_routing",
                "message": "Human validation pending — routing to finalize (partial state)",
            })
        state["logs"] = logs
        return "finalize"

    def _route_after_planning_phase(self, state: OrchestratorState) -> str:
        plan = state.get("plan") or {}
        required_artifacts = plan.get("required_artifacts") or []
        reasoning = (plan.get("reasoning_summary") or "").strip()
        steps = plan.get("steps") or []

        logs = list(state.get("logs", []))

        if not required_artifacts and not reasoning and not steps:
            logs.append({
                "step": "dynamic_routing",
                "message": "Planner produced an empty plan — skipping generation and routing to finalize",
            })
            state["logs"] = logs
            return "finalize"

        logs.append({
            "step": "dynamic_routing",
            "message": (
                f"Planning phase produced {len(required_artifacts)} artifact(s) — "
                f"routing to cost_estimation"
            ),
        })
        state["logs"] = logs
        return "cost_estimation"

    def _route_after_validation(self, state: OrchestratorState) -> str:
        validation = state.get("validation") or {}
        status = validation.get("status", "valid")

        logs = list(state.get("logs", []))

        if status == "invalid":
            required = validation.get("required_artifacts") or []
            missing = validation.get("missing_artifacts") or []
            if required and len(missing) >= len(required):
                logs.append({
                    "step": "dynamic_routing",
                    "message": (
                        "Validation status INVALID — all required artifacts missing. "
                        "Skipping CI/CD and routing to finalize."
                    ),
                })
                state["logs"] = logs
                return "finalize"

        logs.append({
            "step": "dynamic_routing",
            "message": f"Validation status '{status}' — routing to CI/CD",
        })
        state["logs"] = logs
        return "cicd"

    # ═══════════════════════════════════════════════════════════════════════════
    # Graph construction
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_graph(self):
        workflow = StateGraph(OrchestratorState)

        # ── Nodes ────────────────────────────────────────────────────────────
        workflow.add_node("initialize",          self._initialize_node)
        workflow.add_node("analyze_repository",  self._analyze_repository_node)
        workflow.add_node("planning_phase",      self._planning_phase_node)
        workflow.add_node("human_validation",    self._human_validation_node)
        workflow.add_node("cost_estimation",     self._cost_estimation_node)
        workflow.add_node("multi_plan_phase",    self._multi_plan_phase_node)
        workflow.add_node("plan_selection",      self._plan_selection_node)
        # Generation sub-pipeline
        workflow.add_node("generation_phase",    self._generation_phase_node)    # Step 3: Docker
        workflow.add_node("terraform_phase",     self._terraform_phase_node)     # Step 4: Terraform
        workflow.add_node("kubernetes_phase",    self._kubernetes_phase_node)    # Step 5: Kubernetes
        workflow.add_node("security_scan_phase", self._security_scan_phase_node) # Step 6: Trivy placeholder
        workflow.add_node("validation_phase",    self._validation_phase_node)
        workflow.add_node("cicd",                self._cicd_node)
        workflow.add_node("finalize",            self._finalize_node)

        # ── Entry ─────────────────────────────────────────────────────────────
        workflow.add_edge(START, "initialize")

        workflow.add_conditional_edges(
            "initialize",
            self._route_repository,
            {"analyze_repository": "analyze_repository", "planning_phase": "planning_phase"},
        )
        workflow.add_conditional_edges(
            "analyze_repository",
            self._route_after_repository_analysis,
            {"planning_phase": "planning_phase", "finalize": "finalize"},
        )
        workflow.add_conditional_edges(
            "planning_phase",
            self._route_after_planning_phase,
            {"cost_estimation": "human_validation", "finalize": "finalize"},
        )
        workflow.add_conditional_edges(
            "human_validation",
            self._route_after_human_validation,
            {"cost_estimation": "cost_estimation", "finalize": "finalize"},
        )
        workflow.add_edge("cost_estimation", "multi_plan_phase")
        workflow.add_conditional_edges(
            "multi_plan_phase",
            self._route_after_multi_plan,
            {"plan_selection": "plan_selection", "generation_phase": "generation_phase"},
        )
        workflow.add_conditional_edges(
            "plan_selection",
            self._route_after_plan_selection,
            {"generation_phase": "generation_phase", "finalize": "finalize"},
        )

        # Generation sub-pipeline chain
        workflow.add_edge("generation_phase",    "terraform_phase")
        workflow.add_edge("terraform_phase",     "kubernetes_phase")
        workflow.add_edge("kubernetes_phase",    "security_scan_phase")
        workflow.add_edge("security_scan_phase", "validation_phase")

        workflow.add_conditional_edges(
            "validation_phase",
            self._route_after_validation,
            {"cicd": "cicd", "finalize": "finalize"},
        )
        workflow.add_edge("cicd",     "finalize")
        workflow.add_edge("finalize", END)

        return workflow.compile()

    # ═══════════════════════════════════════════════════════════════════════════
    # Public execution modes (all preserved for backward compat)
    # ═══════════════════════════════════════════════════════════════════════════

    def _base_state(
        self,
        prompt: str,
        repo_url: str | None = None,
        repository_visibility: str = "public",
        github_token: str | None = None,
        uploaded_env_input: dict | None = None,
        auto_mode: bool = True,
    ) -> OrchestratorState:
        return {
            "prompt": prompt,
            "repo_url": repo_url,
            "repository_visibility": repository_visibility,
            "github_token": github_token,
            "uploaded_env_input": uploaded_env_input,
            "auto_mode": auto_mode,
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
            "plans": None,
            "selected_plan": None,
            "awaiting_user_input": False,
            "infra": None,
            "terraform_outputs": None,
            "cicd": None,
            "cost_estimation": None,
            "architecture_decision": None,
            "selected_plan_id": None,
            "application_profile": None,
            "validation": None,
            "result": None,
            "error_message": None,
            "human_decision": None,
            "human_feedback": None,
            "requires_user_input": False,
        }

    def run(
        self,
        prompt: str,
        repo_url: str | None = None,
        repository_visibility: str = "public",
        github_token: str | None = None,
        uploaded_env_input: dict | None = None,
        auto_mode: bool = True,
    ) -> dict:
        initial_state = self._base_state(
            prompt=prompt,
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
            uploaded_env_input=uploaded_env_input,
            auto_mode=auto_mode,
        )
        return self.graph.invoke(initial_state)

    def run_plan_preview(
        self,
        prompt: str,
        repo_url: str | None = None,
        repository_visibility: str = "public",
        github_token: str | None = None,
        uploaded_env_input: dict | None = None,
    ) -> dict:
        state: OrchestratorState = self._base_state(
            prompt=prompt,
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
            uploaded_env_input=uploaded_env_input,
        )
        state["approved_artifacts"] = None

        state = self._initialize_node(state)

        if repo_url:
            state = self._analyze_repository_node(state)
            if (state.get("repository_security") or {}).get("status") == "blocked":
                state["status"] = "blocked"
                return state

        state = self._planning_phase_node(state)
        state = self._cost_estimation_node(state)
        state["status"] = "awaiting_user_review"
        state["logs"] = list(state.get("logs", [])) + [
            {
                "step": "awaiting_user_review",
                "message": "Waiting for user approval of required artifacts",
            }
        ]

        state["security"] = SecurityScoreTransformer.transform(
            repository_security=state.get("repository_security"),
            env_security_runtime=state.get("env_security_runtime"),
        )

        return state

    # ── NEW: Architecture Decision phase ──────────────────────────────────────

    def run_architecture_decision_phase(
        self,
        prompt: str,
        repo_url: str | None = None,
        repository_visibility: str = "public",
        github_token: str | None = None,
        uploaded_env_input: dict | None = None,
    ) -> dict:
        """
        Unified replacement for run_plan_preview.

        Runs repo analysis (if repo_url provided) then generates 1–3 deployment
        strategies — each enriched with AWS cost estimates — in one atomic phase.

        Returns state with:
          state["architecture_decision"] = { plans: [...], recommended_plan: str }
          state["current_phase"]         = "architecture_decision_complete"
          state["status"]                = "awaiting_architecture_selection"
        """
        logger.info("[OrchestratorAgent] run_architecture_decision_phase — starting")

        state: OrchestratorState = self._base_state(
            prompt=prompt,
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
            uploaded_env_input=uploaded_env_input,
        )
        state["approved_artifacts"] = None

        state = self._initialize_node(state)

        if repo_url:
            state = self._analyze_repository_node(state)
            if (state.get("repository_security") or {}).get("status") == "blocked":
                state["status"] = "blocked"
                logger.info("[OrchestratorAgent] run_architecture_decision_phase — blocked by security")
                return state

        # Build planner context from analysis results
        agent_context = state.get("agent_context") or {}
        application_profile = (
            state.get("application_profile")
            or agent_context.get("application_profile")
        )

        planner_context: dict = dict(agent_context.get("planner_context") or {})
        planner_context["application_profile"] = application_profile

        logs = list(state.get("logs", []))
        logs.append({"step": "architecture_decision", "message": "Generating architecture strategies…"})
        state["logs"] = logs

        try:
            arch_result = self.architecture_decision_agent.run(
                prompt=prompt,
                planner_context=planner_context or None,
                application_profile=application_profile,
            )
        except Exception as exc:
            logger.error("[OrchestratorAgent] ArchitectureDecisionAgent failed: %s", exc)
            raise

        # Keep a backward-compatible plan/cost_estimation in state (balanced variant)
        balanced_plan = next(
            (p for p in (arch_result.get("plans") or []) if p.get("id") == "balanced"),
            (arch_result.get("plans") or [{}])[0] if arch_result.get("plans") else {},
        )
        state["plan"] = balanced_plan.get("plan") or {}
        state["cost_estimation"] = {
            "monthly_cost":         balanced_plan.get("monthly_cost", 0.0),
            "breakdown":            balanced_plan.get("cost_breakdown") or {},
            "cost_profile":         balanced_plan.get("cost_profile", "unknown"),
            "optimization_tips":    balanced_plan.get("optimization_tips") or [],
            "assumptions":          balanced_plan.get("assumptions") or [],
            "pricing_model_version": balanced_plan.get("pricing_model_version", "aws-simplified-v1"),
        }

        state["architecture_decision"] = arch_result
        state["current_phase"] = "architecture_decision_complete"
        state["status"] = "awaiting_architecture_selection"
        state["requires_user_input"] = True

        logs = list(state.get("logs", []))
        plans_count = len(arch_result.get("plans") or [])
        logs.append({
            "step": "architecture_decision",
            "message": (
                f"{plans_count} architecture strategy/strategies generated — "
                f"recommended: '{arch_result.get('recommended_plan', 'balanced')}'"
            ),
        })
        state["logs"] = logs

        state["security"] = SecurityScoreTransformer.transform(
            repository_security=state.get("repository_security"),
            env_security_runtime=state.get("env_security_runtime"),
        )

        logger.info(
            "[OrchestratorAgent] run_architecture_decision_phase — complete (%d strategies)",
            plans_count,
        )
        return state

    def resume_with_selected_plan(
        self,
        prior_state: dict,
        selected_plan_id: str,
    ) -> dict:
        """
        Apply the user's plan selection from the architecture-decision phase.

        Sets ``state["plan"]`` and ``state["cost_estimation"]`` from the chosen
        strategy, marks ``current_phase = "planning_complete"``, and returns
        the updated state so the caller can persist it and subsequently trigger
        the Docker phase via the existing run-docker endpoint.
        """
        logger.info(
            "[OrchestratorAgent] resume_with_selected_plan — plan_id='%s'", selected_plan_id
        )

        state: OrchestratorState = dict(prior_state)  # type: ignore[assignment]

        arch_decision = state.get("architecture_decision") or {}
        plans: list[dict] = arch_decision.get("plans") or []

        selected = next(
            (p for p in plans if p.get("id") == selected_plan_id),
            None,
        )
        if not selected:
            from backend.app.agents.errors import PlanPropagationError
            available = [p.get("id") for p in plans]
            raise PlanPropagationError(
                f"Plan ID '{selected_plan_id}' not found in architecture_decision.",
                metadata={"selected_plan_id": selected_plan_id, "available": available},
            )

        # Promote selected strategy's plan + cost into top-level state fields.
        # CRITICAL: stamp strategy_tier / plan_id onto the promoted plan so
        # TerraformAgent and KubernetesAgent can read it explicitly.
        # Prior to this fix the strategy id lived only on the wrapper dict
        # and was lost here, causing multi_az to always be False and every
        # strategy to render identical Terraform.
        promoted_plan = dict(selected.get("plan") or {})
        promoted_plan["plan_id"] = selected_plan_id
        promoted_plan["strategy_tier"] = selected_plan_id

        # Propagate approved_artifacts from the strategy's required_artifacts
        # so downstream phase nodes (which gate on this list) see a
        # deterministic value instead of falling into the "neither list
        # populated → run-everything" fallback branch.
        promoted_required = list(selected.get("required_artifacts") or [])
        if promoted_required:
            promoted_plan.setdefault("required_artifacts", promoted_required)
            promoted_plan["approved_artifacts"] = promoted_required
            state["approved_artifacts"] = promoted_required

        state["plan"] = promoted_plan
        state["cost_estimation"] = {
            "monthly_cost":         selected.get("monthly_cost", 0.0),
            "breakdown":            selected.get("cost_breakdown") or {},
            "cost_profile":         selected.get("cost_profile", "unknown"),
            "optimization_tips":    selected.get("optimization_tips") or [],
            "assumptions":          selected.get("assumptions") or [],
            "pricing_model_version": selected.get("pricing_model_version", "aws-simplified-v1"),
        }
        state["selected_plan_id"] = selected_plan_id

        logs = list(state.get("logs", []))
        logs.append({
            "step": "architecture_decision",
            "message": (
                f"User selected strategy '{selected_plan_id}' "
                f"(${selected.get('monthly_cost', 0):.2f}/month) — "
                "workflow unblocked, ready for infrastructure generation"
            ),
        })
        state["logs"] = logs
        state["current_phase"] = "planning_complete"
        state["status"] = "in_progress"
        state["requires_user_input"] = False
        state["awaiting_user_input"] = False

        logger.info(
            "[OrchestratorAgent] resume_with_selected_plan — plan '%s' applied, "
            "current_phase set to 'planning_complete'",
            selected_plan_id,
        )
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
        preview_state = self._terraform_phase_node(preview_state)
        preview_state = self._kubernetes_phase_node(preview_state)
        preview_state = self._security_scan_phase_node(preview_state)
        preview_state = self._filter_generated_artifacts(preview_state)
        preview_state = self._artifact_validation_node(preview_state)

        next_step = self._route_after_validation(preview_state)
        if next_step == "cicd":
            preview_state = self._cicd_node(preview_state)

        preview_state = self._finalize_node(preview_state)
        return preview_state

    def run_until_plan_selection(
        self,
        prompt: str,
        repo_url: str | None = None,
        repository_visibility: str = "public",
        github_token: str | None = None,
        uploaded_env_input: dict | None = None,
    ) -> dict:
        logger.info("[OrchestratorAgent] run_until_plan_selection — starting")
        state: OrchestratorState = self._base_state(
            prompt=prompt,
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
            uploaded_env_input=uploaded_env_input,
            auto_mode=False,
        )

        state = self._initialize_node(state)

        if repo_url:
            state = self._analyze_repository_node(state)
            if (state.get("repository_security") or {}).get("status") == "blocked":
                state["status"] = "blocked"
                logger.info("[OrchestratorAgent] run_until_plan_selection — blocked by security")
                return state

        state = self._planning_phase_node(state)

        plan = state.get("plan") or {}
        required_artifacts = plan.get("required_artifacts") or []
        reasoning = (plan.get("reasoning_summary") or "").strip()
        steps = plan.get("steps") or []
        if not required_artifacts and not reasoning and not steps:
            state["status"] = "empty_plan"
            logger.info("[OrchestratorAgent] run_until_plan_selection — empty plan, stopping")
            return state

        state = self._cost_estimation_node(state)
        state = self._multi_plan_phase_node(state)
        state["status"] = "awaiting_plan_selection"
        state["awaiting_user_input"] = True

        state["security"] = SecurityScoreTransformer.transform(
            repository_security=state.get("repository_security"),
            env_security_runtime=state.get("env_security_runtime"),
        )

        logger.info(
            "[OrchestratorAgent] run_until_plan_selection — returning %d plan(s) for user selection",
            len(state.get("plans") or []),
        )
        return state

    def resume_with_plan(
        self,
        prior_state: dict,
        selected_plan_id: str,
        approved_artifacts: list[str] | None = None,
    ) -> dict:
        logger.info(
            "[OrchestratorAgent] resume_with_plan — selected plan '%s'", selected_plan_id
        )

        state: OrchestratorState = dict(prior_state)  # type: ignore[assignment]
        state["selected_plan"] = selected_plan_id
        state["awaiting_user_input"] = False

        plans = state.get("plans") or []
        matched = next(
            (p for p in plans if p.get("plan_id") == selected_plan_id),
            state.get("plan") or {},
        )
        if matched:
            state["plan"] = matched

        if approved_artifacts is not None:
            state["approved_artifacts"] = approved_artifacts
            plan = state.get("plan") or {}
            plan["approved_artifacts"] = approved_artifacts
            state["plan"] = plan

        logs = list(state.get("logs", []))
        logs.append({
            "step": "plan_selection",
            "message": f"User selected plan '{selected_plan_id}' — resuming workflow",
        })
        state["logs"] = logs

        state = self._generation_phase_node(state)
        state = self._terraform_phase_node(state)
        state = self._kubernetes_phase_node(state)
        state = self._security_scan_phase_node(state)
        state = self._filter_generated_artifacts(state)
        state = self._validation_phase_node(state)

        next_step = self._route_after_validation(state)
        if next_step == "cicd":
            state = self._cicd_node(state)

        state = self._finalize_node(state)
        return state

    def resume_with_human_decision(
        self,
        prior_state: dict,
        decision: str,
        feedback: str | None = None,
    ) -> dict:
        decision = decision.strip().lower()
        if decision not in {"approved", "rejected", "modified"}:
            raise ValueError(f"Invalid decision '{decision}'. Must be approved, rejected, or modified.")
        if decision == "modified" and not (feedback or "").strip():
            raise ValueError("feedback is required when decision is 'modified'")

        state: OrchestratorState = dict(prior_state)  # type: ignore[assignment]
        state["human_decision"] = decision
        state["human_feedback"] = feedback
        state["requires_user_input"] = False

        logs = list(state.get("logs", []))

        if decision == "rejected":
            reason = feedback or "No reason provided"
            logs.append({
                "step": "human_validation",
                "message": f"Plan rejected by user. Reason: {reason}",
            })
            state["logs"] = logs
            state["status"] = "rejected"
            state["result"] = {
                "agent": self.name,
                "status": "rejected",
                "plan": state.get("plan"),
                "rejection_reason": reason,
            }
            logger.info("[OrchestratorAgent] resume_with_human_decision: rejected")
            return state

        if decision == "modified":
            logs.append({
                "step": "human_validation",
                "message": f"Modification requested — replanning with feedback: {feedback}",
            })
            state["logs"] = logs
            state["human_feedback"] = feedback
            state["human_decision"] = None

            state = self._planning_phase_node(state)
            state = self._cost_estimation_node(state)

            state["requires_user_input"] = True
            state["status"] = "awaiting_plan_validation"
            state["security"] = SecurityScoreTransformer.transform(
                repository_security=state.get("repository_security"),
                env_security_runtime=state.get("env_security_runtime"),
            )
            logger.info("[OrchestratorAgent] resume_with_human_decision: replanned, pausing again")
            return state

        # Approved — run full generation pipeline
        logs.append({
            "step": "human_validation",
            "message": "Plan approved by user — proceeding to artifact generation",
        })
        state["logs"] = logs

        approved_artifacts = (
            state.get("approved_artifacts")
            or (state.get("plan") or {}).get("required_artifacts")
            or []
        )
        state["approved_artifacts"] = approved_artifacts
        plan = dict(state.get("plan") or {})
        plan["approved_artifacts"] = approved_artifacts
        state["plan"] = plan

        logger.info("[OrchestratorAgent] resume_with_human_decision: approved, running generation")

        state = self._infrastructure_node(state)
        state = self._terraform_phase_node(state)
        state = self._kubernetes_phase_node(state)
        state = self._security_scan_phase_node(state)
        state = self._filter_generated_artifacts(state)
        state = self._artifact_validation_node(state)

        next_step = self._route_after_validation(state)
        if next_step == "cicd":
            state = self._cicd_node(state)

        state = self._finalize_node(state)
        return state

    # ═══════════════════════════════════════════════════════════════════════════
    # Utilities
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_app_config(self, state: OrchestratorState) -> dict:
        """Build KubernetesAgent app_config from orchestrator state."""
        plan = state.get("plan") or {}
        repo_summary = state.get("repo_summary") or {}
        infrastructure_context = (state.get("agent_context") or {}).get("infrastructure_context") or {}
        services = infrastructure_context.get("services") or []

        # Detect primary port
        ports: list[int] = []
        for svc in services:
            port = svc.get("port")
            if port and isinstance(port, int):
                ports.append(port)
        if not ports:
            ports = [8080]

        # Non-sensitive env var names only
        env_var_names: list[str] = []
        for svc in services:
            for ev in (svc.get("environment_variables") or []):
                name = ev if isinstance(ev, str) else ev.get("name", "")
                if name:
                    env_var_names.append(name)

        app_name = (
            repo_summary.get("name")
            or plan.get("agent")
            or "app"
        )

        return {
            "app_name": str(app_name).lower().replace(" ", "-")[:63],
            "namespace": "default",
            "ports": ports[:3],
            "replicas": 2,
            "env_vars": env_var_names[:15],
            "resource_limits": {"cpu": "500m", "memory": "512Mi"},
        }

    def _artifact_matches_requested(
        self, generated_artifact: str, requested_artifacts: set[str]
    ) -> bool:
        if not requested_artifacts:
            return True
        for req in requested_artifacts:
            if req == generated_artifact:
                return True
            if "*" in req:
                prefix = req.split("*", 1)[0]
                if generated_artifact.startswith(prefix):
                    return True
        return False

    def _find_target_path(self, targets: list[str], filename: str) -> str | None:
        return next(
            (t for t in targets if t.lower().endswith(filename.lower())), None
        )

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

    # ═══════════════════════════════════════════════════════════════════════════
    # Step-by-step execution methods (used by /workflow router)
    # ═══════════════════════════════════════════════════════════════════════════

    def run_docker_phase(self, prior_state: dict) -> dict:
        """Run ONLY the Docker (InfrastructureAgent) phase and return updated state."""
        state: OrchestratorState = dict(prior_state)  # type: ignore[assignment]
        logger.info("[OrchestratorAgent] run_docker_phase — starting")
        state = self._infrastructure_node(state)
        state["current_phase"] = "docker_completed"
        logs = list(state.get("logs", []))
        logs.append({"step": "phase_checkpoint", "message": "Docker phase complete — awaiting user approval"})
        state["logs"] = logs
        return state

    def run_terraform_phase_only(self, prior_state: dict, task_id: Optional[str] = None) -> dict:
        """Run ONLY the TerraformAgent phase and return updated state.

        ``task_id`` is forwarded so the deterministic backend.tf injector
        can key state objects per-task.
        """
        state: OrchestratorState = dict(prior_state)  # type: ignore[assignment]
        if task_id and "task_id" not in state:
            state["task_id"] = task_id  # type: ignore[typeddict-unknown-key]
        logger.info(
            "[OrchestratorAgent] run_terraform_phase_only — starting (task_id=%s)",
            state.get("task_id"),
        )
        state = self._terraform_phase_node(state)

        # The phase node sets `current_phase` to terraform_failed or
        # terraform_validation_failed on error; respect it. Otherwise
        # promote to terraform_completed.
        phase = state.get("current_phase") or ""
        if phase not in ("terraform_failed", "terraform_validation_failed"):
            state["current_phase"] = "terraform_completed"
        logs = list(state.get("logs", []))
        if state["current_phase"] == "terraform_completed":
            logs.append({"step": "phase_checkpoint", "message": "Terraform phase complete — awaiting user approval"})
        elif state["current_phase"] == "terraform_validation_failed":
            logs.append({"step": "phase_checkpoint", "message": "Terraform validation failed — pipeline blocked"})
        else:
            logs.append({"step": "phase_checkpoint", "message": "Terraform generation failed — pipeline blocked"})
        state["logs"] = logs
        return state

    def run_kubernetes_phase_only(self, prior_state: dict) -> dict:
        """Run ONLY the KubernetesAgent phase and return updated state."""
        state: OrchestratorState = dict(prior_state)  # type: ignore[assignment]
        logger.info("[OrchestratorAgent] run_kubernetes_phase_only — starting")
        state = self._kubernetes_phase_node(state)
        state["current_phase"] = "kubernetes_completed"
        logs = list(state.get("logs", []))
        logs.append({"step": "phase_checkpoint", "message": "Kubernetes phase complete — awaiting user approval"})
        state["logs"] = logs
        return state

    def run_cicd_and_finalize_phase(self, prior_state: dict) -> dict:
        """Run security scan, validation, CI/CD, and finalize. Returns the complete result."""
        state: OrchestratorState = dict(prior_state)  # type: ignore[assignment]
        logger.info("[OrchestratorAgent] run_cicd_and_finalize_phase — starting")
        state = self._security_scan_phase_node(state)
        state = self._filter_generated_artifacts(state)
        state = self._artifact_validation_node(state)
        next_step = self._route_after_validation(state)
        if next_step == "cicd":
            state = self._cicd_node(state)
        state = self._finalize_node(state)
        state["current_phase"] = "completed"
        return state

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
