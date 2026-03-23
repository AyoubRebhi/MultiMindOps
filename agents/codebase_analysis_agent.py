from typing import Any, Dict

from agents.base_agent import BaseAgent
from backend.app.services.context_builder_service import ContextBuilderService
from backend.app.services.github_service import GitHubService
from backend.app.services.repository_parser_service import RepositoryParserService


class CodebaseAnalysisAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="CodebaseAnalysisAgent")
        self.github_service = GitHubService()
        self.repository_parser = RepositoryParserService()
        self.context_builder = ContextBuilderService()

    def run(self, repo_url: str) -> Dict[str, Any]:
        repo_path = self.github_service.clone_repository(repo_url)
        parsed_repo = self.repository_parser.parse_repository(repo_path)
        agent_context = self.context_builder.build_agent_context(parsed_repo)

        return {
            "agent": self.name,
            "repo_path": repo_path,
            "repo_summary": parsed_repo.get("project_summary"),
            "file_tree": parsed_repo.get("file_tree"),
            "important_files": parsed_repo.get("important_files"),
            "agent_context": agent_context,
        }