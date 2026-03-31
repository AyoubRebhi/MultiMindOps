from typing import Any, Dict, List

from agents.base_agent import BaseAgent
from backend.app.services.llm_service import LLMService


class InfrastructureAgent(BaseAgent):
    def __init__(self, prompt_template: str):
        super().__init__(name="InfrastructureAgent")
        self.llm = LLMService()
        self.prompt_template = prompt_template

    def run(
        self,
        prompt: str,
        plan: Dict[str, Any],
        infrastructure_context: Dict[str, Any] | None = None,
        approved_artifacts: List[str] | None = None,
    ) -> Dict[str, Any]:
        user_prompt = f"""
User task:
{prompt}

Execution plan:
{plan}

Infrastructure context:
{infrastructure_context or {}}

Approved artifacts to generate:
{approved_artifacts or []}
""".strip()

        return self.llm.chat_json(
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=2200,
        )