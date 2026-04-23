"""
OrchestratorAgent — LangGraph-based multi-agent workflow coordinator.

Upgrades over the previous static orchestrator
-----------------------------------------------
1. **Dynamic routing after planner**
   - If the plan produces no artifacts and no reasoning → skip to finalize.
   - Otherwise proceed normally to infrastructure generation.

2. **Dynamic routing after artifact validation**
   - If validation reports INVALID (all required artifacts missing) → skip
     CI/CD and finalize with a clear error status.
   - If validation is PARTIAL or VALID → proceed to CI/CD as normal.

3. **Context-aware routing after repository analysis**
   - Security-blocked repos are routed to finalize immediately (unchanged).
   - Repos with no agent_context (e.g. empty repo) go straight to planner
     without error.

4. **Routing decision logging**
   - Every routing decision is appended to ``state["logs"]`` for
     full observability in the task history.

5. **Multi-phase workflow with human-in-the-loop plan selection**
   - New phases: planning_phase → multi_plan_phase → plan_selection (pause)
     → generation_phase → validation_phase.
   - run_until_plan_selection(): executes up to multi_plan_phase then stops.
   - resume_with_plan(selected_plan_id): resumes from generation_phase with
     the chosen plan injected into state.
   - auto_mode=True skips plan_selection and picks the first available plan.

All execution modes (``run``, ``run_plan_preview``, ``run_generation``,
``run_until_plan_selection``, ``resume_with_plan``) are supported.
"""

from __future__ import annotations

import logging
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from backend.app.agents.base_agent import BaseAgent
from backend.app.agents.codebase_analysis_agent import CodebaseAnalysisAgent
from backend.app.agents.cost_estimation_agent import CostEstimationAgent
from backend.app.agents.infrastructure_agent import InfrastructureAgent
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

    Graph topology
    --------------

    START
      │
      ▼
    initialize
      │
      ├── (repo_url?) ──────────────────────────────┐
      │                                              ▼
      │                                    analyze_repository
      │                                              │
      │                          ┌───────────────────┤
      │                          │ security_blocked?  │ ok?
      │                          ▼                    ▼
      │                       finalize          planning_phase ◄──── (no repo_url)
      │                                              │
      │                                       multi_plan_phase
      │                                              │
      │                          ┌───────────────────┤
      │                          │ auto_mode=True     │ default
      │                          │ (pick first plan)  ▼
      │                          │             plan_selection
      │                          │             (awaiting_user_input)
      │                          │                    │
      │                          │              selected_plan?
      │                          │             yes /        \ no
      │                          ▼            ▼              ▼
      │                    generation_phase  generation_phase  END (partial)
      │    (≡infrastructure)     │
      │                   artifact_validation (validation_phase)
      │                                              │
      │                       ┌──────────────────────┤
      │                       │ fully_invalid?        │ ok / partial?
      │                       ▼                       ▼
      │                    finalize                 cicd
      │                                              │
      │                                           finalize
      │                                              │
      └──────────────────────────────────────────── END
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
            '"required_artifacts" (array of file path strings — MUST include terraform/main.tf '
            'and Dockerfile; include kubernetes/deployment.yaml for microservices), '
            '"estimated_complexity" ("low"|"medium"|"high"), '
            '"reasoning_summary" (string — MUST explain why Terraform is used and why '
            'Kubernetes is or is not chosen based on the application architecture).'
        )
        default_infrastructure = (
            "You are a DevSecOps infrastructure generation agent. Respond with ONLY a valid JSON "
            "object — no markdown, no prose, no code fences. "
            'The JSON must have an "artifacts" key (object) whose values are plain strings: '
            '"dockerfile", "dockerignore", "docker_compose", "env_example", "terraform_main", '
            '"terraform_variables", "terraform_outputs", "kubernetes_deployment", '
            '"kubernetes_service", "kubernetes_configmap", "kubernetes_manifests", '
            '"security_notes". '
            'Also include "generated_artifacts" (array of generated keys) and "summary" (string). '
            "Only include artifacts relevant to the approved list. Never inject real secrets."
        )

        planner_prompt = planner_prompt or _read("planner_prompt.txt", default_planner)
        infrastructure_prompt = infrastructure_prompt or _read(
            "infrastructure_prompt.txt", default_infrastructure
        )

        self.planner_agent = PlannerAgent(prompt_template=planner_prompt)
        self.codebase_agent = CodebaseAnalysisAgent()
        self.infrastructure_agent = InfrastructureAgent(prompt_template=infrastructure_prompt)
        self.cicd_agent = CICDAgent()
        self.cost_estimation_agent = CostEstimationAgent()
        self.multi_plan_agent = MultiPlanAgent()
        self.artifact_quality_validator = ArtifactQualityValidator()
        self.artifact_contract_service = ArtifactContractService()
        self.graph = self._build_graph()

    # ═══════════════════════════════════════════════════════════════════════════
    # Graph nodes
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
                "[OrchestratorAgent] application_profile key absent from analysis output (cache_status=%s) — profiling pipeline did not set it",
                cache_status,
            )
            raise Exception("Application profiling failed: key missing from analysis output")

        if not application_profile:
            logger.error(
                "[OrchestratorAgent] application_profile is an empty dict (cache_status=%s) — profiling returned no usable data",
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
            "agent_context": agent_context,
            "application_profile": application_profile,
            "env_security_runtime": analysis.get("env_security_runtime"),
            "logs": logs,
        }

    def _planner_node(self, state: OrchestratorState) -> OrchestratorState:
        """Retained for backward-compat; delegates to _planning_phase_node."""
        return self._planning_phase_node(state)

    def _planning_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        """Phase 1 — run PlannerAgent and store the primary plan.

        Always sets ``requires_user_input=True`` so the human_validation node
        decides whether to proceed (auto_mode) or pause for API input.
        If ``human_feedback`` is present in state the prompt is augmented with
        the modification request so the planner regenerates accordingly.
        """
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

        # Augment the prompt when the user has requested plan modifications.
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

        # Signal that a human decision is required before execution continues.
        return {**state, "plan": plan, "logs": logs, "requires_user_input": True}

    def _cost_estimation_node(self, state: OrchestratorState) -> OrchestratorState:
        """Estimate monthly AWS cost from the infrastructure blueprint in the plan."""
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
        """
        Phase 2 — generate three infrastructure plan variants (low_cost,
        balanced, high_performance) via MultiPlanAgent and store them in
        ``state["plans"]`` for the subsequent plan_selection node.
        """
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
        """
        Blocking node — workflow pauses here until the user injects a selected_plan.

        In run_until_plan_selection() the graph is invoked but the conditional
        edge after this node routes to END when selected_plan is None, so no
        further processing happens until resume_with_plan() is called.
        """
        logs = list(state.get("logs", []))
        logs.append({
            "step": "plan_selection",
            "message": "Workflow paused — awaiting user plan selection",
        })
        logger.info("[OrchestratorAgent] plan_selection node reached — workflow paused")
        return {**state, "awaiting_user_input": True, "logs": logs}

    def _human_validation_node(self, state: OrchestratorState) -> OrchestratorState:
        """Bloc 7 — human-in-the-loop gate between planning and execution.

        Behaviour
        ---------
        * ``auto_mode=True``           → auto-approve and clear the gate.
        * ``human_decision`` not set   → stay paused (graph will route to finalize).
        * ``human_decision=approved``  → clear the gate, continue.
        * ``human_decision=rejected``  → mark status as rejected, stop.
        * ``human_decision=modified``  → re-plan with feedback (graph path only;
          the API path handles this loop via ``resume_with_human_decision``).
        """
        logs = list(state.get("logs", []))

        # ── Auto-approve for batch / automated runs ───────────────────────────
        if state.get("auto_mode"):
            logs.append({
                "step": "human_validation",
                "message": "Auto-mode active — plan auto-approved, proceeding to execution",
            })
            logger.info("[OrchestratorAgent] human_validation: auto-approved")
            return {**state, "human_decision": "approved", "requires_user_input": False, "logs": logs}

        decision = (state.get("human_decision") or "").strip().lower()

        # ── No decision yet — workflow is paused ─────────────────────────────
        if not decision:
            logs.append({
                "step": "human_validation",
                "message": "Workflow paused — awaiting human plan validation via API",
            })
            logger.info("[OrchestratorAgent] human_validation: paused, no decision received")
            return {**state, "requires_user_input": True, "logs": logs}

        # ── Approved ─────────────────────────────────────────────────────────
        if decision == "approved":
            logs.append({
                "step": "human_validation",
                "message": "Plan approved by user — proceeding to execution",
            })
            logger.info("[OrchestratorAgent] human_validation: approved")
            return {**state, "requires_user_input": False, "logs": logs}

        # ── Rejected ─────────────────────────────────────────────────────────
        if decision == "rejected":
            reason = (state.get("human_feedback") or "No reason provided")
            logs.append({
                "step": "human_validation",
                "message": f"Plan rejected by user. Reason: {reason}",
            })
            logger.info("[OrchestratorAgent] human_validation: rejected")
            return {**state, "status": "rejected", "requires_user_input": False, "logs": logs}

        # ── Modified (graph path only — API path uses resume_with_human_decision)
        logs.append({
            "step": "human_validation",
            "message": "Modification requested — replanning required via API",
        })
        return {**state, "status": "awaiting_replanning", "requires_user_input": True, "logs": logs}

    # generation_phase and validation_phase are thin aliases so the graph uses
    # the new phase names while delegating to the existing heavy-lift nodes.

    def _generation_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        """Phase alias → infrastructure generation."""
        logger.info("[OrchestratorAgent] Entering generation_phase")
        return self._infrastructure_node(state)

    def _validation_phase_node(self, state: OrchestratorState) -> OrchestratorState:
        """Phase alias → artifact validation."""
        logger.info("[OrchestratorAgent] Entering validation_phase")
        return self._artifact_validation_node(state)

    def _infrastructure_node(self, state: OrchestratorState) -> OrchestratorState:
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
                f"Infrastructure artifacts generated "
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

        # Surface validation issues from InfrastructureAgent
        val_summary = infra.get("validation_summary") or {}
        if val_summary.get("issues"):
            logs.append({
                "step": "infrastructure_validation",
                "message": (
                    f"Artifact validation: {val_summary.get('status')} — "
                    f"{len(val_summary['issues'])} issue(s)"
                ),
            })

        return {**state, "infra": infra, "logs": logs}

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
                artifact_targets.get("kubernetes") or [], "deployment.yaml"
            ) or "kubernetes/deployment.yaml",
            "kubernetes_service": self._find_target_path(
                artifact_targets.get("kubernetes") or [], "service.yaml"
            ) or "kubernetes/service.yaml",
            "kubernetes_configmap": self._find_target_path(
                artifact_targets.get("kubernetes") or [], "configmap.yaml"
            ) or "kubernetes/configmap.yaml",
            "terraform_main": self._find_target_path(
                artifact_targets.get("terraform") or [], "main.tf"
            ) or "terraform/main.tf",
            "terraform_variables": self._find_target_path(
                artifact_targets.get("terraform") or [], "variables.tf"
            ) or "terraform/variables.tf",
            "terraform_outputs": (
                self._find_target_path(artifact_targets.get("terraform") or [], "output.tf")
                or self._find_target_path(artifact_targets.get("terraform") or [], "outputs.tf")
                or "terraform/output.tf"
            ),
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

        # Transform security data into frontend-expected format
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
            "cicd": cicd,
            "cost_estimation": state.get("cost_estimation"),
            "validation": final_validation,
            "artifact_contract": final_contract,
        }

        return {**state, "status": final_status, "result": result, "logs": logs}

    # ═══════════════════════════════════════════════════════════════════════════
    # Dynamic routing functions
    # ═══════════════════════════════════════════════════════════════════════════

    def _route_repository(self, state: OrchestratorState) -> str:
        """Route to repo analysis or directly to planning_phase."""
        return "analyze_repository" if state.get("repo_url") else "planning_phase"

    def _route_after_repository_analysis(self, state: OrchestratorState) -> str:
        """
        After repo analysis:
        - security blocked → finalize immediately
        - otherwise → planning_phase
        """
        security_result = state.get("repository_security") or {}
        if security_result.get("status") == "blocked":
            return "finalize"
        return "planning_phase"

    def _route_after_multi_plan(self, state: OrchestratorState) -> str:
        """
        Routing after multi_plan_phase.

        - auto_mode=True  → pick first plan automatically, go to generation_phase.
        - Otherwise       → set awaiting_user_input=True, park at plan_selection.
        """
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
        """
        Continue to generation_phase only if the user has supplied a selected_plan.
        Otherwise surface a partial result and end.
        """
        if state.get("selected_plan"):
            logger.info(
                "[OrchestratorAgent] Plan '%s' selected — resuming to generation_phase",
                state["selected_plan"],
            )
            return "generation_phase"

        logger.info("[OrchestratorAgent] No plan selected — stopping workflow")
        return "finalize"

    def _route_after_human_validation(self, state: OrchestratorState) -> str:
        """
        Route after the human_validation node.

        - auto_mode or decision=approved → cost_estimation
        - decision=rejected / still waiting / modified → finalize (partial/stopped)
        """
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
        """
        Dynamic routing after planning_phase — context-aware decision.

        Rules (evaluated in priority order):
        1. Plan has no required_artifacts AND no reasoning → skip generation.
        2. Otherwise → multi_plan_phase.
        """
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
        """
        Dynamic routing after artifact validation.

        Rules:
        - INVALID (all required artifacts missing) → skip CI/CD, go to finalize.
        - PARTIAL or VALID → proceed to CI/CD.
        """
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
        workflow.add_node("initialize", self._initialize_node)
        workflow.add_node("analyze_repository", self._analyze_repository_node)

        # Phase nodes (new architecture)
        workflow.add_node("planning_phase", self._planning_phase_node)
        workflow.add_node("human_validation", self._human_validation_node)  # Bloc 7
        workflow.add_node("cost_estimation", self._cost_estimation_node)
        workflow.add_node("multi_plan_phase", self._multi_plan_phase_node)
        workflow.add_node("plan_selection", self._plan_selection_node)
        workflow.add_node("generation_phase", self._generation_phase_node)
        workflow.add_node("validation_phase", self._validation_phase_node)

        workflow.add_node("cicd", self._cicd_node)
        workflow.add_node("finalize", self._finalize_node)

        # ── Entry ─────────────────────────────────────────────────────────────
        workflow.add_edge(START, "initialize")

        # initialize → analyze_repository | planning_phase
        workflow.add_conditional_edges(
            "initialize",
            self._route_repository,
            {"analyze_repository": "analyze_repository", "planning_phase": "planning_phase"},
        )

        # analyze_repository → planning_phase | finalize (security blocked)
        workflow.add_conditional_edges(
            "analyze_repository",
            self._route_after_repository_analysis,
            {"planning_phase": "planning_phase", "finalize": "finalize"},
        )

        # planning_phase → human_validation | finalize (empty plan)
        workflow.add_conditional_edges(
            "planning_phase",
            self._route_after_planning_phase,
            {"cost_estimation": "human_validation", "finalize": "finalize"},
        )

        # human_validation → cost_estimation (approved/auto) | finalize (rejected/paused)
        workflow.add_conditional_edges(
            "human_validation",
            self._route_after_human_validation,
            {"cost_estimation": "cost_estimation", "finalize": "finalize"},
        )

        # cost_estimation → multi_plan_phase (always)
        workflow.add_edge("cost_estimation", "multi_plan_phase")

        # multi_plan_phase → plan_selection | generation_phase (auto_mode)
        workflow.add_conditional_edges(
            "multi_plan_phase",
            self._route_after_multi_plan,
            {"plan_selection": "plan_selection", "generation_phase": "generation_phase"},
        )

        # plan_selection → generation_phase (plan chosen) | finalize (no plan)
        workflow.add_conditional_edges(
            "plan_selection",
            self._route_after_plan_selection,
            {"generation_phase": "generation_phase", "finalize": "finalize"},
        )

        # generation_phase → validation_phase (always)
        workflow.add_edge("generation_phase", "validation_phase")

        # validation_phase → cicd | finalize (fully invalid)
        workflow.add_conditional_edges(
            "validation_phase",
            self._route_after_validation,
            {"cicd": "cicd", "finalize": "finalize"},
        )

        # cicd → finalize (always)
        workflow.add_edge("cicd", "finalize")
        workflow.add_edge("finalize", END)

        return workflow.compile()

    # ═══════════════════════════════════════════════════════════════════════════
    # Public execution modes
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
        """Build a fresh initial OrchestratorState."""
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
            "cicd": None,
            "cost_estimation": None,
            "application_profile": None,
            "validation": None,
            "result": None,
            "error_message": None,
            # Bloc 7 — human validation gate
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

        # Apply dynamic routing for the validation → cicd transition
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
        """
        Execute the workflow up to and including multi_plan_phase, then stop.

        Returns the partial state that includes ``plans`` and
        ``awaiting_user_input=True``.  Call ``resume_with_plan()`` to continue.
        """
        logger.info("[OrchestratorAgent] run_until_plan_selection — starting")
        state: OrchestratorState = self._base_state(
            prompt=prompt,
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
            uploaded_env_input=uploaded_env_input,
            auto_mode=False,  # force interactive mode
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
        """
        Resume the workflow from generation_phase using a user-selected plan.

        Parameters
        ----------
        prior_state:
            The state dict returned by ``run_until_plan_selection()``.
        selected_plan_id:
            The ``plan_id`` of the chosen plan from ``prior_state["plans"]``.
        approved_artifacts:
            Optional artifact allowlist; if omitted the plan's own
            required_artifacts list is used.
        """
        logger.info(
            "[OrchestratorAgent] resume_with_plan — selected plan '%s'", selected_plan_id
        )

        state: OrchestratorState = dict(prior_state)  # type: ignore[assignment]
        state["selected_plan"] = selected_plan_id
        state["awaiting_user_input"] = False

        # Resolve which plan dict corresponds to the selection
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
        """
        Bloc 7 — resume the pipeline after a human validates the plan.

        Parameters
        ----------
        prior_state:
            The OrchestratorState returned by ``run_plan_preview()``,
            loaded from the persisted ``task.workflow_state``.
        decision:
            ``"approved"`` | ``"rejected"`` | ``"modified"``
        feedback:
            Free-text reason (required when ``decision == "modified"``).

        Returns
        -------
        dict
            Updated state.  Callers inspect ``requires_user_input`` to
            determine whether another validation round is needed (``modified``
            path) or the pipeline has finished.
        """
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

        # ── Rejected ─────────────────────────────────────────────────────────
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

        # ── Modified — re-plan with user feedback then pause again ───────────
        if decision == "modified":
            logs.append({
                "step": "human_validation",
                "message": f"Modification requested — replanning with feedback: {feedback}",
            })
            state["logs"] = logs

            # Carry feedback into state so _planning_phase_node picks it up
            state["human_feedback"] = feedback
            # Reset decision so the next call can set a fresh one
            state["human_decision"] = None

            state = self._planning_phase_node(state)   # regenerates plan
            state = self._cost_estimation_node(state)  # refresh cost estimate

            state["requires_user_input"] = True
            state["status"] = "awaiting_plan_validation"
            state["security"] = SecurityScoreTransformer.transform(
                repository_security=state.get("repository_security"),
                env_security_runtime=state.get("env_security_runtime"),
            )
            logger.info("[OrchestratorAgent] resume_with_human_decision: replanned, pausing again")
            return state

        # ── Approved — run full generation pipeline ───────────────────────────
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
        state = self._filter_generated_artifacts(state)
        state = self._artifact_validation_node(state)

        next_step = self._route_after_validation(state)
        if next_step == "cicd":
            state = self._cicd_node(state)

        state = self._finalize_node(state)
        return state

    # ═══════════════════════════════════════════════════════════════════════════
    # Utilities (unchanged from original)
    # ═══════════════════════════════════════════════════════════════════════════

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
