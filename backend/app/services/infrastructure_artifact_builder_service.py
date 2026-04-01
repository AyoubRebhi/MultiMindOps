from pathlib import Path
from typing import Any


class InfrastructureArtifactBuilderService:
    def build_fallback_artifacts(self, mapped_context: dict[str, Any]) -> dict[str, str]:
        return {
            "dockerfile": self.build_dockerfile(mapped_context),
            "dockerignore": self.build_dockerignore(mapped_context),
            "docker_compose": self.build_docker_compose(mapped_context),
            "env_example": self.build_env_example(mapped_context),
            "kubernetes_manifests": self.build_kubernetes_manifests(mapped_context),
            "kubernetes_deployment": self.build_kubernetes_deployment(mapped_context),
            "kubernetes_service": self.build_kubernetes_service(mapped_context),
            "kubernetes_configmap": self.build_kubernetes_configmap(mapped_context),
            "terraform_main": self.build_terraform_main(mapped_context),
            "terraform_variables": self.build_terraform_variables(mapped_context),
            "terraform_outputs": self.build_terraform_outputs(mapped_context),
        }

    def build_env_example(self, mapped_context: dict[str, Any]) -> str:
        env_template = mapped_context.get("environment_template") or []
        if not env_template:
            return ""

        sections: dict[str, list[str]] = {}
        for item in env_template:
            category = item.get("category", "app")
            sections.setdefault(category, []).append(f"{item['name']}=")

        lines = []
        for category in ("app", "database", "cache", "queue", "external_api", "deployment", "secret"):
            entries = sections.get(category)
            if not entries:
                continue
            lines.append(f"# {category}")
            lines.extend(sorted(set(entries)))
            lines.append("")
        return "\n".join(lines).strip()

    def build_dockerignore(self, mapped_context: dict[str, Any]) -> str:
        runtime = mapped_context.get("runtime") or {}
        exclude_paths = runtime.get("exclude_paths") or []
        defaults = [".git", "__pycache__", "*.pyc", ".env", "venv/", ".history/", "workspace/"]
        lines = sorted(set(defaults + [f"{path}/" if "/" not in path and not path.endswith("/") else path for path in exclude_paths]))
        return "\n".join(lines)

    def build_dockerfile(self, mapped_context: dict[str, Any]) -> str:
        if not mapped_context.get("artifact_expectations", {}).get("needs_dockerfile"):
            return ""

        runtime = mapped_context.get("runtime") or {}
        main_service = mapped_context.get("main_service") or {}
        language = (main_service.get("language") or "").lower()
        dependency_files = runtime.get("dependency_files") or []
        build_context = mapped_context.get("build_context") or "."
        dependency_file = next((path for path in dependency_files if "requirements-backend" in path.lower()), None)
        if not dependency_file:
            dependency_file = dependency_files[0] if dependency_files else "requirements.txt"

        if language == "java":
            return self._build_java_dockerfile(mapped_context, dependency_file)

        port = main_service.get("port") or 8000
        run_command = main_service.get("run_command") or "python app.py"
        cmd = self._command_to_docker_cmd(run_command)
        copy_instruction = self._python_dependency_copy_line(build_context, dependency_file)
        install_instruction = self._python_install_line(dependency_file)
        lines = [
            "FROM python:3.11-slim",
            "",
            "WORKDIR /app",
            "",
            copy_instruction,
            install_instruction,
            "",
            "COPY . .",
            "",
            "ENV PYTHONUNBUFFERED=1",
            f"EXPOSE {port}",
            cmd,
        ]
        return "\n".join(lines)

    def _build_java_dockerfile(
        self,
        mapped_context: dict[str, Any],
        dependency_file: str,
    ) -> str:
        main_service = mapped_context.get("main_service") or {}
        port = main_service.get("port") or 8080
        runtime = mapped_context.get("runtime") or {}
        build_context = mapped_context.get("build_context") or "."
        dependency_files = runtime.get("dependency_files") or []
        pom_file = next((path for path in dependency_files if Path(path).name.lower() == "pom.xml"), dependency_file)
        has_wrapper = any(Path(path).name.lower() == "mvnw" for path in dependency_files)
        build_tool = "./mvnw" if has_wrapper else "mvn"

        lines = [
            "FROM maven:3.9-eclipse-temurin-17 AS build",
            "",
            "WORKDIR /app",
            "",
            f"COPY {Path(pom_file).name} ./{Path(pom_file).name}",
            "COPY mvnw ./mvnw" if has_wrapper else "",
            "RUN chmod +x ./mvnw" if has_wrapper else "",
            "COPY . .",
            f"RUN {build_tool} -DskipTests package",
            "",
            "FROM eclipse-temurin:17-jre",
            "",
            "WORKDIR /app",
            "COPY --from=build /app/target/*.jar app.jar",
            f"EXPOSE {port}",
            'ENTRYPOINT ["java", "-jar", "/app/app.jar"]',
        ]
        return "\n".join(lines)

    def build_docker_compose(self, mapped_context: dict[str, Any]) -> str:
        if not mapped_context.get("artifact_expectations", {}).get("needs_docker_compose"):
            return ""

        services = mapped_context.get("services") or []
        env_template = mapped_context.get("environment_template") or []
        infra_dependencies = mapped_context.get("infrastructure_dependencies") or []
        lines = ["services:"]

        dependency_names = {item["name"] for item in infra_dependencies}
        has_postgres = "postgres" in dependency_names
        has_mysql = "mysql" in dependency_names

        for service in services:
            lines.extend(
                self._compose_service_block(
                    service,
                    env_template,
                    has_postgres,
                    has_mysql,
                    mapped_context.get("artifact_targets") or {},
                    mapped_context.get("build_context") or ".",
                )
            )

        if has_postgres:
            lines.extend(
                [
                    "  db:",
                    "    image: postgres:15",
                    "    restart: unless-stopped",
                    "    environment:",
                    "      POSTGRES_USER: ${POSTGRES_USER}",
                    "      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}",
                    "      POSTGRES_DB: ${POSTGRES_DB}",
                    "    ports:",
                    "      - \"5432:5432\"",
                    "    volumes:",
                    "      - postgres_data:/var/lib/postgresql/data",
                ]
            )
        if has_mysql:
            lines.extend(
                [
                    "  db:",
                    "    image: mysql:8.0",
                    "    restart: unless-stopped",
                    "    environment:",
                    "      MYSQL_DATABASE: ${MYSQL_DATABASE}",
                    "      MYSQL_USER: ${MYSQL_USER}",
                    "      MYSQL_PASSWORD: ${MYSQL_PASSWORD}",
                    "      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}",
                    "    ports:",
                    '      - "3306:3306"',
                    "    volumes:",
                    "      - mysql_data:/var/lib/mysql",
                ]
            )

        volume_names = []
        if has_postgres:
            volume_names.append("postgres_data")
        if has_mysql:
            volume_names.append("mysql_data")
        if volume_names:
            lines.extend(["", "volumes:"])
            for volume_name in volume_names:
                lines.append(f"  {volume_name}:")

        return "\n".join(lines)

    def build_kubernetes_manifests(self, mapped_context: dict[str, Any]) -> str:
        if not mapped_context.get("artifact_expectations", {}).get("needs_kubernetes"):
            return ""
        parts = [
            self.build_kubernetes_deployment(mapped_context),
            self.build_kubernetes_service(mapped_context),
            self.build_kubernetes_configmap(mapped_context),
        ]
        return "\n---\n".join(part for part in parts if part.strip())

    def build_kubernetes_deployment(self, mapped_context: dict[str, Any]) -> str:
        if not mapped_context.get("artifact_expectations", {}).get("needs_kubernetes"):
            return ""
        main_service = mapped_context.get("main_service") or {}
        port = main_service.get("port") or 8000
        name = main_service.get("name") or "app"
        lines = [
            "apiVersion: apps/v1",
            "kind: Deployment",
            "metadata:",
            f"  name: {name}",
            "spec:",
            "  replicas: 1",
            "  selector:",
            "    matchLabels:",
            f"      app: {name}",
            "  template:",
            "    metadata:",
            "      labels:",
            f"        app: {name}",
            "    spec:",
            "      containers:",
            f"        - name: {name}",
            f"          image: {name}:latest",
            "          ports:",
            f"            - containerPort: {port}",
        ]
        env_template = mapped_context.get("environment_template") or []
        if env_template:
            lines.extend(
                [
                    "          envFrom:",
                    "            - configMapRef:",
                    f"                name: {name}-config",
                ]
            )
        return "\n".join(lines)

    def build_kubernetes_service(self, mapped_context: dict[str, Any]) -> str:
        if not mapped_context.get("artifact_expectations", {}).get("needs_kubernetes"):
            return ""
        main_service = mapped_context.get("main_service") or {}
        port = main_service.get("port") or 8000
        name = main_service.get("name") or "app"
        return "\n".join(
            [
                "apiVersion: v1",
                "kind: Service",
                "metadata:",
                f"  name: {name}",
                "spec:",
                "  selector:",
                f"    app: {name}",
                "  ports:",
                "    - name: http",
                f"      port: {port}",
                f"      targetPort: {port}",
                "  type: ClusterIP",
            ]
        )

    def build_kubernetes_configmap(self, mapped_context: dict[str, Any]) -> str:
        if not mapped_context.get("artifact_expectations", {}).get("needs_kubernetes"):
            return ""
        env_template = mapped_context.get("environment_template") or []
        if not env_template:
            return ""
        name = (mapped_context.get("main_service") or {}).get("name") or "app"
        lines = [
            "apiVersion: v1",
            "kind: ConfigMap",
            "metadata:",
            f"  name: {name}-config",
            "data:",
        ]
        for item in env_template:
            lines.append(f'  {item["name"]}: ""')
        return "\n".join(lines)

    def build_terraform_main(self, mapped_context: dict[str, Any]) -> str:
        if not mapped_context.get("artifact_expectations", {}).get("needs_terraform"):
            return ""
        main_service = mapped_context.get("main_service") or {}
        service_name = main_service.get("name") or "app"
        port = main_service.get("port") or 8080
        return "\n".join(
            [
                'terraform {',
                '  required_version = ">= 1.5.0"',
                "",
                '  required_providers {',
                '    docker = {',
                '      source = "kreuzwerker/docker"',
                '      version = "~> 3.0"',
                "    }",
                "  }",
                '}',
                "",
                'provider "docker" {}',
                "",
                f'resource "docker_image" "{service_name}" {{',
                f'  name = "{service_name}:latest"',
                f'  build {{',
                f'    context = var.build_context',
                "  }",
                "}",
                "",
                f'resource "docker_container" "{service_name}" {{',
                f'  name  = "{service_name}"',
                f'  image = docker_image.{service_name}.image_id',
                "  ports {",
                f"    internal = {port}",
                f"    external = {port}",
                "  }",
                "}",
            ]
        )

    def build_terraform_variables(self, mapped_context: dict[str, Any]) -> str:
        if not mapped_context.get("artifact_expectations", {}).get("needs_terraform"):
            return ""
        build_context = mapped_context.get("build_context") or "."
        return "\n".join(
            [
                'variable "build_context" {',
                "  type = string",
                f'  default = "{build_context}"',
                "}",
            ]
        )

    def build_terraform_outputs(self, mapped_context: dict[str, Any]) -> str:
        if not mapped_context.get("artifact_expectations", {}).get("needs_terraform"):
            return ""
        main_service = mapped_context.get("main_service") or {}
        service_name = main_service.get("name") or "app"
        return "\n".join(
            [
                'output "container_name" {',
                f"  value = docker_container.{service_name}.name",
                "}",
            ]
        )

    def _compose_service_block(
        self,
        service: dict[str, Any],
        env_template: list[dict[str, Any]],
        has_postgres: bool,
        has_mysql: bool,
        artifact_targets: dict[str, Any],
        build_context: str,
    ) -> list[str]:
        name = service.get("name", "app")
        command = service.get("run_command")
        port = service.get("port")
        env_names = service.get("environment_variables") or []
        dockerfile_target = artifact_targets.get("dockerfile") or "Dockerfile"
        compose_dockerfile = Path(dockerfile_target).name if build_context not in {".", ""} else dockerfile_target
        block = [
            f"  {name}:",
            "    build:",
            f"      context: {build_context}",
            f"      dockerfile: {compose_dockerfile}",
            "    restart: unless-stopped",
        ]
        if command:
            block.append(f'    command: {command}')
        if port:
            block.extend(["    ports:", f'      - "{port}:{port}"'])
        if env_names:
            block.append("    environment:")
            allowed_names = {item["name"] for item in env_template}
            for env_name in sorted(set(env_names)):
                if env_name in allowed_names:
                    block.append(f"      {env_name}: ${{{env_name}}}")
        if (has_postgres or has_mysql) and service.get("name") == "backend":
            block.extend(["    depends_on:", "      - db"])
        return block

    def _command_to_docker_cmd(self, command: str) -> str:
        normalized = command.strip()
        if normalized.startswith("CMD "):
            return normalized
        if "uvicorn" in normalized:
            return 'CMD ["sh", "-c", "' + normalized.replace('"', '\\"') + '"]'
        if "streamlit run" in normalized:
            return 'CMD ["sh", "-c", "' + normalized.replace('"', '\\"') + '"]'
        return 'CMD ["sh", "-c", "' + normalized.replace('"', '\\"') + '"]'

    def _python_dependency_copy_line(
        self,
        build_context: str,
        dependency_file: str,
    ) -> str:
        file_name = Path(dependency_file).name
        if build_context == ".":
            return f"COPY {dependency_file} ./{file_name}"
        return f"COPY {file_name} ./{file_name}"

    def _python_install_line(self, dependency_file: str) -> str:
        file_name = Path(dependency_file).name
        if file_name.endswith(".txt"):
            return f"RUN pip install --no-cache-dir -r {file_name}"
        if file_name == "pyproject.toml":
            return "RUN pip install --no-cache-dir ."
        if file_name == "package.json":
            return "RUN echo \"Frontend dependencies managed separately\""
        return f"RUN pip install --no-cache-dir -r {file_name}"
