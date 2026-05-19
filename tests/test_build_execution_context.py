import unittest
from pathlib import Path

from backend.app.services.execution.docker_executor import DockerExecutor
from backend.app.services.infrastructure.repository_build_context import (
    BuildStrategy,
    BuildStrategyDetector,
    RepositoryBuildContext,
    STRATEGY_BACKEND,
    STRATEGY_REPO_ROOT,
)


class SilentDockerExecutor(DockerExecutor):
    async def _emit(self, level, message):  # noqa: ANN001
        return None


class BuildExecutionContextTests(unittest.TestCase):
    def test_detector_uses_repo_root_when_root_dependency_exists(self):
        known_files = [
            "backend/app/main.py",
            "frontend-React/package.json",
            "requirements-backend.txt",
            "Dockerfile",
        ]
        repo_ctx = BuildStrategyDetector().detect(
            known_files=known_files,
            mapped_context={
                "service_root": "backend/app",
                "build_context": "backend/app",
            },
        )

        self.assertIsNotNone(repo_ctx.docker)
        self.assertEqual(repo_ctx.docker.strategy, STRATEGY_REPO_ROOT)
        self.assertEqual(repo_ctx.docker.context_path, ".")

    def test_executor_resolves_root_context_from_copy_sources(self):
        dockerfile = "\n".join(
            [
                "FROM python:3.11-slim AS builder",
                "WORKDIR /build",
                "COPY requirements-backend.txt .",
                "RUN pip install --no-cache-dir --user -r requirements-backend.txt",
                "FROM python:3.11-slim AS runtime",
                "WORKDIR /app",
                "COPY . .",
            ]
        )

        repo = Path("workspace/repos/MultiMindOps_136ca4d1")
        if not repo.is_dir():
            self.skipTest("fixture repository is not available in workspace/repos")

        executor = SilentDockerExecutor(
            task_id="35e3149a-test",
            artifacts={"dockerfile": dockerfile},
            image_tag="test:latest",
            build_strategy={
                "strategy": "backend_context",
                "context_path": "backend/app",
                "dockerfile_path": "backend/app/Dockerfile",
            },
            repo_source_path=str(repo),
        )
        executor._workspace = str(repo)
        executor._copy_sources = executor._extract_copy_sources(dockerfile)
        executor._resolve_final_build_context(repo, dockerfile)

        self.assertTrue((repo / "requirements-backend.txt").exists())
        self.assertTrue((repo / "backend" / "app").exists())
        self.assertEqual(executor._resolved_build_context_path, repo.resolve())


    def test_reconcile_with_dockerfile_overrides_backend_to_repo_root(self):
        """
        When the detector mis-selects backend_context (e.g. because
        known_files lacked the root dep file), the post-generation
        reconciliation must override to repo_root_context as soon as it
        sees a repo-root-relative COPY source in the generated Dockerfile.
        """
        repo_ctx = RepositoryBuildContext(
            repo_root=".",
            backend_root="backend/app",
            docker=BuildStrategy(
                strategy=STRATEGY_BACKEND,
                context_path="backend/app",
                dockerfile_path="backend/app/Dockerfile",
            ),
        )
        dockerfile = (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY requirements-backend.txt .\n"
            "RUN pip install -r requirements-backend.txt\n"
        )
        reconciled = BuildStrategyDetector().reconcile_with_dockerfile(
            repo_ctx=repo_ctx,
            dockerfile_content=dockerfile,
            known_files=["backend/app/main.py", "requirements-backend.txt"],
        )
        self.assertEqual(reconciled.docker.strategy, STRATEGY_REPO_ROOT)
        self.assertEqual(reconciled.docker.context_path, ".")
        self.assertEqual(reconciled.docker.dockerfile_path, "Dockerfile")


if __name__ == "__main__":
    unittest.main()
