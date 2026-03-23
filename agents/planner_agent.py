from typing import Any, Dict

from agents.base_agent import BaseAgent
from backend.app.services.llm_service import LLMService


class PlannerAgent(BaseAgent):
    def __init__(self, prompt_template: str):
        super().__init__(name="PlannerAgent")
        self.llm = LLMService()
        self.prompt_template = prompt_template

    def run(self, prompt: str, planner_context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        user_prompt = f"""
User task:
{prompt}

Repository context:
{planner_context or {}}
""".strip()

        return self.llm.chat_json(
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=1400,
        )