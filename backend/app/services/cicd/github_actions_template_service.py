from __future__ import annotations

from pathlib import Path
from typing import Any


class GitHubActionsTemplateService:
    """Load local GitHub Actions examples organized under /rag for CICD generation."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or (
            Path(__file__).resolve().parents[3] / "rag" / "cicd" / "github_actions"
        )
        self.examples_dir = self.base_dir / "examples"
        self.validation_dir = self.base_dir / "validation"

    def load_best_template(self, runtime_info: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any] | None:
        template_id = self._select_template_id(runtime_info, handoff)
        if not template_id:
            return None

        path = self.examples_dir / f"{template_id}.yml"
        if not path.exists():
            return None

        return {
            "id": template_id,
            "path": str(path.relative_to(self.base_dir.parent.parent)).replace("\\", "/"),
            "content": path.read_text(encoding="utf-8"),
        }

    def load_validation_reference(self) -> str:
        report_path = self.validation_dir / "workflow_validation_report.txt"
        if not report_path.exists():
            return ""
        return report_path.read_text(encoding="utf-8")

    def list_templates(self) -> list[str]:
        if not self.examples_dir.exists():
            return []
        return sorted(path.stem for path in self.examples_dir.glob("*.yml"))

    def _select_template_id(self, runtime_info: dict[str, Any], handoff: dict[str, Any]) -> str | None:
        runtime_name = str(runtime_info.get("runtime_name") or "").lower()
        framework = str(runtime_info.get("framework") or "").lower()
        repo_summary = handoff.get("repo_summary") or {}
        stack = repo_summary.get("stack") or {}
        devops_tools = [str(item).lower() for item in stack.get("devops_tools") or []]
        infra_files = [str(item).lower() for item in (handoff.get("artifact_groups") or {}).get("infrastructure", [])]

        is_dockerized = "docker" in devops_tools or any(path.endswith("dockerfile") for path in infra_files)

        if framework == "spring boot" or runtime_name == "java":
            return "spring_boot_ci"
        if runtime_name == "python" and is_dockerized:
            return "full_stack_ci_cd"
        if runtime_name == "python":
            return "python_ci"
        if runtime_name == "node":
            return "node_ci"
        if is_dockerized:
            return "docker_build"
        return None
