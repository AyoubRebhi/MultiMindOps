import logging
from pathlib import Path
from typing import Any, Dict

from backend.app.agents.base_agent import BaseAgent
from backend.app.services.rag.context_builder_service import ContextBuilderService
from backend.app.services.environment.env_file_detector_service import EnvFileDetectorService
from backend.app.services.environment.env_sanitizer_service import EnvSanitizerService
from backend.app.services.execution.execution_trace_service import ExecutionTraceService
from backend.app.services.repository.github_service import GitHubService
from backend.app.services.repository.llm_priority_engine import LLMPriorityEngine
from backend.app.services.repository.quick_scanner_service import QuickScannerService
from backend.app.services.repository.repository_fingerprint_service import RepositoryFingerprintService
from backend.app.services.repository.repository_parser_service import RepositoryParserService
from backend.app.services.repository.repository_registry_service import RepositoryRegistryService
from backend.app.services.repository.repository_security_service import RepositorySecurityService
from backend.app.services.repository.targeted_repository_parser import TargetedRepositoryParser

logger = logging.getLogger(__name__)


class CodebaseAnalysisAgent(BaseAgent):
    ANALYSIS_VERSION = "2026-04-08-analysis-llm-v1"

    def __init__(self):
        super().__init__(name="CodebaseAnalysisAgent")
        self.github_service = GitHubService()
        self.security_service = RepositorySecurityService()
        self.repository_parser = RepositoryParserService()
        self.context_builder = ContextBuilderService()
        self.env_file_detector = EnvFileDetectorService()
        self.env_sanitizer = EnvSanitizerService()
        self.fingerprint_service = RepositoryFingerprintService()
        self.registry_service = RepositoryRegistryService()
        self.trace_service = ExecutionTraceService()
        # Intelligent analysis pipeline (GLM-5.1:cloud)
        self.quick_scanner = QuickScannerService()
        self.priority_engine = LLMPriorityEngine()
        self.targeted_parser = TargetedRepositoryParser()

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
        uploaded_env: Dict[str, Any] | None = None,
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
        env_security_runtime = None
        current_repo_path: str | None = None
        current_env_snapshot: Dict[str, Any] | None = None

        if cache_decision["status"] == "unchanged" and latest_analysis:
            latest_metadata = latest_analysis.get("analysis_metadata") or {}
            latest_env_fingerprint = latest_metadata.get("env_fingerprint")
            latest_env_detected = bool(latest_metadata.get("env_detected"))
            latest_env_file_count = int(latest_metadata.get("env_file_count") or 0)

            current_repo_path = self.github_service.clone_repository(
                repo_url=repo_url,
                repository_visibility=repository_visibility,
                github_token=github_token,
            )
            current_env_snapshot = self._build_env_snapshot(
                current_repo_path,
                uploaded_env=uploaded_env,
            )
            env_security_runtime = current_env_snapshot.get("runtime_security")
            current_env_fingerprint = current_env_snapshot.get("env_fingerprint")
            current_env_files = current_env_snapshot.get("env_files") or []
            current_env_detected = bool(current_env_files)
            current_env_file_count = len(current_env_files)

            if latest_env_detected != current_env_detected:
                cache_decision = {
                    "status": "changed",
                    "reason": "env_presence_changed",
                    "latest_analysis": latest_analysis,
                }
            elif latest_env_fingerprint != current_env_fingerprint:
                cache_decision = {
                    "status": "changed",
                    "reason": "env_fingerprint_changed",
                    "latest_analysis": latest_analysis,
                }
            elif latest_env_file_count != current_env_file_count:
                cache_decision = {
                    "status": "changed",
                    "reason": "env_file_count_changed",
                    "latest_analysis": latest_analysis,
                }

            cache_decision_summary = {
                "status": cache_decision["status"],
                "reason": cache_decision["reason"],
                "latest_analysis": self._summarize_cached_analysis(
                    cache_decision.get("latest_analysis")
                ),
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
                        "env_verification": self._summarize_env_snapshot(current_env_snapshot),
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
            analysis_output["env_security_runtime"] = env_security_runtime or {
                "sensitive_values": [],
                "all_values": [],
            }
            return analysis_output

        repo_path = current_repo_path or self.github_service.clone_repository(
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

        # ── Intelligent pipeline: GLM-5.1:cloud quick scan + targeted parse ──
        intelligent_analysis: Dict[str, Any] = {}
        llm_calls = 0
        try:
            quick_scan = self.quick_scanner.scan(repo_path)
            priority_result = self.priority_engine.rank(
                quick_scan=quick_scan,
                user_prompt=None,
            )
            if priority_result.llm_used:
                llm_calls += 1
            targeted = self.targeted_parser.parse_targeted(
                repo_path=repo_path,
                priority_result=priority_result,
            )
            intelligent_analysis = {
                "quick_scan": quick_scan,
                "critical_files_ranked": targeted.get("critical_files_ranked", []),
                "file_relationships": targeted.get("file_relationships", {}),
                "critical_sections": targeted.get("critical_sections", {}),
                "architecture_summary": targeted.get("architecture_summary", ""),
                "llm_used": priority_result.llm_used,
            }
            execution_trace.append(
                self.trace_service.build_trace_entry(
                    step="intelligent_analysis",
                    status="completed",
                    details={
                        "llm_used": priority_result.llm_used,
                        "critical_files_count": len(targeted.get("critical_files_ranked", [])),
                        "architecture_hint": priority_result.architecture_hint,
                        "primary_stack": priority_result.primary_stack,
                        "size_category": quick_scan.get("size_category"),
                    },
                )
            )
        except Exception as exc:
            logger.warning("Intelligent analysis pipeline failed (%s); continuing with heuristic parser.", exc)
            execution_trace.append(
                self.trace_service.build_trace_entry(
                    step="intelligent_analysis",
                    status="failed",
                    details={"error": str(exc)},
                )
            )

        parsed_repo = self.repository_parser.parse_repository(
            repo_path,
            uploaded_env=uploaded_env,
        )
        agent_context = self.context_builder.build_agent_context(parsed_repo)
        env_security_runtime = parsed_repo.pop("_runtime_env_security", None) or {
            "sensitive_values": [],
            "all_values": [],
        }

        # Merge LLM-ranked important files into the heuristic list (LLM takes priority)
        llm_critical_paths = [
            f["path"] for f in intelligent_analysis.get("critical_files_ranked", [])
        ]
        heuristic_important = parsed_repo.get("important_files") or []
        merged_important_files = llm_critical_paths + [
            f for f in heuristic_important if f not in set(llm_critical_paths)
        ]

        content_fingerprint = self.fingerprint_service.build_content_fingerprint(
            repo_path=repo_path,
            candidate_files=(
                (merged_important_files or parsed_repo.get("file_tree") or [])
                + [item["path"] for item in (parsed_repo.get("env_files") or [])]
            ),
        )
        env_fingerprint = parsed_repo.get("env_fingerprint")
        env_files = parsed_repo.get("env_files") or []
        sanitized_env_context = parsed_repo.get("sanitized_env_context") or {}

        execution_trace.append(
            self.trace_service.build_trace_entry(
                step="repository_parsing",
                status="completed",
                details={
                    "important_files_count": len(merged_important_files),
                    "key_entrypoints_count": len(parsed_repo.get("key_entrypoints") or []),
                    "content_fingerprint": content_fingerprint,
                },
            )
        )
        execution_trace.append(
            self.trace_service.build_trace_entry(
                step="env_file_processing",
                status="sanitized" if env_files else "not_detected",
                details={
                    "env_detected": bool(env_files),
                    "env_source": sanitized_env_context.get("source", "none"),
                    "uploaded_env_provided": bool(uploaded_env),
                    "env_hash_stored": bool(env_fingerprint),
                    "env_file_count": len(env_files),
                    "variables_extracted": len(sanitized_env_context.get("variables") or []),
                    "sensitive_variables_count": sanitized_env_context.get(
                        "sensitive_variables_count",
                        0,
                    ),
                },
            )
        )

        analysis_output = {
            "agent": self.name,
            "repo_path": repo_path,
            "security": security_result,
            "repo_summary": parsed_repo.get("project_summary"),
            "file_tree": parsed_repo.get("file_tree"),
            "important_files": merged_important_files,
            "key_entrypoints": parsed_repo.get("key_entrypoints"),
            "categorized_files": parsed_repo.get("categorized_files"),
            "chunks": parsed_repo.get("chunks"),
            "agent_context": agent_context,
            "intelligent_analysis": intelligent_analysis,
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
                "env_detected": bool(env_files),
                "env_source": sanitized_env_context.get("source", "none"),
                "env_fingerprint": env_fingerprint,
                "env_file_count": len(env_files),
                "uploaded_env_provided": bool(uploaded_env),
                "llm_used_for_priority": intelligent_analysis.get("llm_used", False),
                "reused_components": [],
                "recomputed_components": [
                    "security_scan",
                    "intelligent_analysis",
                    "repository_parsing",
                    "env_file_processing",
                    "context_building",
                ],
            },
            execution_trace=execution_trace,
            execution_stats={"llm_calls": llm_calls, "cache_hit": False},
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
        analysis_output["env_security_runtime"] = env_security_runtime

        return analysis_output

    def _build_env_snapshot(
        self,
        repo_path: str,
        uploaded_env: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        file_tree = self.repository_parser._build_file_tree(Path(repo_path))
        env_files = self.env_file_detector.detect(file_tree)
        return self.env_sanitizer.extract(
            repo_path,
            env_files,
            uploaded_env=uploaded_env,
        )

    def _summarize_env_snapshot(
        self,
        snapshot: Dict[str, Any] | None,
    ) -> Dict[str, Any]:
        snapshot = snapshot or {}
        sanitized_context = snapshot.get("sanitized_env_context") or {}
        return {
            "env_detected": bool(snapshot.get("env_files")),
            "env_source": (snapshot.get("sanitized_env_context") or {}).get("source", "none"),
            "env_hash_stored": bool(snapshot.get("env_fingerprint")),
            "env_file_count": len(snapshot.get("env_files") or []),
            "variables_extracted": len(sanitized_context.get("variables") or []),
            "sensitive_variables_count": sanitized_context.get(
                "sensitive_variables_count",
                0,
            ),
        }
