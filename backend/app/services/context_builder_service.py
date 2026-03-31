from typing import Any, Dict


class ContextBuilderService:
    def build_agent_context(self, parsed_repo: Dict[str, Any]) -> Dict[str, Any]:
        summary = parsed_repo.get("project_summary") or {}
        stack = parsed_repo.get("detected_stack") or {}
        key_files = parsed_repo.get("key_files_content") or {}
        important_files = parsed_repo.get("important_files") or []
        chunks = parsed_repo.get("chunks") or []
        key_entrypoints = parsed_repo.get("key_entrypoints") or []
        categorized_files = parsed_repo.get("categorized_files") or {}

        planner_context = {
            "project_summary": summary,
            "detected_stack": stack,
            "important_files": important_files[:50],
            "key_entrypoints": key_entrypoints,
            "ci_cd_files": categorized_files.get("ci_cd_files", []),
            "infra_files": categorized_files.get("infra_files", []),
        }

        infrastructure_context = {
            "existing_devops_files": [
                path for path in important_files
                if any(
                    keyword in path.lower()
                    for keyword in ["docker", "k8s", "kubernetes", "terraform", ".github", "deploy"]
                )
            ],
            "detected_stack": stack,
            "key_entrypoints": key_entrypoints,
            "infra_files": categorized_files.get("infra_files", []),
            "deployment_files": categorized_files.get("deployment_files", []),
            "key_files_content": key_files,
            "relevant_chunks": [
                chunk for chunk in chunks
                if chunk.get("category") in {"infrastructure", "deployment", "dependencies", "source_code"}
            ][:10],
        }

        security_context = {
            "detected_stack": stack,
            "dependency_files": categorized_files.get("dependency_files", []),
            "ci_cd_files": categorized_files.get("ci_cd_files", []),
            "infra_files": categorized_files.get("infra_files", []),
            "relevant_chunks": [
                chunk for chunk in chunks
                if chunk.get("category") in {"dependencies", "infrastructure", "ci_cd", "source_code"}
            ][:10],
        }

        cicd_context = {
            "detected_stack": stack,
            "ci_cd_files": categorized_files.get("ci_cd_files", []),
            "deployment_files": categorized_files.get("deployment_files", []),
            "key_entrypoints": key_entrypoints,
            "key_files_content": key_files,
            "relevant_chunks": [
                chunk for chunk in chunks
                if chunk.get("category") in {"ci_cd", "deployment", "dependencies", "source_code"}
            ][:10],
        }

        return {
            "planner_context": planner_context,
            "infrastructure_context": infrastructure_context,
            "security_context": security_context,
            "cicd_context": cicd_context,
        }