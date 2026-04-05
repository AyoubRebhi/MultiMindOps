from typing import Any, Dict, Literal

from pydantic import BaseModel, ValidationError

from backend.app.agents.base_agent import BaseAgent
from backend.app.services.core.llm_service import LLMService


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

        return self._normalize_plan(validated.model_dump(), prompt=prompt, planner_context=planner_context)

    def _normalize_plan(
        self,
        plan: Dict[str, Any],
        *,
        prompt: str,
        planner_context: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        normalized = dict(plan)
        required_artifacts = [
            self._normalize_artifact_path(item)
            for item in normalized.get("required_artifacts", [])
            if str(item or "").strip()
        ]

        github_actions_only = []
        cicd_requested = self._cicd_is_requested(prompt=prompt, planner_context=planner_context)

        for path in required_artifacts:
            lowered = path.lower()
            if self._is_disallowed_cicd_artifact(lowered):
                cicd_requested = True
                continue
            github_actions_only.append(path)

        if cicd_requested and not any(self._is_supported_github_actions_artifact(path) for path in github_actions_only):
            github_actions_only.append(".github/workflows/ci-cd.yml")

        normalized["required_artifacts"] = self._dedupe_preserve_order(github_actions_only)
        return normalized

    def _cicd_is_requested(
        self,
        *,
        prompt: str,
        planner_context: Dict[str, Any] | None,
    ) -> bool:
        text = f"{prompt}\n{planner_context or {}}".lower()
        return any(
            marker in text
            for marker in (
                "ci/cd",
                "cicd",
                "pipeline",
                "github actions",
                "workflow",
                "jenkins",
                "gitlab ci",
                "azure pipelines",
                "circleci",
            )
        )

    def _normalize_artifact_path(self, path: str) -> str:
        lowered = str(path).replace("\\", "/").strip()
        if self._is_supported_github_actions_artifact(lowered):
            return ".github/workflows/ci-cd.yml"
        return lowered

    def _is_supported_github_actions_artifact(self, path: str) -> bool:
        lowered = str(path).lower()
        return lowered.startswith(".github/workflows/") and lowered.endswith((".yml", ".yaml"))

    def _is_disallowed_cicd_artifact(self, path: str) -> bool:
        return any(
            token in path
            for token in (
                "jenkinsfile",
                ".gitlab-ci",
                "azure-pipelines",
                ".circleci/",
                "scripts/build.sh",
                "scripts/deploy.sh",
            )
        )

    def _dedupe_preserve_order(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result
