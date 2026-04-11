import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import app


class ArtifactsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("backend.app.api.routes.artifacts.github_service.get_repository_file_content")
    def test_view_artifact_returns_content(self, mock_get_file):
        mock_get_file.return_value = {
            "path": ".github/workflows/ci-cd.yml",
            "content": "name: CI\njobs:\n  test:\n",
            "encoding": "utf-8",
        }

        response = self.client.get(
            "/artifacts/view",
            params={
                "repo_url": "https://github.com/example/demo-repo",
                "path": ".github/workflows/ci-cd.yml",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], ".github/workflows/ci-cd.yml")

    @patch("backend.app.api.routes.artifacts.github_service.get_repository_file_content")
    def test_view_artifact_returns_404_for_missing_file(self, mock_get_file):
        mock_get_file.side_effect = FileNotFoundError("GitHub file not found: missing.yml")

        response = self.client.get(
            "/artifacts/view",
            params={
                "repo_url": "https://github.com/example/demo-repo",
                "path": "missing.yml",
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("GitHub file not found", response.json()["detail"])

    @patch("backend.app.api.routes.artifacts.github_service.get_repository_file_content")
    def test_view_artifact_returns_403_for_private_repo_without_access(self, mock_get_file):
        mock_get_file.side_effect = PermissionError("Unable to access the requested GitHub file.")

        response = self.client.get(
            "/artifacts/view",
            params={
                "repo_url": "https://github.com/example/private-repo",
                "path": ".github/workflows/ci.yml",
                "repository_visibility": "private",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("Unable to access", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
