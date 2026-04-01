from pathlib import Path
from typing import Any


class ServiceDetectorService:
    def detect(
        self,
        *,
        file_tree: list[str],
        stack: dict[str, Any],
        key_files_content: dict[str, str],
        commands: list[dict[str, Any]],
        environment_variables: list[dict[str, Any]],
        infrastructure_dependencies: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        services = []

        backend_entrypoint = self._find_backend_entrypoint(file_tree, key_files_content)
        if backend_entrypoint:
            services.append(
                self._build_service(
                    name="backend",
                    service_type="api",
                    framework=self._detect_framework(backend_entrypoint, key_files_content, stack),
                    language=self._detect_language(backend_entrypoint),
                    entrypoint=backend_entrypoint,
                    run_command=self._infer_run_command("backend", backend_entrypoint, commands),
                    port=self._infer_port("backend", commands, backend_entrypoint),
                    environment_variables=environment_variables,
                    infrastructure_dependencies=infrastructure_dependencies,
                )
            )

        frontend_entrypoint = self._find_frontend_entrypoint(file_tree, key_files_content)
        if frontend_entrypoint:
            services.append(
                self._build_service(
                    name="frontend",
                    service_type="web_ui",
                    framework=self._detect_framework(frontend_entrypoint, key_files_content, stack),
                    language=self._detect_language(frontend_entrypoint),
                    entrypoint=frontend_entrypoint,
                    run_command=self._infer_run_command("frontend", frontend_entrypoint, commands),
                    port=self._infer_port("frontend", commands, frontend_entrypoint),
                    environment_variables=environment_variables,
                    infrastructure_dependencies=infrastructure_dependencies,
                )
            )

        worker_entrypoint = self._find_worker_entrypoint(file_tree, key_files_content, commands)
        if worker_entrypoint:
            services.append(
                self._build_service(
                    name="worker",
                    service_type="worker",
                    framework=self._detect_framework(worker_entrypoint, key_files_content, stack),
                    language=self._detect_language(worker_entrypoint),
                    entrypoint=worker_entrypoint,
                    run_command=self._infer_run_command("worker", worker_entrypoint, commands),
                    port=None,
                    environment_variables=environment_variables,
                    infrastructure_dependencies=infrastructure_dependencies,
                )
            )

        scheduler_entrypoint = self._find_scheduler_entrypoint(file_tree, key_files_content, commands)
        if scheduler_entrypoint:
            services.append(
                self._build_service(
                    name="scheduler",
                    service_type="scheduler",
                    framework=self._detect_framework(scheduler_entrypoint, key_files_content, stack),
                    language=self._detect_language(scheduler_entrypoint),
                    entrypoint=scheduler_entrypoint,
                    run_command=self._infer_run_command("scheduler", scheduler_entrypoint, commands),
                    port=None,
                    environment_variables=environment_variables,
                    infrastructure_dependencies=infrastructure_dependencies,
                )
            )

        return services

    def _build_service(
        self,
        *,
        name: str,
        service_type: str,
        framework: str | None,
        language: str,
        entrypoint: str,
        run_command: str | None,
        port: int | None,
        environment_variables: list[dict[str, Any]],
        infrastructure_dependencies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        env_names = [
            item["name"]
            for item in environment_variables
            if item.get("service") in {name, "application"}
        ]
        dependencies = [
            item["name"]
            for item in infrastructure_dependencies
            if item.get("type") in {"database", "cache", "queue", "object_storage", "reverse_proxy"}
        ]
        return {
            "name": name,
            "type": service_type,
            "framework": framework,
            "language": language,
            "entrypoint": entrypoint,
            "run_command": run_command,
            "port": port,
            "environment_variables": sorted(set(env_names)),
            "dependencies": sorted(set(dependencies)),
        }

    def _find_backend_entrypoint(self, file_tree: list[str], key_files_content: dict[str, str]) -> str | None:
        candidates = [
            path
            for path in file_tree
            if path.endswith(("/main.py", "/app.py"))
            or path in {"main.py", "app.py"}
            or path.endswith("Application.java")
        ]
        for candidate in candidates:
            content = key_files_content.get(candidate, "").lower()
            if any(
                marker in content
                for marker in ("fastapi", "flask", "django", "uvicorn", "@springbootapplication")
            ) or candidate.startswith("backend/"):
                return candidate
        java_candidate = next(
            (path for path in candidates if path.lower().endswith("application.java")),
            None,
        )
        if java_candidate:
            return java_candidate
        return next((path for path in candidates if path.startswith("backend/")), None)

    def _find_frontend_entrypoint(self, file_tree: list[str], key_files_content: dict[str, str]) -> str | None:
        candidates = [
            path
            for path in file_tree
            if path.endswith(("/app.py", "/app.tsx", "/app.jsx", "/main.tsx", "/main.jsx"))
            or path in {"frontend/app.py", "frontend/app.tsx", "frontend/app.jsx", "package.json"}
        ]
        for candidate in candidates:
            content = key_files_content.get(candidate, "").lower()
            if "streamlit" in content or candidate.startswith("frontend/"):
                return candidate
        return next((path for path in candidates if "frontend" in path.lower()), None)

    def _find_worker_entrypoint(
        self,
        file_tree: list[str],
        key_files_content: dict[str, str],
        commands: list[dict[str, Any]],
    ) -> str | None:
        command = next((item for item in commands if item.get("service") == "worker"), None)
        if command:
            return command.get("source_file")
        for path in file_tree:
            lowered = path.lower()
            if "worker" in lowered or "celery" in lowered:
                return path
            if "celery" in key_files_content.get(path, "").lower():
                return path
        return None

    def _find_scheduler_entrypoint(
        self,
        file_tree: list[str],
        key_files_content: dict[str, str],
        commands: list[dict[str, Any]],
    ) -> str | None:
        command = next((item for item in commands if item.get("service") == "scheduler"), None)
        if command:
            return command.get("source_file")
        for path in file_tree:
            lowered = path.lower()
            if "scheduler" in lowered or "beat" in lowered:
                return path
            if "apscheduler" in key_files_content.get(path, "").lower():
                return path
        return None

    def _detect_framework(self, entrypoint: str, key_files_content: dict[str, str], stack: dict[str, Any]) -> str | None:
        content = key_files_content.get(entrypoint, "").lower()
        if "fastapi" in content:
            return "FastAPI"
        if "streamlit" in content:
            return "Streamlit"
        if "flask" in content:
            return "Flask"
        if "django" in content:
            return "Django"
        if "celery" in content:
            return "Celery"
        if "@springbootapplication" in content or "springapplication.run" in content:
            return "Spring Boot"
        frameworks = stack.get("frameworks", [])
        return frameworks[0] if frameworks else None

    def _detect_language(self, entrypoint: str) -> str:
        suffix = Path(entrypoint).suffix.lower()
        if suffix == ".py":
            return "Python"
        if suffix == ".java":
            return "Java"
        if suffix in {".js", ".jsx"}:
            return "JavaScript"
        if suffix in {".ts", ".tsx"}:
            return "TypeScript"
        return "Unknown"

    def _infer_run_command(self, service_name: str, entrypoint: str, commands: list[dict[str, Any]]) -> str | None:
        matching_commands = [item["command"] for item in commands if item.get("service") == service_name]
        if matching_commands:
            return matching_commands[0]
        if service_name == "backend":
            if entrypoint.endswith(".java"):
                return "./mvnw spring-boot:run"
            module = entrypoint.replace("/", ".").replace(".py", "")
            return f"uvicorn {module}:app --host 0.0.0.0 --port 8000"
        if service_name == "frontend":
            if entrypoint.endswith(".py"):
                return f"streamlit run {entrypoint} --server.port 8501"
            return "npm run dev"
        if service_name in {"worker", "scheduler"}:
            return f"python {entrypoint}"
        return None

    def _infer_port(
        self,
        service_name: str,
        commands: list[dict[str, Any]],
        entrypoint: str | None = None,
    ) -> int | None:
        for command in [item["command"] for item in commands if item.get("service") == service_name]:
            parts = command.replace("=", " ").split()
            for part in parts:
                if part.isdigit():
                    value = int(part)
                    if 1 <= value <= 65535:
                        return value
        if service_name == "backend":
            if any(token in (entrypoint or "").lower() for token in ("application.java",)):
                return 8080
            backend_command = next(
                (
                    item["command"]
                    for item in commands
                    if item.get("service") == "backend"
                    and any(token in item["command"].lower() for token in ("spring-boot:run", "java -jar"))
                ),
                None,
            )
            if backend_command:
                return 8080
            return 8000
        if service_name == "frontend":
            return 8501
        return None
