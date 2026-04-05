import copy
import unittest

from backend.app.agents.orchestrator_agent import OrchestratorAgent
from backend.app.agents.cicd_agent import CICDAgent
from backend.app.services.cicd.artifact_contract_service import ArtifactContractService


class ArtifactContractConsistencyTests(unittest.TestCase):
    DEFAULT_WORKFLOW = ".github/workflows/ci-cd.yml"

    def setUp(self):
        self.contract_service = ArtifactContractService()
        self.cicd_agent = CICDAgent()

    def test_generated_workflow_is_not_missing_and_sets_has_cicd(self):
        result = self.cicd_agent.generate_cicd_artifacts(
            self._build_cicd_handoff(
                project_type="FastAPI backend",
                languages=["Python"],
                frameworks=["FastAPI"],
                key_entrypoints=["backend/app/main.py"],
            )
        )

        contract = result["artifact_contract"]
        self.assertEqual(self._status_for(contract["artifact_statuses"], self.DEFAULT_WORKFLOW), "generated")
        self.assertNotIn(self.DEFAULT_WORKFLOW, contract["missing_artifacts"])
        self.assertIn(self.DEFAULT_WORKFLOW, contract["generated_artifacts"])
        self.assertTrue(contract["has_ci_cd"])
        self.assertEqual(contract["ci_cd_files"], [self.DEFAULT_WORKFLOW])
        self.assertEqual(contract["existing_cicd_artifacts"], [])

    def test_uploaded_env_resolves_env_artifact_without_generation(self):
        contract = self.contract_service.build_contract(
            repo_summary={
                "project_type": "FastAPI backend",
                "runtime": {"languages": ["Python"], "frameworks": ["FastAPI"]},
                "services": [{"name": "backend", "type": "api"}],
            },
            categorized_files={},
            key_entrypoints=["backend/app/main.py"],
            plan={"approved_artifacts": [".env.example", "Dockerfile"]},
            infrastructure={
                "generated_artifacts": ["Dockerfile"],
                "artifacts": {"dockerfile": "FROM python:3.11-slim\n"},
                "context_used": {
                    "requested_artifacts": [".env.example", "Dockerfile"],
                    "artifact_targets": {
                        "dockerfile": "Dockerfile",
                        "env_files": [".env.example"],
                    },
                    "uploaded_env_provided": True,
                    "uploaded_env_files": [
                        {
                            "path": "uploaded/.env.example.test",
                            "source": "uploaded",
                            "file_hash": "abc123",
                        }
                    ],
                },
            },
            validation={"required_artifacts": [".env.example", "Dockerfile"]},
        )

        env_status = next(item for item in contract["artifact_statuses"] if item["path"] == ".env.example")
        self.assertEqual(env_status["status"], "detected")
        self.assertEqual(env_status["source"], "uploaded")
        self.assertFalse(env_status["generated"])
        self.assertNotIn(".env.example", contract["missing_artifacts"])
        self.assertNotIn(".env.example", contract["generated_artifacts"])
        self.assertEqual(self._status_for(contract["artifact_statuses"], "Dockerfile"), "generated")

    def test_uploaded_env_overrides_accidental_generated_env_status(self):
        contract = self.contract_service.build_contract(
            repo_summary={
                "project_type": "FastAPI backend",
                "runtime": {"languages": ["Python"], "frameworks": ["FastAPI"]},
                "services": [{"name": "backend", "type": "api"}],
            },
            categorized_files={},
            key_entrypoints=["backend/app/main.py"],
            plan={"approved_artifacts": [".env.example", "Dockerfile"]},
            infrastructure={
                "generated_artifacts": ["Dockerfile", ".env.example"],
                "artifacts": {
                    "dockerfile": "FROM python:3.11-slim\n",
                    "env_example": "APP_ENV=dev\n",
                },
                "context_used": {
                    "requested_artifacts": [".env.example", "Dockerfile"],
                    "artifact_targets": {
                        "dockerfile": "Dockerfile",
                        "env_files": [".env.example"],
                    },
                    "uploaded_env_provided": True,
                    "uploaded_env_files": [
                        {
                            "path": "uploaded/.env.example.test",
                            "source": "uploaded",
                            "file_hash": "abc123",
                        }
                    ],
                    "resolved_env_artifact_paths": [".env.example"],
                    "env_source_of_truth": "uploaded",
                },
            },
            validation={"required_artifacts": [".env.example", "Dockerfile"]},
        )

        env_status = next(item for item in contract["artifact_statuses"] if item["path"] == ".env.example")
        self.assertEqual(env_status["status"], "detected")
        self.assertEqual(env_status["source"], "uploaded")
        self.assertFalse(env_status["generated"])
        self.assertNotIn(".env.example", contract["generated_artifacts"])
        self.assertNotIn(".env.example", contract["missing_artifacts"])

    def test_jenkinsfile_does_not_satisfy_cicd_contract(self):
        contract = self.contract_service.build_contract(
            repo_summary={"project_type": "FastAPI backend"},
            categorized_files={"ci_cd_files": ["Jenkinsfile"]},
            key_entrypoints=["backend/app/main.py"],
            plan={"approved_artifacts": [self.DEFAULT_WORKFLOW]},
            infrastructure={"generated_artifacts": [], "context_used": {}},
            validation={"required_artifacts": [self.DEFAULT_WORKFLOW]},
            artifact_statuses=[
                {
                    "path": "Jenkinsfile",
                    "group": "cicd",
                    "family": "cicd",
                    "status": "detected",
                    "required": False,
                    "requested": False,
                    "generated": False,
                }
            ],
            artifact_targets={"cicd": [self.DEFAULT_WORKFLOW]},
            requested_artifacts=[self.DEFAULT_WORKFLOW],
        )

        self.assertFalse(contract["has_ci_cd"])
        self.assertEqual(contract["artifact_groups"]["cicd"], [self.DEFAULT_WORKFLOW])
        self.assertEqual(contract["ci_cd_files"], [])
        self.assertEqual(contract["existing_cicd_artifacts"], [])
        self.assertEqual(self._status_for(contract["artifact_statuses"], self.DEFAULT_WORKFLOW), "missing")

    def test_infrastructure_artifacts_present_in_payload_become_generated(self):
        contract = self.contract_service.build_contract(
            repo_summary={
                "project_type": "FastAPI backend",
                "runtime": {"languages": ["Python"], "frameworks": ["FastAPI"]},
                "services": [{"name": "backend", "type": "api"}],
            },
            categorized_files={},
            key_entrypoints=["backend/app/main.py"],
            plan={
                "approved_artifacts": [
                    ".env.example",
                    "Dockerfile",
                    "docker-compose.yml",
                    "kubernetes/deployment.yaml",
                    "terraform/main.tf",
                ]
            },
            infrastructure={
                "generated_artifacts": [],
                "artifacts": {
                    "env_example": "APP_ENV=\n",
                    "dockerfile": "FROM python:3.11-slim\n",
                    "docker_compose": "services:\n  backend:\n",
                    "kubernetes_deployment": "apiVersion: apps/v1\nkind: Deployment\n",
                    "terraform_main": 'terraform {}\nresource "docker_image" "backend" {}\n',
                },
                "context_used": {
                    "requested_artifacts": [
                        ".env.example",
                        "Dockerfile",
                        "docker-compose.yml",
                        "kubernetes/deployment.yaml",
                        "terraform/main.tf",
                    ],
                    "artifact_targets": {
                        "dockerfile": "Dockerfile",
                        "docker_compose": "docker-compose.yml",
                        "env_files": [".env.example"],
                        "kubernetes": ["kubernetes/deployment.yaml"],
                        "terraform": ["terraform/main.tf"],
                    },
                },
            },
            validation={"required_artifacts": [
                ".env.example",
                "Dockerfile",
                "docker-compose.yml",
                "kubernetes/deployment.yaml",
                "terraform/main.tf",
            ]},
        )

        for path in [
            ".env.example",
            "Dockerfile",
            "docker-compose.yml",
            "kubernetes/deployment.yaml",
            "terraform/main.tf",
        ]:
            self.assertEqual(self._status_for(contract["artifact_statuses"], path), "generated")
            self.assertIn(path, contract["generated_artifacts"])
            self.assertNotIn(path, contract["missing_artifacts"])

        families = {item["family"]: item for item in contract["artifact_family_statuses"]}
        self.assertEqual(families["env"]["status"], "complete")
        self.assertEqual(families["dockerfile"]["status"], "complete")
        self.assertEqual(families["docker_compose"]["status"], "complete")
        self.assertEqual(families["kubernetes"]["status"], "complete")
        self.assertEqual(families["terraform"]["status"], "complete")

    def test_final_contract_is_globally_consistent_after_orchestrator_finalize(self):
        orchestrator = OrchestratorAgent()
        state = {
            "logs": [],
            "repository_security": {"status": "safe"},
            "repository_analysis": None,
            "repo_summary": {
                "project_type": "FastAPI backend",
                "runtime": {"languages": ["Python"], "frameworks": ["FastAPI"]},
                "services": [{"name": "backend", "type": "api"}],
                "key_entrypoints": ["backend/app/main.py"],
                "has_ci_cd": False,
                "ci_cd_files": [],
            },
            "categorized_files": {
                "ci_cd_files": [],
                "deployment_files": [],
            },
            "key_entrypoints": ["backend/app/main.py"],
            "plan": {
                "approved_artifacts": ["Dockerfile", ".env.example", self.DEFAULT_WORKFLOW],
                "required_artifacts": ["Dockerfile", ".env.example", self.DEFAULT_WORKFLOW],
            },
            "infra": {
                "generated_artifacts": ["Dockerfile", ".env.example"],
                "artifacts": {
                    "dockerfile": "FROM python:3.11-slim\n",
                    "env_example": "APP_ENV=\n",
                },
                "context_used": {
                    "requested_artifacts": ["Dockerfile", ".env.example", self.DEFAULT_WORKFLOW],
                    "artifact_targets": {
                        "dockerfile": "Dockerfile",
                        "env_files": [".env.example"],
                    },
                },
            },
            "validation": {
                "status": "partial",
                "required_artifacts": ["Dockerfile", ".env.example", self.DEFAULT_WORKFLOW],
                "generated_artifacts": ["Dockerfile", ".env.example"],
                "missing_artifacts": [self.DEFAULT_WORKFLOW],
                "quality_issues": [],
                "warnings": [],
                "artifact_statuses": [
                    {
                        "path": "Dockerfile",
                        "group": "infrastructure",
                        "family": "dockerfile",
                        "status": "required_generated",
                        "required": True,
                        "requested": True,
                        "generated": True,
                    },
                    {
                        "path": ".env.example",
                        "group": "infrastructure",
                        "family": "env",
                        "status": "required_generated",
                        "required": True,
                        "requested": True,
                        "generated": True,
                    },
                    {
                        "path": self.DEFAULT_WORKFLOW,
                        "group": "cicd",
                        "family": "cicd",
                        "status": "required_missing",
                        "required": True,
                        "requested": True,
                        "generated": False,
                    },
                ],
                "generated_with_rag": False,
                "fallback_used": False,
                "template_ids_used": [],
            },
            "cicd": {
                "requested_artifacts": [self.DEFAULT_WORKFLOW],
                "artifact_targets": {"cicd": [self.DEFAULT_WORKFLOW]},
                "generated_artifacts": [self.DEFAULT_WORKFLOW],
                "artifact_statuses": [
                    {
                        "path": self.DEFAULT_WORKFLOW,
                        "group": "cicd",
                        "family": "cicd",
                        "status": "generated",
                        "required": True,
                        "requested": True,
                        "generated": True,
                        "source": "generated",
                    }
                ],
                "validation": {
                    "status": "valid",
                    "issues": [],
                    "warnings": [],
                },
            },
        }

        finalized = orchestrator._finalize_node(copy.deepcopy(state))
        result = finalized["result"]
        contract = result["artifact_contract"]

        self.assertTrue(contract["has_ci_cd"])
        self.assertEqual(contract["ci_cd_files"], [self.DEFAULT_WORKFLOW])
        self.assertEqual(contract["artifact_groups"]["cicd"], [self.DEFAULT_WORKFLOW])
        self.assertEqual(contract["existing_cicd_artifacts"], [])
        self.assertNotIn(self.DEFAULT_WORKFLOW, contract["missing_artifacts"])
        self.assertIn(self.DEFAULT_WORKFLOW, contract["generated_artifacts"])
        self.assertIn("Dockerfile", contract["generated_artifacts"])
        self.assertIn(".env.example", contract["generated_artifacts"])
        self.assertEqual(result["validation"]["missing_artifacts"], [])
        self.assertEqual(result["validation"]["status"], "valid")

    def test_contract_consolidation_is_deterministic(self):
        contract_kwargs = {
            "repo_summary": {
                "project_type": "FastAPI backend",
                "runtime": {"languages": ["Python"], "frameworks": ["FastAPI"]},
                "services": [{"name": "backend", "type": "api"}],
            },
            "categorized_files": {"ci_cd_files": []},
            "key_entrypoints": ["backend/app/main.py"],
            "plan": {"approved_artifacts": ["Dockerfile", self.DEFAULT_WORKFLOW]},
            "infrastructure": {
                "generated_artifacts": ["Dockerfile"],
                "context_used": {
                    "requested_artifacts": ["Dockerfile", self.DEFAULT_WORKFLOW],
                    "artifact_targets": {"dockerfile": "Dockerfile", "cicd": [self.DEFAULT_WORKFLOW]},
                },
            },
            "validation": {"required_artifacts": ["Dockerfile", self.DEFAULT_WORKFLOW]},
            "artifact_statuses": [
                {
                    "path": "Dockerfile",
                    "status": "required_generated",
                    "required": True,
                    "requested": True,
                    "generated": True,
                },
                {
                    "path": self.DEFAULT_WORKFLOW,
                    "status": "generated",
                    "required": True,
                    "requested": True,
                    "generated": True,
                },
            ],
            "artifact_targets": {"dockerfile": "Dockerfile", "cicd": [self.DEFAULT_WORKFLOW]},
            "requested_artifacts": ["Dockerfile", self.DEFAULT_WORKFLOW],
        }

        first = self.contract_service.build_contract(**copy.deepcopy(contract_kwargs))
        second = self.contract_service.build_contract(**copy.deepcopy(contract_kwargs))

        self.assertEqual(first, second)

    def test_final_cicd_group_contains_only_github_actions_workflows(self):
        contract = self.contract_service.build_contract(
            repo_summary={"project_type": "FastAPI backend"},
            categorized_files={"ci_cd_files": ["Jenkinsfile", self.DEFAULT_WORKFLOW]},
            key_entrypoints=["backend/app/main.py"],
            plan={"approved_artifacts": [self.DEFAULT_WORKFLOW]},
            infrastructure={"generated_artifacts": [self.DEFAULT_WORKFLOW], "context_used": {}},
            validation={"required_artifacts": [self.DEFAULT_WORKFLOW]},
            artifact_statuses=[
                {
                    "path": "Jenkinsfile",
                    "group": "cicd",
                    "family": "cicd",
                    "status": "detected",
                    "required": False,
                    "requested": False,
                    "generated": False,
                },
                {
                    "path": self.DEFAULT_WORKFLOW,
                    "group": "cicd",
                    "family": "cicd",
                    "status": "generated",
                    "required": True,
                    "requested": True,
                    "generated": True,
                },
            ],
            artifact_targets={"cicd": [self.DEFAULT_WORKFLOW]},
            requested_artifacts=[self.DEFAULT_WORKFLOW],
        )

        self.assertEqual(contract["artifact_groups"]["cicd"], [self.DEFAULT_WORKFLOW])
        self.assertEqual(contract["ci_cd_files"], [self.DEFAULT_WORKFLOW])
        self.assertNotIn("Jenkinsfile", contract["artifact_groups"]["cicd"])
        self.assertEqual(contract["existing_cicd_artifacts"], [])

    def _build_cicd_handoff(
        self,
        *,
        project_type: str,
        languages: list[str],
        frameworks: list[str],
        key_entrypoints: list[str],
    ) -> dict:
        return {
            "repo_summary": {
                "project_type": project_type,
                "runtime": {"languages": languages, "frameworks": frameworks},
                "services": [{"name": "backend", "type": "api"}],
                "key_entrypoints": key_entrypoints,
            },
            "ci_cd_files": [],
            "deployment_files": [],
            "key_entrypoints": key_entrypoints,
            "artifact_groups": {
                "infrastructure": [],
                "cicd": [],
                "deployment": [],
                "security": [],
            },
            "artifact_targets": {"cicd": [self.DEFAULT_WORKFLOW]},
            "requested_artifacts": [self.DEFAULT_WORKFLOW],
            "artifact_statuses": [],
        }

    def _status_for(self, statuses: list[dict], path: str) -> str:
        for item in statuses:
            if item.get("path") == path:
                return item["status"]
        raise AssertionError(f"Missing status for {path}")


if __name__ == "__main__":
    unittest.main()
