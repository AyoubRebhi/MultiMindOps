import base64
import unittest
from unittest.mock import Mock, patch

from backend.app.services.github_service import GitHubService


class GitHubServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = GitHubService()

    @patch("backend.app.services.github_service.requests.get")
    def test_get_repository_file_content_success(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.ok = True
        mock_response.json.return_value = {
            "type": "file",
            "encoding": "base64",
            "size": 32,
            "content": base64.b64encode(b"name: CI\njobs:\n  test:\n").decode("ascii"),
        }
        mock_get.return_value = mock_response

        result = self.service.get_repository_file_content(
            repo_url="https://github.com/example/demo-repo",
            file_path=".github/workflows/ci-cd.yml",
        )

        self.assertEqual(result["path"], ".github/workflows/ci-cd.yml")
        self.assertEqual(result["encoding"], "utf-8")
        self.assertIn("name: CI", result["content"])

    @patch("backend.app.services.github_service.requests.get")
    def test_get_repository_file_content_not_found(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.ok = False
        mock_get.return_value = mock_response

        with self.assertRaises(FileNotFoundError):
            self.service.get_repository_file_content(
                repo_url="https://github.com/example/demo-repo",
                file_path=".github/workflows/missing.yml",
            )

    @patch("backend.app.services.github_service.requests.get")
    def test_get_repository_file_content_private_repo_without_access(self, mock_get):
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.ok = False
        mock_get.return_value = mock_response

        with self.assertRaises(PermissionError):
            self.service.get_repository_file_content(
                repo_url="https://github.com/example/private-repo",
                file_path=".github/workflows/ci.yml",
                repository_visibility="private",
                github_token="token",
            )

    @patch(
        "backend.app.services.github_service.GitHubService.get_repository_file_content",
        return_value={"path": ".github/workflows/ci.yml", "content": "name: CI", "encoding": "utf-8"},
    )
    def test_verify_existing_github_workflow_returns_true_for_real_file(self, mock_get_file):
        self.assertTrue(
            self.service.verify_existing_github_workflow(
                repo_url="https://github.com/example/demo-repo",
                file_path=".github/workflows/ci.yml",
            )
        )
        mock_get_file.assert_called_once()

    @patch(
        "backend.app.services.github_service.GitHubService.get_repository_file_content",
        side_effect=FileNotFoundError("missing"),
    )
    def test_verify_existing_github_workflow_returns_false_for_phantom_file(self, mock_get_file):
        self.assertFalse(
            self.service.verify_existing_github_workflow(
                repo_url="https://github.com/example/demo-repo",
                file_path=".github/workflows/phantom.yml",
            )
        )
        mock_get_file.assert_called_once()


if __name__ == "__main__":
    unittest.main()
