from typing import Any, Dict

from agents.base_agent import BaseAgent
from backend.app.services.context_builder_service import ContextBuilderService
from backend.app.services.execution_trace_service import ExecutionTraceService
from backend.app.services.github_service import GitHubService
from backend.app.services.repository_fingerprint_service import RepositoryFingerprintService
from backend.app.services.repository_parser_service import RepositoryParserService
from backend.app.services.repository_registry_service import RepositoryRegistryService
from backend.app.services.repository_security_service import RepositorySecurityService


class CodebaseAnalysisAgent(BaseAgent):
    ANALYSIS_VERSION = "2026-03-31-analysis-cache-v2"

    def __init__(self):
        super().__init__(name="CodebaseAnalysisAgent")
        self.github_service = GitHubService()
        self.security_service = RepositorySecurityService()
        self.repository_parser = RepositoryParserService()
        self.context_builder = ContextBuilderService()
        self.fingerprint_service = RepositoryFingerprintService()
        self.registry_service = RepositoryRegistryService()
        self.trace_service = ExecutionTraceService()

    @staticmethod
    def _summarize_cached_analysis(cached_analysis: Dict[str, Any] | None) -> Dict[str, Any] | None:
        if not cached_analysis:
            return None

        return {
            "id": cached_analysis.get("id"),
            "commit_sha": cached_analysis.get("commit_sha"),
            "content_fingerprint": cached_analysis.get("content_fingerprint"),
            "analysis_status": cached_analysis.get("analysis_status"),
            "created_at": cached_analysis.get("created_at"),
            "updated_at": cached_analysis.get("updated_at"),
        }

    def run(
        self,
        repo_url: str,
        repository_visibility: str = "public",
        github_token: str | None = None,
    ) -> Dict[str, Any]:
        repo_identity = self.fingerprint_service.build_identity(repo_url)
        cache_decision = {
            "status": "new",
            "reason": "initial_assumption",
            "latest_analysis": None,
        }

        try:
            remote_metadata = self.github_service.get_remote_repository_metadata(
                repo_url=repo_url,
                repository_visibility=repository_visibility,
                github_token=github_token,
            )
            repo_identity = self.fingerprint_service.build_identity(
                repo_url=repo_url,
                branch=remote_metadata.get("branch"),
                commit_sha=remote_metadata.get("commit_sha"),
            )
            cache_decision = self.registry_service.determine_repository_state(
                normalized_url=repo_identity["normalized_url"],
                branch=repo_identity["branch"],
                current_commit_sha=repo_identity.get("commit_sha"),
                current_analysis_version=self.ANALYSIS_VERSION,
            )
        except Exception as exc:
            cache_decision = {
                "status": "changed",
                "reason": f"remote_metadata_unavailable:{type(exc).__name__}",
                "latest_analysis": None,
            }

        latest_analysis = cache_decision.get("latest_analysis") or {}
        cache_decision_summary = {
            "status": cache_decision["status"],
            "reason": cache_decision["reason"],
            "latest_analysis": self._summarize_cached_analysis(cache_decision.get("latest_analysis")),
        }

        if cache_decision["status"] == "unchanged" and latest_analysis:
            reused_record = self.registry_service.mark_reused(
                latest_analysis["id"],
                self.trace_service.build_trace_entry(
                    step="codebase_analysis_reuse",
                    status="reused",
                    details={
                        "reason": cache_decision["reason"],
                        "commit_sha": repo_identity.get("commit_sha"),
                    },
                ),
            ) or latest_analysis

            analysis_output = dict(reused_record.get("analysis_output") or {})
            analysis_output["repository_analysis"] = {
                "cache_status": "reused",
                "decision": cache_decision_summary,
                "identity": repo_identity,
                "record_id": reused_record.get("id"),
                "execution_trace": reused_record.get("execution_trace", []),
            }
            return analysis_output

        repo_path = self.github_service.clone_repository(
            repo_url=repo_url,
            repository_visibility=repository_visibility,
            github_token=github_token,
        )

        security_result = self.security_service.run_security_gate(
            repo_url=repo_url,
            repo_path=repo_path,
        )

        execution_trace = [
            self.trace_service.build_trace_entry(
                step="repository_lookup",
                status=cache_decision["status"],
                details={
                    "reason": cache_decision["reason"],
                    "normalized_url": repo_identity["normalized_url"],
                    "branch": repo_identity["branch"],
                    "commit_sha": repo_identity.get("commit_sha"),
                },
            ),
            self.trace_service.build_trace_entry(
                step="repository_security_scan",
                status=security_result["status"],
                details={
                    "warnings": security_result.get("warnings", []),
                    "blocked_reasons": security_result.get("blocked_reasons", []),
                },
            ),
        ]

        if security_result["status"] == "blocked":
            analysis_output = {
                "agent": self.name,
                "repo_path": repo_path,
                "security": security_result,
                "repo_summary": None,
                "file_tree": None,
                "important_files": None,
                "key_entrypoints": None,
                "categorized_files": None,
                "chunks": None,
                "agent_context": None,
            }
            stored_record = self.registry_service.save_analysis(
                normalized_url=repo_identity["normalized_url"],
                branch=repo_identity["branch"],
                commit_sha=repo_identity.get("commit_sha"),
                content_fingerprint=None,
                analysis_status="blocked",
                project_summary=None,
                analysis_output=analysis_output,
                analysis_metadata={
                    "analysis_version": self.ANALYSIS_VERSION,
                    "cache_decision": cache_decision_summary,
                    "repository_visibility": repository_visibility,
                    "reused_components": [],
                    "recomputed_components": ["security_scan"],
                },
                execution_trace=execution_trace,
                execution_stats={"llm_calls": 0, "cache_hit": False},
                notes="Security gate blocked repository analysis.",
            )
            analysis_output["repository_analysis"] = {
                "cache_status": "blocked",
                "decision": cache_decision_summary,
                "identity": repo_identity,
                "record_id": stored_record["id"],
                "execution_trace": stored_record.get("execution_trace", []),
            }
            return analysis_output

        parsed_repo = self.repository_parser.parse_repository(repo_path)
        agent_context = self.context_builder.build_agent_context(parsed_repo)
        content_fingerprint = self.fingerprint_service.build_content_fingerprint(
            repo_path=repo_path,
            candidate_files=parsed_repo.get("important_files") or parsed_repo.get("file_tree") or [],
        )

        execution_trace.append(
            self.trace_service.build_trace_entry(
                step="repository_parsing",
                status="completed",
                details={
                    "important_files_count": len(parsed_repo.get("important_files") or []),
                    "key_entrypoints_count": len(parsed_repo.get("key_entrypoints") or []),
                    "content_fingerprint": content_fingerprint,
                },
            )
        )

        analysis_output = {
            "agent": self.name,
            "repo_path": repo_path,
            "security": security_result,
            "repo_summary": parsed_repo.get("project_summary"),
            "file_tree": parsed_repo.get("file_tree"),
            "important_files": parsed_repo.get("important_files"),
            "key_entrypoints": parsed_repo.get("key_entrypoints"),
            "categorized_files": parsed_repo.get("categorized_files"),
            "chunks": parsed_repo.get("chunks"),
            "agent_context": agent_context,
        }

        stored_record = self.registry_service.save_analysis(
            normalized_url=repo_identity["normalized_url"],
            branch=repo_identity["branch"],
            commit_sha=repo_identity.get("commit_sha"),
            content_fingerprint=content_fingerprint,
            analysis_status="completed",
            project_summary=parsed_repo.get("project_summary"),
            analysis_output=analysis_output,
            analysis_metadata={
                "analysis_version": self.ANALYSIS_VERSION,
                "cache_decision": cache_decision_summary,
                "repository_visibility": repository_visibility,
                "reused_components": [],
                "recomputed_components": ["security_scan", "repository_parsing", "context_building"],
            },
            execution_trace=execution_trace,
            execution_stats={"llm_calls": 0, "cache_hit": False},
            notes=(
                "Initial repository analysis persisted."
                if cache_decision["status"] == "new"
                else "Repository changed; analysis recomputed."
            ),
        )

        analysis_output["repository_analysis"] = {
            "cache_status": (
                "new_analysis"
                if cache_decision["status"] == "new"
                else "recomputed_after_change"
            ),
            "decision": cache_decision_summary,
            "identity": repo_identity,
            "record_id": stored_record["id"],
            "execution_trace": stored_record.get("execution_trace", []),
        }

        return analysis_output
