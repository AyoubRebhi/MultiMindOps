from typing import Any, Dict

from agents.base_agent import BaseAgent
from backend.app.services.llm_service import LLMService


class InfrastructureAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="InfrastructureAgent")
        self.llm = LLMService()

    def generate_infra(self, prompt: str, plan: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = """
You are an Infrastructure Agent for a DevSecOps AI platform.
Generate infrastructure artifacts based on the user request and plan.
Return ONLY valid JSON:
{
  "agent": "InfrastructureAgent",
  "dockerfile": "...",
  "docker_compose": "...",
  "kubernetes": "...",
  "terraform": "...",
  "notes": ["..."]
}
If an artifact is not needed, return an empty string.
"""

        user_prompt = f"User request:\n{prompt}\n\nPlan:\n{plan}"
        content = self.llm.chat(system_prompt, user_prompt)

        if not content or not content.strip():
            raise ValueError(f"InfrastructureAgent: Empty response from LLM")
        
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
            import json
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"InfrastructureAgent: Failed to parse LLM response as JSON. Response: {content[:500]}. Error: {str(e)}")

    def run(self, prompt: str, plan: Dict[str, Any]) -> Dict[str, Any]:
        return self.generate_infra(prompt, plan)