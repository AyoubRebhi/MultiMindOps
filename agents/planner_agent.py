from typing import Any, Dict, Literal

from pydantic import BaseModel, ValidationError

from agents.base_agent import BaseAgent
from backend.app.services.llm_service import LLMService


class PlannerResponseSchema(BaseModel):
    agent: str
    input_prompt: str
    steps: list[str]
    required_artifacts: list[str]
    estimated_complexity: Literal["low", "medium", "high"]
    reasoning_summary: str


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

        response = self.llm.chat_json(
            system_prompt=self.prompt_template,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=1400,
        )

        if "ERROR" in response or "error" in response:
            raise ValueError(f"Planner provider returned an error payload: {response}")

        try:
            validated = PlannerResponseSchema.model_validate(response)
        except ValidationError as exc:
            raise ValueError(
                f"Planner returned an invalid JSON structure: {exc}"
            ) from exc

        return validated.model_dump()
