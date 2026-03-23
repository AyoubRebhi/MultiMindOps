import json
from typing import Any, Dict

from agents.base_agent import BaseAgent
from backend.app.services.llm_service import LLMService


class PlannerAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="PlannerAgent")
        self.llm = LLMService()

    def generate_plan(self, prompt: str) -> Dict[str, Any]:
        system_prompt = """
You are a DevSecOps planning agent.
Return ONLY valid JSON with this structure:
{
  "agent": "PlannerAgent",
  "input_prompt": "...",
  "steps": ["..."],
  "estimated_complexity": "low|medium|high"
}
Break the request into concrete DevSecOps execution steps.
"""

        content = self.llm.chat(system_prompt, prompt)
        if not content or not content.strip():
            raise ValueError(f"PlannerAgent: Empty response from LLM")
        
        # Strip markdown code blocks if present
        content = content.strip()
        if content.startswith("```"):
            content = content[3:]
        if content.startswith("json"):
            content = content[4:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"PlannerAgent: Failed to parse LLM response as JSON. Response: {content[:500]}. Error: {str(e)}")

    def run(self, prompt: str) -> Dict[str, Any]:
        return self.generate_plan(prompt)