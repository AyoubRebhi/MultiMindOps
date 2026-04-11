from __future__ import annotations

from copy import deepcopy
from typing import Any

from backend.app.services.cicd.artifact_contract_service import ArtifactContractService


class CicdHandoffService:
    """Prepare and normalize the infrastructure handoff for the future CICD agent.

    This service is intentionally deterministic and side-effect free. It only reads the
    upstream handoff contract and derives CI/CD-specific metadata. It never executes
    build, deploy, or infrastructure commands.
    """

    DEFAULT_WORKFLOW_TARGET = ".github/workflows/ci-cd.yml"

    def __init__(self) -> None:
        self.contract_service = ArtifactContractService()

    def normalize(
        self,
        handoff_context: dict[str, Any] | None,
        *,
        github_token: str | None = None,
    ) -> dict[str, Any]:
        handoff_context = deepcopy(handoff_context or {})
        repo_summary = handoff_context.get("repo_summary") or {}
        categorized_files = handoff_context.get("categorized_files") or {}
        artifact_groups = self._normalize_artifact_groups(
            handoff_context.get("artifact_groups") or {}
        )
        artifact_targets = self._normalize_artifact_targets(
            handoff_context.get("artifact_targets") or {}
        )
        requested_artifacts = self._normalize_paths(
            handoff_context.get("requested_artifacts") or []
        )
        upstream_statuses = self._normalize_status_paths(
            handoff_context.get("artifact_statuses") or []
        )

        ci_cd_files = self._normalize_paths(
            handoff_context.get("ci_cd_files")
            or repo_summary.get("ci_cd_files")
            or categorized_files.get("ci_cd_files")
            or []
        )
        repo_url = handoff_context.get("repo_url") or repo_summary.get("repo_url")
        repository_visibility = handoff_context.get("repository_visibility") or "public"
        branch = handoff_context.get("branch") or "main"
        deployment_files = self._normalize_paths(
            handoff_context.get("deployment_files")
            or repo_summary.get("deployment_files")
            or categorized_files.get("deployment_files")
            or []
        )

        detected_existing: list[str] = []
        requested_cicd = self._detect_requested_cicd_artifacts(
            requested_artifacts=requested_artifacts,
            artifact_targets=artifact_targets,
        )
        candidate_paths = self._build_candidate_paths(requested=requested_cicd)

        artifact_groups["cicd"] = candidate_paths

        return {
            "repo_url": repo_url,
            "repository_visibility": repository_visibility,
            "branch": branch,
            "repo_summary": repo_summary,
            "ci_cd_files": [],
            "deployment_files": deployment_files,
            "key_entrypoints": handoff_context.get("key_entrypoints")
            or repo_summary.get("key_entrypoints")
            or [],
            "artifact_groups": artifact_groups,
            "artifact_targets": artifact_targets,
            "requested_artifacts": requested_artifacts,
            "artifact_statuses": upstream_statuses,
            "existing_cicd_artifacts": detected_existing,
            "requested_cicd_artifacts": requested_cicd,
            "candidate_cicd_artifacts": candidate_paths,
            "prototype_scope": handoff_context.get(
                "prototype_scope",
                "artifact_generation_only",
            ),
            "execution_policy": handoff_context.get("execution_policy")
            or {
                "real_deployment_executed": False,
                "docker_build_executed": False,
                "docker_push_executed": False,
                "kubectl_apply_executed": False,
                "terraform_apply_executed": False,
                "generated_scripts_are_artifacts_only": True,
            },
        }

    def _normalize_artifact_groups(
        self,
        artifact_groups: dict[str, Any],
    ) -> dict[str, list[str]]:
        return {
            "infrastructure": self._normalize_paths(artifact_groups.get("infrastructure") or []),
            "cicd": self._normalize_paths(artifact_groups.get("cicd") or []),
            "deployment": self._normalize_paths(artifact_groups.get("deployment") or []),
            "security": self._normalize_paths(artifact_groups.get("security") or []),
        }

    def _normalize_artifact_targets(
        self,
        artifact_targets: dict[str, Any],
    ) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in artifact_targets.items():
            if isinstance(value, list):
                normalized[key] = self._normalize_paths(value)
            elif isinstance(value, str):
                normalized[key] = self._normalize_path(value)
            else:
                normalized[key] = deepcopy(value)
        return normalized

    def _normalize_status_paths(
        self,
        statuses: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in statuses:
            entry = deepcopy(item)
            if entry.get("path"):
                entry["path"] = self._normalize_path(entry["path"])
            normalized.append(entry)
        return normalized

    def _detect_requested_cicd_artifacts(
        self,
        *,
        requested_artifacts: list[str],
        artifact_targets: dict[str, Any],
    ) -> list[str]:
        requested = {
            self.DEFAULT_WORKFLOW_TARGET
            for path in requested_artifacts
            if self.contract_service.is_supported_cicd_artifact(path)
        }

        for path in artifact_targets.get("cicd") or []:
            normalized = self._normalize_path(path)
            if self.contract_service.is_supported_cicd_artifact(normalized):
                requested.add(self.DEFAULT_WORKFLOW_TARGET)

        return sorted(requested)

    def _build_candidate_paths(
        self,
        *,
        requested: list[str],
    ) -> list[str]:
        candidates = sorted(set(requested))
        if candidates:
            return candidates
        return [self.DEFAULT_WORKFLOW_TARGET]

    def _normalize_paths(self, paths: list[str]) -> list[str]:
        return sorted(
            {
                self._normalize_path(path)
                for path in paths
                if str(path or "").strip()
            }
        )

    def _normalize_path(self, path: str) -> str:
        return str(path).replace("\\", "/").strip()
