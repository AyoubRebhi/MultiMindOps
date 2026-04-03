import shutil
import unittest
from pathlib import Path

from backend.app.services.artifact_contract_service import ArtifactContractService
from backend.app.services.artifact_quality_validator import ArtifactQualityValidator
from backend.app.services.github_actions_template_service import (
    GitHubActionsTemplateService,
)
from backend.app.services.infrastructure_artifact_builder_service import (
    InfrastructureArtifactBuilderService,
)
from backend.app.services.infrastructure_context_mapper import InfrastructureContextMapper
from backend.app.services.repository_parser_service import RepositoryParserService


class BlocCReadinessTests(unittest.TestCase):
    def setUp(self):
        self.mapper = InfrastructureContextMapper()
        self.builder = InfrastructureArtifactBuilderService()
        self.validator = ArtifactQualityValidator()
        self.contract_service = ArtifactContractService()
        self.template_service = GitHubActionsTemplateService()

    def test_fastapi_postgres_contract_is_generation_only(self):
        context = self._build_infrastructure_context(
            project_type="FastAPI backend",
            services=[
                {
                    "name": "backend",
                    "type": "api",
                    "framework": "FastAPI",
                    "language": "Python",
                    "entrypoint": "backend/app/main.py",
                    "run_command": "uvicorn backend.app.main:app --host 0.0.0.0 --port 8000",
                    "port": 8000,
                    "dependencies": ["postgres"],
                    "environment_variables": ["DATABASE_URL", "GROQ_API_KEY"],
                }
            ],
            environment_variables=[
                self._env_var("DATABASE_URL", "database", "backend", sensitive=True),
                self._env_var("GROQ_API_KEY", "external_api", "backend", sensitive=True),
            ],
            dependencies=[{"name": "postgres", "type": "database"}],
            requested_artifacts=["Dockerfile", "docker-compose.yml", ".env.example"],
        )
        mapped = self.mapper.map(
            prompt="Generate infra",
            plan={"approved_artifacts": ["Dockerfile", "docker-compose.yml", ".env.example"]},
            infrastructure_context=context,
        )
        artifacts = {
            "dockerfile": self.builder.build_dockerfile(mapped),
            "docker_compose": self.builder.build_docker_compose(mapped),
            "env_example": self.builder.build_env_example(mapped),
        }
        validation = self.validator.validate(
            prompt="Generate infra",
            plan={"approved_artifacts": ["Dockerfile", "docker-compose.yml", ".env.example"]},
            infra={
                "artifacts": artifacts,
                "generated_artifacts": ["Dockerfile", "docker-compose.yml", ".env.example"],
                "rag": {"generated_with_rag": False, "fallback_used": True},
            },
            infrastructure_context=context,
            approved_artifacts=["Dockerfile", "docker-compose.yml", ".env.example"],
            env_security_runtime={"sensitive_values": [], "all_values": []},
        )
        contract = self.contract_service.build_contract(
            repo_summary=context["project_summary"],
            categorized_files={"infra_files": [], "ci_cd_files": [], "deployment_files": []},
            key_entrypoints=context["project_summary"]["key_entrypoints"],
            plan={"approved_artifacts": ["Dockerfile", "docker-compose.yml", ".env.example"]},
            infrastructure={
                "generated_artifacts": ["Dockerfile", "docker-compose.yml", ".env.example"],
                "context_used": mapped,
            },
            validation=validation,
        )

        self.assertFalse(contract["execution_policy"]["real_deployment_executed"])
        self.assertIn("Dockerfile", contract["artifact_groups"]["infrastructure"])
        self.assertIn("docker-compose.yml", contract["artifact_groups"]["infrastructure"])
        self.assertEqual(validation["status"], "valid")

    def test_spring_boot_mysql_paths_are_preserved(self):
        requested = [
            "TP-Projet/Dockerfile",
            "docker-compose.yml",
            ".env.example",
            "kubernetes/deployment.yaml",
            "kubernetes/service.yaml",
            "terraform/main.tf",
            "terraform/variables.tf",
            "terraform/output.tf",
        ]
        context = self._build_infrastructure_context(
            project_type="Spring Boot backend",
            services=[
                {
                    "name": "backend",
                    "type": "api",
                    "framework": "Spring Boot",
                    "language": "Java",
                    "entrypoint": "TP-Projet/src/main/java/com/example/DemoApplication.java",
                    "run_command": "./mvnw spring-boot:run",
                    "port": 8080,
                    "dependencies": ["mysql"],
                    "environment_variables": ["MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD"],
                }
            ],
            environment_variables=[
                self._env_var("MYSQL_DATABASE", "database", "backend", sensitive=False),
                self._env_var("MYSQL_USER", "database", "backend", sensitive=False),
                self._env_var("MYSQL_PASSWORD", "database", "backend", sensitive=True),
            ],
            dependencies=[{"name": "mysql", "type": "database"}],
            requested_artifacts=requested,
        )
        mapped = self.mapper.map(
            prompt="Generate infra",
            plan={"approved_artifacts": requested},
            infrastructure_context=context,
        )

        self.assertEqual(mapped["artifact_targets"]["dockerfile"], "TP-Projet/Dockerfile")
        self.assertIn("kubernetes/deployment.yaml", mapped["artifact_targets"]["kubernetes"])
        self.assertIn("terraform/output.tf", mapped["artifact_targets"]["terraform"])

    def test_backend_only_does_not_require_compose_without_dependencies(self):
        context = self._build_infrastructure_context(
            project_type="Flask backend",
            services=[
                {
                    "name": "backend",
                    "type": "api",
                    "framework": "Flask",
                    "language": "Python",
                    "entrypoint": "backend/app.py",
                    "run_command": "python backend/app.py",
                    "port": 5000,
                    "dependencies": [],
                    "environment_variables": [],
                }
            ],
            environment_variables=[],
            dependencies=[],
            requested_artifacts=["Dockerfile"],
        )
        mapped = self.mapper.map(
            prompt="Generate infra",
            plan={"approved_artifacts": ["Dockerfile"]},
            infrastructure_context=context,
        )
        self.assertFalse(mapped["artifact_expectations"]["needs_docker_compose"])
        self.assertTrue(mapped["artifact_expectations"]["needs_dockerfile"])

    def test_kubernetes_family_can_be_marked_partial(self):
        family_statuses = self.contract_service.build_family_statuses(
            requested_artifacts=[
                "kubernetes/deployment.yaml",
                "kubernetes/service.yaml",
                "kubernetes/configmap.yaml",
            ],
            generated_artifacts=["kubernetes/deployment.yaml"],
        )
        kubernetes_status = next(
            item for item in family_statuses if item["family"] == "kubernetes"
        )
        self.assertEqual(kubernetes_status["status"], "partial")
        self.assertIn("kubernetes/service.yaml", kubernetes_status["missing"])

    def test_terraform_family_complete_when_all_files_generated(self):
        family_statuses = self.contract_service.build_family_statuses(
            requested_artifacts=[
                "terraform/main.tf",
                "terraform/variables.tf",
                "terraform/output.tf",
            ],
            generated_artifacts=[
                "terraform/main.tf",
                "terraform/variables.tf",
                "terraform/output.tf",
            ],
        )
        terraform_status = next(
            item for item in family_statuses if item["family"] == "terraform"
        )
        self.assertEqual(terraform_status["status"], "complete")

    def test_uploaded_env_is_merged_and_sanitized(self):
        repo = Path("workspace/test_bloc_c_uploaded_env")
        if repo.exists():
            shutil.rmtree(repo)
        (repo / "backend").mkdir(parents=True)
        (repo / ".env").write_text(
            "APP_ENV=prod\nDATABASE_URL=postgres://repo_secret\n",
            encoding="utf-8",
        )
        (repo / "backend" / "app.py").write_text(
            'import os\nos.getenv("APP_ENV")\nos.getenv("DATABASE_URL")\nos.getenv("GROQ_API_KEY")\n',
            encoding="utf-8",
        )
        uploaded_env = {
            "filename": ".env.local",
            "content": b"APP_ENV=dev\nGROQ_API_KEY=gsk_live_secret\n",
            "content_type": "text/plain",
            "source": "uploaded",
        }
        try:
            parsed = RepositoryParserService().parse_repository(
                str(repo),
                uploaded_env=uploaded_env,
            )
            sanitized_context = parsed["project_summary"]["sanitized_env_context"]
            variables = {item["name"]: item for item in sanitized_context["variables"]}

            self.assertEqual(sanitized_context["source"], "merged")
            self.assertEqual(variables["APP_ENV"]["sanitized_value"], "dev")
            self.assertTrue(variables["GROQ_API_KEY"]["is_sensitive"])
            self.assertNotIn("gsk_live_secret", str(sanitized_context))
            self.assertNotIn("repo_secret", str(sanitized_context))
        finally:
            if repo.exists():
                shutil.rmtree(repo)

    def test_uploaded_env_prevents_env_example_regeneration_requirement(self):
        context = self._build_infrastructure_context(
            project_type="FastAPI backend",
            services=[
                {
                    "name": "backend",
                    "type": "api",
                    "framework": "FastAPI",
                    "language": "Python",
                    "entrypoint": "backend/app/main.py",
                    "run_command": "uvicorn backend.app.main:app --host 0.0.0.0 --port 8000",
                    "port": 8000,
                    "dependencies": [],
                    "environment_variables": ["APP_ENV", "GROQ_API_KEY"],
                }
            ],
            environment_variables=[
                self._env_var("APP_ENV", "deployment", "backend", sensitive=False),
                self._env_var("GROQ_API_KEY", "external_api", "backend", sensitive=True),
            ],
            dependencies=[],
            requested_artifacts=["Dockerfile", ".env.example"],
        )
        context["uploaded_env_provided"] = True
        context["env_files"] = [
            {
                "path": "uploaded/.env.example.test",
                "name": ".env.example.test",
                "source": "uploaded",
                "file_hash": "abc123",
                "variable_count": 2,
                "sensitive_variables_count": 1,
            }
        ]
        context["sanitized_env_context"]["source"] = "uploaded"
        context["project_summary"]["sanitized_env_context"]["source"] = "uploaded"

        mapped = self.mapper.map(
            prompt="Generate infra",
            plan={"approved_artifacts": ["Dockerfile", ".env.example"]},
            infrastructure_context=context,
        )
        validation = self.validator.validate(
            prompt="Generate infra",
            plan={"approved_artifacts": ["Dockerfile", ".env.example"]},
            infra={
                "artifacts": {
                    "dockerfile": "FROM python:3.11-slim\n",
                },
                "generated_artifacts": ["Dockerfile"],
                "rag": {"generated_with_rag": False, "fallback_used": True},
            },
            infrastructure_context=context,
            approved_artifacts=["Dockerfile", ".env.example"],
            env_security_runtime={"sensitive_values": [], "all_values": []},
        )
        contract = self.contract_service.build_contract(
            repo_summary=context["project_summary"],
            categorized_files={"infra_files": [], "ci_cd_files": [], "deployment_files": []},
            key_entrypoints=context["project_summary"]["key_entrypoints"],
            plan={"approved_artifacts": ["Dockerfile", ".env.example"]},
            infrastructure={
                "generated_artifacts": ["Dockerfile"],
                "artifacts": {"dockerfile": "FROM python:3.11-slim\n"},
                "context_used": mapped,
            },
            validation=validation,
        )

        env_status = next(item for item in contract["artifact_statuses"] if item["path"] == ".env.example")
        self.assertFalse(mapped["artifact_expectations"]["needs_env_example"])
        self.assertEqual(env_status["status"], "detected")
        self.assertEqual(env_status["source"], "uploaded")
        self.assertFalse(
            any(".env.example should be generated" in issue for issue in validation["quality_issues"])
        )
        self.assertNotIn(".env.example", contract["missing_artifacts"])
        self.assertNotIn(".env.example", contract["generated_artifacts"])

    def test_uploaded_env_keeps_env_example_out_of_final_generated_contract(self):
        context = self._build_infrastructure_context(
            project_type="FastAPI backend",
            services=[
                {
                    "name": "backend",
                    "type": "api",
                    "framework": "FastAPI",
                    "language": "Python",
                    "entrypoint": "backend/app/main.py",
                    "run_command": "uvicorn backend.app.main:app --host 0.0.0.0 --port 8000",
                    "port": 8000,
                    "dependencies": [],
                    "environment_variables": ["APP_ENV", "GROQ_API_KEY"],
                }
            ],
            environment_variables=[
                self._env_var("APP_ENV", "deployment", "backend", sensitive=False),
                self._env_var("GROQ_API_KEY", "external_api", "backend", sensitive=True),
            ],
            dependencies=[],
            requested_artifacts=["Dockerfile", ".env.example"],
        )
        context["uploaded_env_provided"] = True
        context["env_files"] = [
            {
                "path": "uploaded/.env.example.test",
                "name": ".env.example.test",
                "source": "uploaded",
                "file_hash": "abc123",
                "variable_count": 2,
                "sensitive_variables_count": 1,
            }
        ]
        context["sanitized_env_context"]["source"] = "uploaded"
        context["project_summary"]["sanitized_env_context"]["source"] = "uploaded"

        mapped = self.mapper.map(
            prompt="Generate infra",
            plan={"approved_artifacts": ["Dockerfile", ".env.example"]},
            infrastructure_context=context,
        )
        artifacts = {
            "dockerfile": self.builder.build_dockerfile(mapped),
            "env_example": self.builder.build_env_example(mapped),
        }
        contract = self.contract_service.build_contract(
            repo_summary=context["project_summary"],
            categorized_files={"infra_files": [], "ci_cd_files": [], "deployment_files": []},
            key_entrypoints=context["project_summary"]["key_entrypoints"],
            plan={"approved_artifacts": ["Dockerfile", ".env.example"]},
            infrastructure={
                "generated_artifacts": ["Dockerfile"],
                "artifacts": artifacts,
                "context_used": mapped,
            },
            validation={"required_artifacts": ["Dockerfile", ".env.example"]},
        )

        self.assertFalse(mapped["artifact_expectations"]["needs_env_example"])
        self.assertEqual(
            next(item for item in contract["artifact_statuses"] if item["path"] == ".env.example")["source"],
            "uploaded",
        )
        self.assertNotIn(".env.example", contract["generated_artifacts"])
        self.assertNotIn(".env.example", contract["missing_artifacts"])

    def test_github_actions_templates_are_available_from_local_rag(self):
        templates = self.template_service.list_templates()
        self.assertIn("python_ci", templates)
        self.assertIn("spring_boot_ci", templates)

        template = self.template_service.load_best_template(
            {"runtime_name": "java", "language": "Java", "framework": "Spring Boot"},
            {"repo_summary": {"stack": {"devops_tools": []}}, "artifact_groups": {"infrastructure": []}},
        )

        self.assertIsNotNone(template)
        self.assertEqual(template["id"], "spring_boot_ci")
        self.assertIn("setup-java", template["content"])

    def test_no_env_remains_supported(self):
        repo = Path("workspace/test_bloc_c_no_env")
        if repo.exists():
            shutil.rmtree(repo)
        (repo / "backend").mkdir(parents=True)
        (repo / "backend" / "app.py").write_text(
            'print("hello")\n',
            encoding="utf-8",
        )
        try:
            parsed = RepositoryParserService().parse_repository(str(repo))
            sanitized_context = parsed["project_summary"]["sanitized_env_context"]
            self.assertFalse(sanitized_context["env_detected"])
            self.assertEqual(sanitized_context["variables"], [])
        finally:
            if repo.exists():
                shutil.rmtree(repo)

    def _build_infrastructure_context(
        self,
        *,
        project_type: str,
        services: list[dict],
        environment_variables: list[dict],
        dependencies: list[dict],
        requested_artifacts: list[str],
    ) -> dict:
        return {
            "project_summary": {
                "project_type": project_type,
                "services": services,
                "environment_variables": environment_variables,
                "runtime": {
                    "languages": [services[0]["language"]] if services else [],
                    "frameworks": [services[0]["framework"]] if services else [],
                },
                "key_entrypoints": [service["entrypoint"] for service in services if service.get("entrypoint")],
                "sanitized_env_context": {
                    "env_detected": bool(environment_variables),
                    "source": "repository",
                    "variables": environment_variables,
                },
            },
            "services": services,
            "environment_variables": environment_variables,
            "commands": [
                {
                    "command": service.get("run_command"),
                    "service": service.get("name"),
                    "source_file": service.get("entrypoint"),
                }
                for service in services
            ],
            "runtime": {
                "languages": [service["language"] for service in services],
                "frameworks": [service["framework"] for service in services],
                "package_managers": ["pip" if services and services[0]["language"] == "Python" else "maven"],
                "dependency_files": ["requirements.txt" if services and services[0]["language"] == "Python" else "pom.xml"],
            },
            "env_files": [],
            "env_fingerprint": None,
            "sanitized_env_context": {
                "env_detected": bool(environment_variables),
                "source": "repository",
                "variables": environment_variables,
            },
            "infrastructure_dependencies": dependencies,
            "infrastructure_needs": [item["name"] for item in dependencies],
            "uploaded_env_provided": False,
            "requested_artifacts": requested_artifacts,
        }

    def _env_var(self, name: str, category: str, service: str, *, sensitive: bool) -> dict:
        return {
            "name": name,
            "category": category,
            "service": service,
            "required": not sensitive,
            "default": None,
            "existing_in_env": True,
            "has_value": True,
            "is_sensitive": sensitive,
            "sanitized_value": None if sensitive else "",
            "used_for_generation": True,
            "env_source": "repository",
            "source_file": ".env",
        }


if __name__ == "__main__":
    unittest.main()
