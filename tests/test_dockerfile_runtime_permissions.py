"""
End-to-end verification of the runtime-permission stabilization patch.

These tests pin the contract that generated Python/FastAPI Dockerfiles MUST:
  • create the non-root user with a home directory (-m on Debian, -h on Alpine)
  • set --chown=appuser:appgroup on every runtime-stage COPY
  • pre-create runtime-writable directories (workspace/repos) and chown them
    BEFORE the USER appuser switch

They also pin the new DockerBuildStaticValidator runtime-permission rules.
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.services.artifact_generation.assemblers.artifact_assembler import (
    ArtifactAssembler,
)
from backend.app.services.artifact_generation.blueprints.loader import BlueprintLoader
from backend.app.services.artifact_generation.generators.section_generator import (
    ArtifactSectionGenerator,
)
from backend.app.services.artifact_generation.validators.docker_static_validator import (
    DockerBuildStaticValidator,
)
from backend.app.services.repository.github_service import (
    DEFAULT_WORKSPACE_DIR,
    GitHubService,
    resolve_workspace_dir,
)


class _FailingLLM:
    """LLM stub that always raises, forcing deterministic fallbacks."""

    def chat_json(self, *_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("LLM disabled for deterministic test")


class DockerfileRuntimePermissionsTests(unittest.TestCase):
    def _generate_python_fastapi_dockerfile(self) -> str:
        loader = BlueprintLoader()
        blueprint = loader.load_by_name("python_fastapi", "docker")
        assert blueprint is not None, "python_fastapi blueprint must load"
        generator = ArtifactSectionGenerator(_FailingLLM())
        assembler = ArtifactAssembler()

        project_context = {
            "main_service": {
                "language": "python",
                "framework": "fastapi",
                "port": 8000,
                "entrypoint": "main",
                "run_command": "",
            },
            "runtime": {
                "python_version": "3.11",
                "dependency_files": ["requirements.txt"],
            },
        }

        section_results = generator.generate_all_sections(
            blueprint=blueprint,
            project_context=project_context,
        )
        return assembler.assemble(blueprint, section_results)

    # ── End-to-end: generated Python/FastAPI Dockerfile contract ──────────────

    def test_generated_python_fastapi_dockerfile_contains_all_permission_directives(self):
        dockerfile = self._generate_python_fastapi_dockerfile()

        # 1. useradd MUST have -m so /home/appuser exists at runtime
        self.assertIn(
            "RUN groupadd -r appgroup && useradd -r -m -g appgroup appuser",
            dockerfile,
            "Generated Dockerfile must use 'useradd -r -m' so /home/appuser exists",
        )

        # 2. COPY --from=builder MUST set --chown so .local is appuser-owned
        self.assertIn(
            "COPY --chown=appuser:appgroup --from=builder /root/.local /home/appuser/.local",
            dockerfile,
            "COPY of builder /root/.local must set --chown=appuser:appgroup",
        )

        # 3. COPY . . MUST set --chown so /app and source are appuser-owned
        self.assertIn(
            "COPY --chown=appuser:appgroup . .",
            dockerfile,
            "Runtime-stage COPY . . must set --chown=appuser:appgroup",
        )

        # 4. Runtime-writable dirs MUST be pre-created and chown'd before USER
        runtime_dirs_block = (
            "RUN mkdir -p /app/workspace/repos && \\\n"
            "    chown -R appuser:appgroup /app"
        )
        self.assertIn(
            runtime_dirs_block,
            dockerfile,
            "Dockerfile must pre-create /app/workspace/repos with chown before USER",
        )

        # 5. USER directive MUST appear AFTER the mkdir/chown block
        user_idx = dockerfile.find("USER appuser")
        mkdir_idx = dockerfile.find("mkdir -p /app/workspace/repos")
        self.assertGreater(user_idx, 0, "USER appuser must be present")
        self.assertGreater(mkdir_idx, 0, "mkdir/chown block must be present")
        self.assertLess(
            mkdir_idx,
            user_idx,
            "mkdir/chown of writable dirs must precede USER appuser",
        )

        # 6. There must be NO un-chown'd COPY in the runtime stage
        last_from = max(
            (m.start() for m in re.finditer(r"(?im)^FROM\s+", dockerfile)),
            default=0,
        )
        runtime_stage = dockerfile[last_from:]
        bad_copies = [
            line for line in runtime_stage.splitlines()
            if re.match(r"(?i)^\s*COPY\b", line) and "--chown=" not in line.lower()
        ]
        self.assertEqual(
            bad_copies, [],
            f"Runtime-stage has COPY without --chown: {bad_copies!r}",
        )

    # ── Static validator: rule A (HIGH) ───────────────────────────────────────

    def test_static_validator_flags_copy_without_chown_under_nonroot(self):
        dockerfile = (
            "FROM python:3.11-slim AS runtime\n"
            "RUN groupadd -r appgroup && useradd -r -m -g appgroup appuser\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            "RUN mkdir -p /app/workspace/repos && chown -R appuser:appgroup /app\n"
            "USER appuser\n"
            'CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
        )

        result = DockerBuildStaticValidator().validate(
            dockerfile_content=dockerfile,
            build_context=".",
            known_files=["main.py", "requirements.txt"],
            framework="fastapi",
        )

        permission_issues = [
            i for i in result.issues
            if i.rule == "copy_without_chown_under_nonroot_user"
        ]
        self.assertEqual(
            len(permission_issues), 1,
            f"Expected exactly one HIGH issue for COPY without --chown, got: {result.issues}",
        )
        self.assertEqual(permission_issues[0].severity, "high")
        self.assertIn(
            "--chown=appuser:appgroup",
            permission_issues[0].suggested_fix or "",
            "Suggested fix must insert --chown=appuser:appgroup",
        )
        self.assertFalse(result.valid, "Result must be invalid when permission issues are present")

    # ── Static validator: rule B (MEDIUM warning) ─────────────────────────────

    def test_static_validator_warns_when_no_writable_runtime_dirs_for_fastapi(self):
        # Non-root user, FastAPI framework, but NO mkdir/chown before USER
        dockerfile = (
            "FROM python:3.11-slim\n"
            "RUN groupadd -r appgroup && useradd -r -m -g appgroup appuser\n"
            "WORKDIR /app\n"
            "COPY --chown=appuser:appgroup . .\n"
            "USER appuser\n"
            'CMD ["uvicorn", "main:app"]\n'
        )

        result = DockerBuildStaticValidator().validate(
            dockerfile_content=dockerfile,
            build_context=".",
            known_files=["main.py"],
            framework="fastapi",
        )

        joined_warnings = "\n".join(result.warnings)
        self.assertIn(
            "non-root user but runtime-writable",
            joined_warnings,
            f"Expected MEDIUM warning about missing mkdir/chown; got warnings: {result.warnings}",
        )

    # ── Static validator: clean Dockerfile produces no permission issues ─────

    def test_static_validator_passes_for_fully_hardened_dockerfile(self):
        dockerfile = self._generate_python_fastapi_dockerfile()

        result = DockerBuildStaticValidator().validate(
            dockerfile_content=dockerfile,
            build_context=".",
            known_files=["requirements.txt", "main.py"],
            framework="fastapi",
        )

        permission_issues = [
            i for i in result.issues
            if i.rule in (
                "copy_without_chown_under_nonroot_user",
            )
        ]
        permission_warnings = [
            w for w in result.warnings if "non-root user but runtime-writable" in w
        ]
        self.assertEqual(
            permission_issues, [],
            f"Hardened Dockerfile should not produce permission issues; got: {permission_issues}",
        )
        self.assertEqual(
            permission_warnings, [],
            f"Hardened Dockerfile should not produce missing-mkdir warning; got: {permission_warnings}",
        )

    # ── Root user is unaffected ───────────────────────────────────────────────

    def test_static_validator_skips_permission_checks_for_root_user(self):
        dockerfile = (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            "USER root\n"
            'CMD ["python", "app.py"]\n'
        )
        result = DockerBuildStaticValidator().validate(
            dockerfile_content=dockerfile,
            build_context=".",
            known_files=["app.py"],
            framework="fastapi",
        )
        self.assertNotIn(
            "copy_without_chown_under_nonroot_user",
            {i.rule for i in result.issues},
            "USER root must not trigger non-root permission rules",
        )

    # ── HEALTHCHECK + curl install contract ───────────────────────────────────

    def test_generated_python_fastapi_dockerfile_installs_curl_for_healthcheck(self):
        dockerfile = self._generate_python_fastapi_dockerfile()

        # python:*-slim does NOT ship curl; the blueprint must install it
        self.assertIn(
            "apt-get update && apt-get install -y --no-install-recommends",
            dockerfile,
            "Runtime stage must apt-get install runtime packages",
        )
        self.assertIn("curl", dockerfile, "curl must be installed in the runtime stage")
        self.assertIn(
            "rm -rf /var/lib/apt/lists/*",
            dockerfile,
            "apt lists must be cleaned to keep the image small",
        )

    def test_generated_python_fastapi_healthcheck_uses_curl_against_docs_endpoint(self):
        dockerfile = self._generate_python_fastapi_dockerfile()

        # The HEALTHCHECK must use curl (installed above) and probe /docs
        # (the FastAPI default that always responds without auth)
        hc_match = re.search(
            r"(?im)^HEALTHCHECK\s.*\n\s*CMD\s+(.+?)$",
            dockerfile,
            flags=re.MULTILINE,
        )
        self.assertIsNotNone(hc_match, f"HEALTHCHECK line not found in:\n{dockerfile}")
        cmd_text = hc_match.group(1)  # type: ignore[union-attr]

        self.assertIn(
            "curl -f http://localhost:8000/docs",
            cmd_text,
            f"FastAPI healthcheck must curl /docs; got: {cmd_text!r}",
        )
        # The previous bug: `nc localhost 8000` — netcat is NOT installed
        self.assertNotIn(
            "nc ",
            cmd_text,
            "HEALTHCHECK must not use nc/netcat — not installed in python:*-slim",
        )

    def test_runtime_packages_runs_before_user_switch(self):
        dockerfile = self._generate_python_fastapi_dockerfile()

        apt_idx = dockerfile.find("apt-get install")
        user_idx = dockerfile.find("USER appuser")
        self.assertGreater(apt_idx, 0, "apt-get install step must be present")
        self.assertGreater(user_idx, 0, "USER appuser must be present")
        self.assertLess(
            apt_idx, user_idx,
            "apt-get must run as root, before the USER switch",
        )


class WorkspaceResolverTests(unittest.TestCase):
    """resolve_workspace_dir() precedence: explicit > env > default."""

    def test_default_is_app_workspace_repos(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORKSPACE_DIR", None)
            self.assertEqual(
                str(resolve_workspace_dir()),
                str(Path(DEFAULT_WORKSPACE_DIR)),
            )

    def test_env_override_is_honored(self):
        with patch.dict(os.environ, {"WORKSPACE_DIR": "/tmp/custom-ws"}):
            self.assertEqual(
                str(resolve_workspace_dir()),
                str(Path("/tmp/custom-ws")),
            )

    def test_explicit_argument_beats_env(self):
        with patch.dict(os.environ, {"WORKSPACE_DIR": "/env/path"}):
            self.assertEqual(
                str(resolve_workspace_dir("/explicit/path")),
                str(Path("/explicit/path")),
            )

    def test_github_service_uses_explicit_workspace_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc = GitHubService(workspace_dir=tmp)
            self.assertEqual(svc.workspace_dir, Path(tmp))
            self.assertTrue(svc.workspace_dir.exists())


if __name__ == "__main__":
    unittest.main()
