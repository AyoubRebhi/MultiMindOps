from __future__ import annotations

from typing import Any

from backend.app.services.github_actions_template_service import (
    GitHubActionsTemplateService,
)


class CicdWorkflowBuilderService:
    """Build GitHub Actions workflows as text artifacts only.

    The builder is deterministic, never executes commands, and limits CI/CD output
    to GitHub Actions workflow files. For this prototype, CI/CD statuses are reduced
    to `generated` or `missing`.
    """

    DEFAULT_WORKFLOW_PATH = ".github/workflows/ci-cd.yml"

    def __init__(self) -> None:
        self.template_service = GitHubActionsTemplateService()

    def detect_project_runtime(self, normalized_handoff: dict[str, Any]) -> dict[str, str]:
        repo_summary = normalized_handoff.get("repo_summary") or {}
        runtime = repo_summary.get("runtime") or {}
        project_type = str(repo_summary.get("project_type") or "")
        languages = [str(item).lower() for item in runtime.get("languages") or []]
        frameworks = [str(item).lower() for item in runtime.get("frameworks") or []]
        key_entrypoints = [str(item).lower() for item in normalized_handoff.get("key_entrypoints") or []]
        stack = repo_summary.get("stack") or {}
        devops_tools = [str(item).lower() for item in stack.get("devops_tools") or []]

        if "java" in languages or "spring boot" in frameworks or "spring boot" in project_type.lower():
            return {
                "runtime_name": "java",
                "language": "Java",
                "framework": "Spring Boot" if "spring boot" in frameworks or "spring boot" in project_type.lower() else "generic",
                "package_manager": "maven",
                "dockerized": "docker" in devops_tools,
            }

        if "node.js" in languages or "javascript" in languages or "typescript" in languages:
            return {
                "runtime_name": "node",
                "language": "Node.js",
                "framework": self._detect_framework(frameworks, project_type, default="generic"),
                "package_manager": "npm",
                "dockerized": "docker" in devops_tools,
            }

        if "python" in languages or any(path.endswith(".py") for path in key_entrypoints):
            return {
                "runtime_name": "python",
                "language": "Python",
                "framework": self._detect_framework(frameworks, project_type, default="generic"),
                "package_manager": "pip",
                "dockerized": "docker" in devops_tools,
            }

        return {
            "runtime_name": "generic",
            "language": "generic",
            "framework": "generic",
            "package_manager": "unknown",
            "dockerized": "docker" in devops_tools,
        }

    def generate_workflow_artifacts(
        self,
        normalized_handoff: dict[str, Any],
    ) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, str]]:
        runtime_info = self.detect_project_runtime(normalized_handoff)
        requested_artifacts = set(normalized_handoff.get("requested_cicd_artifacts") or [])
        candidate_artifacts = normalized_handoff.get("candidate_cicd_artifacts") or [
            self.DEFAULT_WORKFLOW_PATH
        ]
        candidate_artifacts = [
            path for path in candidate_artifacts
            if str(path).startswith(".github/workflows/") and str(path).endswith((".yml", ".yaml"))
        ] or [self.DEFAULT_WORKFLOW_PATH]

        artifacts: dict[str, str] = {}
        statuses: list[dict[str, Any]] = []
        notes: dict[str, str] = {}

        template = self.template_service.load_best_template(runtime_info, normalized_handoff)

        for path in candidate_artifacts:
            workflow_content = self._build_workflow_content(
                path=path,
                runtime_info=runtime_info,
                template=template,
            )
            if workflow_content:
                artifacts[path] = workflow_content
                statuses.append(self._build_status(path, "generated", requested_artifacts))
                notes[path] = f"generated_from_{(template or {}).get('id', 'deterministic_fallback')}"
            else:
                statuses.append(self._build_status(path, "missing", requested_artifacts))
                notes[path] = "missing_runtime_template"

        return artifacts, statuses, notes

    def _build_workflow_content(
        self,
        *,
        path: str,
        runtime_info: dict[str, str],
        template: dict[str, Any] | None,
    ) -> str:
        if template and str(template.get("content") or "").strip():
            return str(template["content"]).strip()

        runtime_name = runtime_info.get("runtime_name")
        if runtime_name == "java":
            return self._build_java_fallback()
        if runtime_name == "node":
            return self._build_node_fallback()
        if runtime_name == "python":
            return self._build_python_fallback()
        if runtime_info.get("dockerized"):
            return self._build_docker_fallback()
        return ""

    def _build_python_fallback(self) -> str:
        return "\n".join(
            [
                "name: Python CI",
                "on:",
                "  push:",
                "    branches: [main, develop]",
                "  pull_request:",
                "    branches: [main]",
                "jobs:",
                "  test:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
                "      - uses: actions/setup-python@v4",
                "        with:",
                "          python-version: '3.11'",
                "          cache: pip",
                "      - run: python -m pip install --upgrade pip",
                "      - run: if [ -f requirements.txt ]; then pip install -r requirements.txt; fi",
                "      - run: if [ -f requirements-backend.txt ]; then pip install -r requirements-backend.txt; fi",
                "      - run: if [ -d tests ]; then python -m unittest discover -s tests; else echo \"No tests directory found\"; fi",
            ]
        )

    def _build_node_fallback(self) -> str:
        return "\n".join(
            [
                "name: Node.js CI",
                "on:",
                "  push:",
                "    branches: [main, develop]",
                "  pull_request:",
                "    branches: [main]",
                "jobs:",
                "  build:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
                "      - uses: actions/setup-node@v4",
                "        with:",
                "          node-version: '20'",
                "          cache: npm",
                "      - run: if [ -f package-lock.json ]; then npm ci; else npm install; fi",
                "      - run: npm run lint --if-present",
                "      - run: npm test --if-present",
                "      - run: npm run build --if-present",
            ]
        )

    def _build_java_fallback(self) -> str:
        return "\n".join(
            [
                "name: Java CI",
                "on:",
                "  push:",
                "    branches: [main, develop]",
                "  pull_request:",
                "    branches: [main]",
                "jobs:",
                "  build:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
                "      - uses: actions/setup-java@v4",
                "        with:",
                "          distribution: temurin",
                "          java-version: '17'",
                "          cache: maven",
                "      - run: if [ -f mvnw ]; then chmod +x mvnw && ./mvnw test; else mvn test; fi",
                "      - run: if [ -f mvnw ]; then ./mvnw -DskipTests package; else mvn -DskipTests package; fi",
            ]
        )

    def _build_docker_fallback(self) -> str:
        return "\n".join(
            [
                "name: Docker Build",
                "on:",
                "  push:",
                "    branches: [main]",
                "jobs:",
                "  build:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
                "      - uses: docker/setup-buildx-action@v2",
                "      - uses: docker/build-push-action@v4",
                "        with:",
                "          context: .",
                "          push: false",
                "          tags: local/${{ github.event.repository.name }}:ci",
            ]
        )

    def _build_status(
        self,
        path: str,
        status: str,
        requested_artifacts: set[str],
    ) -> dict[str, Any]:
        return {
            "path": path,
            "group": "cicd",
            "family": "cicd",
            "status": status,
            "required": path in requested_artifacts,
            "requested": path in requested_artifacts,
            "generated": status == "generated",
            "source": "generated" if status == "generated" else "planned",
        }

    def _detect_framework(
        self,
        frameworks: list[str],
        project_type: str,
        *,
        default: str,
    ) -> str:
        for candidate in ("fastapi", "flask", "django", "react", "vue", "spring boot"):
            if candidate in frameworks or candidate in project_type.lower():
                return candidate
        return default
