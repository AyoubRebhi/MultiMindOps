import unittest
from unittest.mock import patch

from agents.planner_agent import PlannerAgent


class FakeLLMService:
    def __init__(self, response: dict):
        self._response = response

    def chat_json(self, **_: object) -> dict:
        return dict(self._response)


class PlannerAgentGithubActionsOnlyTests(unittest.TestCase):
    def test_planner_replaces_jenkins_with_github_actions(self):
        response = {
            "agent": "PlannerAgent",
            "input_prompt": "Generate CI/CD artifacts",
            "steps": ["Create CI/CD pipeline"],
            "required_artifacts": ["Jenkinsfile", "Dockerfile"],
            "estimated_complexity": "medium",
            "reasoning_summary": "Need CI/CD for the repo.",
        }

        with patch("agents.planner_agent.LLMService", return_value=FakeLLMService(response)):
            agent = PlannerAgent(prompt_template="test")

        plan = agent.run(
            "Generate CI/CD pipeline for this repo",
            planner_context={"repo_summary": {"ci_cd_files": ["Jenkinsfile"]}},
        )

        self.assertIn(".github/workflows/ci-cd.yml", plan["required_artifacts"])
        self.assertIn("Dockerfile", plan["required_artifacts"])
        self.assertNotIn("Jenkinsfile", plan["required_artifacts"])

    def test_planner_keeps_supported_github_actions_artifact(self):
        response = {
            "agent": "PlannerAgent",
            "input_prompt": "Generate CI/CD artifacts",
            "steps": ["Create workflow"],
            "required_artifacts": [".github/workflows/ci-cd.yml"],
            "estimated_complexity": "low",
            "reasoning_summary": "Need GitHub Actions.",
        }

        with patch("agents.planner_agent.LLMService", return_value=FakeLLMService(response)):
            agent = PlannerAgent(prompt_template="test")

        plan = agent.run("Generate GitHub Actions workflow")

        self.assertEqual(plan["required_artifacts"], [".github/workflows/ci-cd.yml"])


if __name__ == "__main__":
    unittest.main()
