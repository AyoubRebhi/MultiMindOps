from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from agents.base_agent import BaseAgent
from agents.planner_agent import PlannerAgent
from agents.state import OrchestratorState


class OrchestratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="OrchestratorAgent")
        self.planner_agent = PlannerAgent()
        self.graph = self._build_graph()

    def _initialize_node(self, state: OrchestratorState) -> OrchestratorState:
        logs = state.get("logs", [])
        logs.append({
            "step": "orchestrator",
            "message": "Starting orchestration"
        })

        return {
            **state,
            "status": "in_progress",
            "logs": logs,
        }

    def _planner_node(self, state: OrchestratorState) -> OrchestratorState:
        prompt = state["prompt"]
        plan = self.planner_agent.generate_plan(prompt)

        logs = state.get("logs", [])
        logs.append({
            "step": "planner",
            "message": "Execution plan generated"
        })

        return {
            **state,
            "plan": plan,
            "logs": logs,
        }

    def _finalize_node(self, state: OrchestratorState) -> OrchestratorState:
        logs = state.get("logs", [])
        logs.append({
            "step": "completed",
            "message": "Task completed successfully"
        })

        result = {
            "agent": self.name,
            "status": "success",
            "message": "Request processed successfully",
            "plan": state.get("plan"),
        }

        return {
            **state,
            "status": "completed",
            "logs": logs,
            "result": result,
        }

    def _build_graph(self):
        workflow = StateGraph(OrchestratorState)

        workflow.add_node("initialize", self._initialize_node)
        workflow.add_node("planner", self._planner_node)
        workflow.add_node("finalize", self._finalize_node)

        workflow.add_edge(START, "initialize")
        workflow.add_edge("initialize", "planner")
        workflow.add_edge("planner", "finalize")
        workflow.add_edge("finalize", END)

        return workflow.compile()

    def process_request(self, prompt: str) -> Dict[str, Any]:
        initial_state: OrchestratorState = {
            "prompt": prompt,
            "status": "pending",
            "logs": [],
            "plan": None,
            "result": None,
            "error_message": None,
        }

        final_state = self.graph.invoke(initial_state)
        return final_state

    def run(self, prompt: str) -> Dict[str, Any]:
        return self.process_request(prompt)