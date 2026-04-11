import copy
import os
import subprocess
import unittest
import yaml
from unittest.mock import patch

from backend.app.agents.cicd_agent import CICDAgent


class CICDAgentTests(unittest.TestCase):
    DEFAULT_WORKFLOW = ".github/workflows/ci-cd.yml"

    def setUp(self):
        self.agent = CICDAgent()

    def test_generates_ci_cd_workflow_for_generic_python_repo(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="Python application",
                languages=["Python"],
                frameworks=[],
                key_entrypoints=["app.py"],
            )
        )

        self.assertEqual(result["generated_artifacts"], [self.DEFAULT_WORKFLOW])
        workflow = result["artifacts"][self.DEFAULT_WORKFLOW]
        self.assertIn("actions/setup-python", workflow)
        self.assertEqual(self._status_for(result, self.DEFAULT_WORKFLOW), "generated")
        self.assertEqual(result["validation"]["status"], "valid")
        self._assert_workflow_yaml_is_valid(workflow)

    def test_generates_ci_cd_workflow_for_fastapi_repo(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="FastAPI backend",
                languages=["Python"],
                frameworks=["FastAPI"],
                key_entrypoints=["backend/app/main.py"],
            )
        )

        workflow = result["artifacts"][self.DEFAULT_WORKFLOW]
        self.assertIn("actions/setup-python", workflow)
        self.assertIn("python -m unittest discover", workflow)
        self.assertEqual(result["handoff_context"]["detected_runtime"]["framework"], "fastapi")
        self.assertEqual(self._status_for(result, self.DEFAULT_WORKFLOW), "generated")
        self._assert_workflow_yaml_is_valid(workflow)

    def test_generates_ci_cd_workflow_for_flask_repo(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="Flask backend",
                languages=["Python"],
                frameworks=["Flask"],
                key_entrypoints=["backend/app.py"],
            )
        )

        workflow = result["artifacts"][self.DEFAULT_WORKFLOW]
        self.assertIn("actions/setup-python", workflow)
        self.assertEqual(result["handoff_context"]["detected_runtime"]["framework"], "flask")
        self.assertEqual(self._status_for(result, self.DEFAULT_WORKFLOW), "generated")
        self.assertEqual(result["validation"]["status"], "valid")

    def test_generates_ci_cd_workflow_for_node_repo(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="Node.js application",
                languages=["TypeScript"],
                frameworks=[],
                key_entrypoints=["frontend/src/index.ts"],
            )
        )

        workflow = result["artifacts"][self.DEFAULT_WORKFLOW]
        self.assertIn("actions/setup-node", workflow)
        self.assertIn("npm test --if-present", workflow)
        self.assertEqual(result["handoff_context"]["detected_runtime"]["runtime_name"], "node")
        self.assertEqual(self._status_for(result, self.DEFAULT_WORKFLOW), "generated")
        self._assert_workflow_yaml_is_valid(workflow)

    def test_generates_ci_cd_workflow_for_spring_boot_repo(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="Spring Boot backend",
                languages=["Java"],
                frameworks=["Spring Boot"],
                key_entrypoints=["src/main/java/com/example/DemoApplication.java"],
            )
        )

        workflow = result["artifacts"][self.DEFAULT_WORKFLOW]
        self.assertIn("actions/setup-java", workflow)
        self.assertIn("mvn", workflow.lower())
        self.assertEqual(result["handoff_context"]["detected_runtime"]["runtime_name"], "java")
        self.assertEqual(self._status_for(result, self.DEFAULT_WORKFLOW), "generated")
        self._assert_workflow_yaml_is_valid(workflow)

    def test_repo_with_existing_workflow_is_still_canonicalized_to_generated_contract(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="FastAPI backend",
                languages=["Python"],
                frameworks=["FastAPI"],
                key_entrypoints=["backend/app/main.py"],
                ci_cd_files=[".github/workflows/deploy.yml"],
            )
        )

        self.assertEqual(result["generated_artifacts"], [self.DEFAULT_WORKFLOW])
        self.assertEqual(result["handoff_context"]["existing_cicd_artifacts"], [])
        self.assertEqual(result["handoff_context"]["ci_cd_files"], [self.DEFAULT_WORKFLOW])
        self.assertEqual(self._status_for(result, self.DEFAULT_WORKFLOW), "generated")
        self.assertNotIn(".github/workflows/deploy.yml", result["artifact_groups"]["cicd"])

    def test_ignores_jenkinsfile_and_generates_github_actions_workflow(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="FastAPI backend",
                languages=["Python"],
                frameworks=["FastAPI"],
                key_entrypoints=["backend/app/main.py"],
                ci_cd_files=["Jenkinsfile"],
            )
        )

        self.assertEqual(result["generated_artifacts"], [self.DEFAULT_WORKFLOW])
        self.assertEqual(self._status_for(result, self.DEFAULT_WORKFLOW), "generated")
        self.assertNotIn("Jenkinsfile", result["artifact_groups"]["cicd"])
        self.assertNotIn("Jenkinsfile", result["handoff_context"]["ci_cd_files"])
        self.assertEqual(result["handoff_context"]["existing_cicd_artifacts"], [])

    def test_generic_repo_without_supported_runtime_marks_cicd_missing(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="Unknown project type",
                languages=[],
                frameworks=[],
                key_entrypoints=[],
            )
        )

        self.assertEqual(result["generated_artifacts"], [])
        self.assertEqual(self._status_for(result, self.DEFAULT_WORKFLOW), "missing")
        self.assertEqual(result["validation"]["status"], "partial")
        self.assertNotIn(self.DEFAULT_WORKFLOW, result["artifacts"])

    def test_updates_cicd_group_without_touching_infrastructure(self):
        handoff = self._build_handoff(
            project_type="Flask backend",
            languages=["Python"],
            frameworks=["Flask"],
            key_entrypoints=["backend/app.py"],
        )
        handoff["artifact_groups"]["infrastructure"] = ["Dockerfile", "docker-compose.yml"]
        handoff["artifact_statuses"] = [
            {
                "path": "Dockerfile",
                "group": "infrastructure",
                "family": "dockerfile",
                "status": "required_generated",
                "required": True,
                "requested": True,
                "generated": True,
            }
        ]

        result = self.agent.generate_cicd_artifacts(handoff)

        self.assertEqual(
            result["artifact_groups"]["infrastructure"],
            ["Dockerfile", "docker-compose.yml"],
        )
        self.assertIn(self.DEFAULT_WORKFLOW, result["artifact_groups"]["cicd"])
        self.assertEqual(self._status_for(result, "Dockerfile"), "generated")
        self.assertNotIn("Dockerfile", result["generated_artifacts"])

    def test_respects_artifact_generation_only_mode_and_executes_no_commands(self):
        handoff = self._build_handoff(
            project_type="FastAPI backend",
            languages=["Python"],
            frameworks=["FastAPI"],
            key_entrypoints=["backend/app/main.py"],
        )

        with patch.object(subprocess, "run") as mock_run, patch.object(
            subprocess,
            "Popen",
        ) as mock_popen, patch.object(os, "system") as mock_system:
            result = self.agent.generate_cicd_artifacts(handoff)

        mock_run.assert_not_called()
        mock_popen.assert_not_called()
        mock_system.assert_not_called()
        policy = result["execution_policy"]
        self.assertTrue(policy["artifact_generation_only"])
        self.assertTrue(policy["no_real_deployment"])
        self.assertTrue(policy["non_executing_agent"])
        self.assertFalse(policy["shell_commands_executed"])
        self.assertFalse(policy["tests_executed_by_agent"])

    def test_output_is_deterministic_for_same_handoff(self):
        handoff = self._build_handoff(
            project_type="FastAPI backend",
            languages=["Python"],
            frameworks=["FastAPI"],
            key_entrypoints=["backend/app/main.py"],
        )

        first = self.agent.generate_cicd_artifacts(copy.deepcopy(handoff))
        second = self.agent.generate_cicd_artifacts(copy.deepcopy(handoff))

        self.assertEqual(first, second)

    def test_contract_fields_and_statuses_are_coherent(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="FastAPI backend",
                languages=["Python"],
                frameworks=["FastAPI"],
                key_entrypoints=["backend/app/main.py"],
            )
        )

        self.assertEqual(result["agent"], "CICDAgent")
        self.assertEqual(result["artifact_targets"]["cicd"], [self.DEFAULT_WORKFLOW])
        self.assertEqual(result["requested_artifacts"], [self.DEFAULT_WORKFLOW])
        self.assertIn(self.DEFAULT_WORKFLOW, result["artifact_contract"]["artifact_groups"]["cicd"])

        allowed = {"generated", "missing"}
        cicd_statuses = [item for item in result["artifact_statuses"] if item["group"] == "cicd"]
        self.assertTrue(cicd_statuses)
        for item in cicd_statuses:
            self.assertIn(item["status"], allowed)

        for path in result["generated_artifacts"]:
            self.assertEqual(self._status_for(result, path), "generated")
            self.assertIn(path, result["artifact_groups"]["cicd"])

    def test_validation_reports_stable_readiness_summary(self):
        result = self.agent.generate_cicd_artifacts(
            self._build_handoff(
                project_type="Node.js application",
                languages=["TypeScript"],
                frameworks=[],
                key_entrypoints=["frontend/src/index.ts"],
            )
        )

        self.assertIn("CICD contract valid", result["readiness_summary"])
        self.assertEqual(result["validation"]["status"], "valid")
        self.assertEqual(result["validation"]["diagnostic"]["generated_count"], 1)
        self.assertEqual(result["validation"]["diagnostic"]["missing_count"], 0)

    def _build_handoff(
        self,
        *,
        project_type: str,
        languages: list[str],
        frameworks: list[str],
        key_entrypoints: list[str],
        ci_cd_files: list[str] | None = None,
    ) -> dict:
        package_managers = ["npm/yarn"] if any(
            language in {"TypeScript", "JavaScript", "Node.js"} for language in languages
        ) else ["pip"]
        return {
            "repo_url": None,
            "repo_summary": {
                "project_type": project_type,
                "services": [{"name": "backend", "type": "api"}],
                "runtime": {
                    "languages": languages,
                    "frameworks": frameworks,
                    "package_managers": package_managers,
                },
                "environment_variables": [],
                "sanitized_env_context": {"env_detected": False, "variables": []},
                "key_entrypoints": key_entrypoints,
            },
            "ci_cd_files": ci_cd_files or [],
            "deployment_files": [],
            "key_entrypoints": key_entrypoints,
            "artifact_groups": {
                "infrastructure": [],
                "cicd": [],
                "deployment": [],
                "security": [],
            },
            "artifact_targets": {
                "cicd": [self.DEFAULT_WORKFLOW],
            },
            "requested_artifacts": [
                self.DEFAULT_WORKFLOW,
            ],
            "artifact_statuses": [],
        }

    def _status_for(self, result: dict, path: str) -> str:
        for item in result["artifact_statuses"]:
            if item.get("path") == path:
                return item["status"]
        raise AssertionError(f"Missing status for {path}")

    def _assert_workflow_yaml_is_valid(self, workflow: str) -> None:
        parsed = yaml.safe_load(workflow)
        self.assertIsInstance(parsed, dict)
        self.assertIn("name", parsed)
        self.assertTrue("on" in parsed or True in parsed)
        self.assertIn("jobs", parsed)
        self.assertIsInstance(parsed["jobs"], dict)
        self.assertTrue(parsed["jobs"])


if __name__ == "__main__":
    unittest.main()
