from typing import Any, Dict


class ContextBuilderService:
    def build_agent_context(self, parsed_repo: Dict[str, Any]) -> Dict[str, Any]:
        summary = parsed_repo.get("project_summary", {})
        stack = parsed_repo.get("detected_stack", {})
        key_files = parsed_repo.get("key_files_content", {})
        important_files = parsed_repo.get("important_files", [])

        planner_context = {
            "project_summary": summary,
            "detected_stack": stack,
            "important_files": important_files[:50],
        }

        infrastructure_context = {
            "existing_devops_files": [
                path for path in important_files
                if any(keyword in path.lower() for keyword in ["docker", "k8s", "kubernetes", "terraform", ".github"])
            ],
            "key_files_content": key_files,
            "detected_stack": stack,
        }

        return {
            "planner_context": planner_context,
            "infrastructure_context": infrastructure_context,
        }