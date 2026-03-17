from typing import Any, Dict

from agents.base_agent import BaseAgent
from agents.planner_agent import PlannerAgent


class OrchestratorAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="OrchestratorAgent")
        self.planner_agent = PlannerAgent()

    def process_request(self, prompt: str) -> Dict[str, Any]:
        plan = self.planner_agent.generate_plan(prompt)

        return {
            "agent": self.name,
            "status": "success",
            "message": "Request processed successfully",
            "plan": plan,
        }

    def run(self, prompt: str) -> Dict[str, Any]:
        return self.process_request(prompt)