from pathlib import Path

from langgraph.graph import END, START, StateGraph

from agents.base_agent import BaseAgent
from agents.codebase_analysis_agent import CodebaseAnalysisAgent
from agents.infrastructure_agent import InfrastructureAgent
from agents.planner_agent import PlannerAgent
from agents.state import OrchestratorState


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
            "Please generate a DevSecOps execution plan with required_artifacts for the provided task."
        )
        default_infrastructure = (
            "Please generate complete infrastructure artifacts for the provided plan."
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
        analysis = self.codebase_agent.run(state["repo_url"])  # type: ignore[index]

        logs = list(state.get("logs", []))
        security_result = analysis.get("security")

        if security_result and security_result.get("status") == "blocked":
            logs.append(
                {
                    "step": "repository_security",
                    "message": "Repository blocked by security gate",
                }
            )
        elif security_result and security_result.get("status") == "safe_with_warnings":
            logs.append(
                {
                    "step": "repository_security",
                    "message": "Repository passed with warnings",
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
            "repo_summary": analysis.get("repo_summary"),
            "file_tree": analysis.get("file_tree"),
            "important_files": analysis.get("important_files"),
            "agent_context": analysis.get("agent_context"),
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
        )

        logs = list(state.get("logs", []))
        logs.append(
            {
                "step": "infrastructure",
                "message": "Infrastructure artifacts generated",
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

        required_artifacts = plan.get("required_artifacts", [])
        generated_artifacts = infra.get("generated_artifacts", [])

        missing_artifacts = [
            artifact
            for artifact in required_artifacts
            if artifact not in generated_artifacts
        ]

        validation_status = "valid" if not missing_artifacts else "partial"

        validation = {
            "status": validation_status,
            "required_artifacts": required_artifacts,
            "generated_artifacts": generated_artifacts,
            "missing_artifacts": missing_artifacts,
        }

        logs = list(state.get("logs", []))
        if missing_artifacts:
            logs.append(
                {
                    "step": "artifact_validation",
                    "message": f"Missing artifacts detected: {', '.join(missing_artifacts)}",
                }
            )
        else:
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

    def _finalize_node(self, state: OrchestratorState) -> OrchestratorState:
        logs = list(state.get("logs", []))
        logs.append(
            {
                "step": "completed",
                "message": "Workflow completed successfully",
            }
        )

        validation = state.get("validation") or {}
        security_result = state.get("repository_security") or {}

        final_status = "completed"
        result_status = "success"

        if security_result.get("status") == "blocked":
            final_status = "blocked"
            result_status = "blocked"
        elif validation.get("status") == "partial":
            final_status = "partial_success"
            result_status = "partial_success"

        result = {
            "agent": self.name,
            "status": result_status,
            "repository_security": security_result,
            "repo_summary": state.get("repo_summary"),
            "plan": state.get("plan"),
            "infrastructure": state.get("infra"),
            "validation": validation,
        }

        return {
            **state,
            "status": final_status,
            "result": result,
            "logs": logs,
        }

    def _build_graph(self):
        workflow = StateGraph(OrchestratorState)

        workflow.add_node("initialize", self._initialize_node)
        workflow.add_node("analyze_repository", self._analyze_repository_node)
        workflow.add_node("planner", self._planner_node)
        workflow.add_node("infrastructure", self._infrastructure_node)
        workflow.add_node("artifact_validation", self._artifact_validation_node)
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
        workflow.add_edge("artifact_validation", "finalize")
        workflow.add_edge("finalize", END)

        return workflow.compile()

    def run(self, prompt: str, repo_url: str | None = None) -> dict:
        initial_state: OrchestratorState = {
            "prompt": prompt,
            "repo_url": repo_url,
            "status": "pending",
            "logs": [],
            "repository_security": None,
            "repo_summary": None,
            "file_tree": None,
            "important_files": None,
            "agent_context": None,
            "plan": None,
            "infra": None,
            "validation": None,
            "result": None,
            "error_message": None,
        }
        return self.graph.invoke(initial_state)