from typing import Any, Dict, List

from agents.base_agent import BaseAgent


class PlannerAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="PlannerAgent")

    def generate_plan(self, prompt: str) -> Dict[str, Any]:
        prompt_lower = prompt.lower()

        steps: List[str] = ["analyse projet"]

        if "ci/cd" in prompt_lower or "pipeline" in prompt_lower:
            steps.append("génération pipeline ci/cd")

        if "docker" in prompt_lower:
            steps.append("génération dockerfile")

        if "kubernetes" in prompt_lower or "k8s" in prompt_lower:
            steps.append("génération manifestes kubernetes")

        if "terraform" in prompt_lower:
            steps.append("génération scripts terraform")

        steps.append("scan sécurité")
        steps.append("déploiement")
        steps.append("monitoring")
        steps.append("retour logs et statut")

        return {
            "agent": self.name,
            "input_prompt": prompt,
            "steps": steps,
            "estimated_complexity": "medium" if len(steps) > 5 else "low",
        }

    def run(self, prompt: str) -> Dict[str, Any]:
        return self.generate_plan(prompt)