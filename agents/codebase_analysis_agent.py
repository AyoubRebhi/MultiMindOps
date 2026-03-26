from typing import Any, Dict

from agents.base_agent import BaseAgent
from backend.app.services.context_builder_service import ContextBuilderService
from backend.app.services.github_service import GitHubService
from backend.app.services.repository_parser_service import RepositoryParserService
from backend.app.services.repository_security_service import RepositorySecurityService


class CodebaseAnalysisAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="CodebaseAnalysisAgent")
        self.github_service = GitHubService()
        self.security_service = RepositorySecurityService()
        self.repository_parser = RepositoryParserService()
        self.context_builder = ContextBuilderService()

    def run(
        self,
        repo_url: str,
        repository_visibility: str = "public",
        github_token: str | None = None,
    ) -> Dict[str, Any]:
        repo_path = self.github_service.clone_repository(
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
        )

        security_result = self.security_service.run_security_gate(
            repo_url=repo_url,
            repo_path=repo_path,
        )

        if security_result["status"] == "blocked":
            return {
                "agent": self.name,
                "repo_path": repo_path,
                "security": security_result,
                "repo_summary": None,
                "file_tree": None,
                "important_files": None,
                "agent_context": None,
            }

        parsed_repo = self.repository_parser.parse_repository(repo_path)
        agent_context = self.context_builder.build_agent_context(parsed_repo)

        return {
            "agent": self.name,
            "repo_path": repo_path,
            "security": security_result,
            "repo_summary": parsed_repo.get("project_summary"),
            "file_tree": parsed_repo.get("file_tree"),
            "important_files": parsed_repo.get("important_files"),
            "agent_context": agent_context,
        }