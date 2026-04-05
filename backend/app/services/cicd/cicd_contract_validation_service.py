from __future__ import annotations

from copy import deepcopy
from typing import Any

import yaml

from backend.app.services.cicd.artifact_contract_service import ArtifactContractService


class CicdContractValidationService:
    """Validate and normalize the CI/CD handoff contract produced by the CICD agent.

    The validator keeps the contract deterministic, path-aware, and explicitly
    non-executing. It does not run workflows or shell commands; it only checks that
    generated workflow artifacts remain text files and that the output contract is
    coherent enough for downstream consumers.
    """

    ALLOWED_STATUSES = {"generated", "missing"}
    DEFAULT_WORKFLOW_PATH = ".github/workflows/ci-cd.yml"

    def __init__(self) -> None:
        self.contract_service = ArtifactContractService()

    def normalize_statuses(self, statuses: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Normalize status entries to a stable, controlled status vocabulary."""

        normalized: dict[str, dict[str, Any]] = {}
        for raw_item in statuses or []:
            path = self._normalize_path(raw_item.get("path"))
            if not path:
                continue

            status = self._normalize_status(raw_item.get("status"))
            group = raw_item.get("group") or self.contract_service.classify_artifact(path)
            family = raw_item.get("family") or self.contract_service.classify_family(path)
            generated = bool(raw_item.get("generated")) or status == "generated"
            required = bool(raw_item.get("required"))
            requested = bool(raw_item.get("requested")) or required

            normalized[path] = {
                "path": path,
                "group": group,
                "family": family,
                "status": status,
                "required": required,
                "requested": requested,
                "generated": generated,
                "source": raw_item.get("source") or self._default_source_for(status),
            }

        return [normalized[path] for path in sorted(normalized)]

    def validate_output(self, output: dict[str, Any]) -> dict[str, Any]:
        """Validate the CICD agent output and return a structured readiness report."""

        issues: list[str] = []
        warnings: list[str] = []

        required_fields = [
            "agent",
            "artifact_groups",
            "artifact_targets",
            "requested_artifacts",
            "artifact_statuses",
            "generated_artifacts",
            "handoff_context",
            "execution_policy",
        ]
        for field in required_fields:
            if field not in output:
                issues.append(f"Missing required field: {field}")

        artifact_groups = self._normalize_groups(output.get("artifact_groups"))
        cicd_group = artifact_groups["cicd"]
        requested_artifacts = self._normalize_paths(output.get("requested_artifacts") or [])
        generated_artifacts = self._normalize_paths(output.get("generated_artifacts") or [])
        statuses = self.normalize_statuses(output.get("artifact_statuses") or [])
        status_map = {item["path"]: item for item in statuses}
        artifact_targets = self._normalize_artifact_targets(output.get("artifact_targets") or {})
        artifacts = output.get("artifacts") or {}
        execution_policy = output.get("execution_policy") or {}

        if not isinstance(output.get("handoff_context"), dict):
            issues.append("handoff_context must be a dictionary")

        if output.get("agent") != "CICDAgent":
            issues.append("agent must be CICDAgent")

        self._validate_execution_policy(execution_policy, issues)

        for path in cicd_group:
            if not self.contract_service.is_supported_cicd_artifact(path):
                issues.append(f"Non-CI/CD artifact found in artifact_groups['cicd']: {path}")
            if path not in status_map:
                issues.append(f"Missing artifact status for CI/CD artifact: {path}")

        for path in generated_artifacts:
            if not self.contract_service.is_supported_cicd_artifact(path):
                issues.append(f"Generated artifact is not classified as CI/CD: {path}")
                continue
            if path not in cicd_group:
                issues.append(f"Generated artifact missing from artifact_groups['cicd']: {path}")
            status = status_map.get(path, {}).get("status")
            if status != "generated":
                issues.append(
                    f"Generated artifact {path} must have status 'generated', found '{status}'"
                )
            if path not in artifacts:
                issues.append(f"Generated artifact content missing for {path}")

        for path, item in status_map.items():
            status = item["status"]
            if item["group"] == "cicd" and status not in self.ALLOWED_STATUSES:
                issues.append(f"Unsupported artifact status '{status}' for {path}")
            if item["group"] == "cicd" and not self.contract_service.is_supported_cicd_artifact(path):
                issues.append(f"Unsupported CI/CD artifact path: {path}")
            if item["group"] == "cicd" and path not in cicd_group:
                issues.append(f"CI/CD status path missing from artifact_groups['cicd']: {path}")

        if not artifact_targets.get("cicd") and not cicd_group:
            warnings.append("No CI/CD artifact target was declared")

        for path, content in artifacts.items():
            normalized_path = self._normalize_path(path)
            if normalized_path not in generated_artifacts:
                warnings.append(f"Artifact content declared for non-generated path: {normalized_path}")
            if not isinstance(content, str):
                issues.append(f"Artifact {normalized_path} must be text content")
                continue
            if normalized_path.startswith(".github/workflows/"):
                workflow_issues = self._validate_workflow_yaml(normalized_path, content)
                issues.extend(workflow_issues)

        artifact_contract = output.get("artifact_contract")
        if artifact_contract is not None and not isinstance(artifact_contract, dict):
            issues.append("artifact_contract must be a dictionary when present")

        diagnostic = self._build_diagnostic(
            cicd_group=cicd_group,
            generated_artifacts=generated_artifacts,
            statuses=statuses,
            artifact_targets=artifact_targets,
            issues=issues,
        )

        status = "invalid" if issues else "valid"
        if not issues and any(item["status"] == "missing" for item in statuses if item["group"] == "cicd"):
            status = "partial"

        return {
            "status": status,
            "issues": issues,
            "warnings": warnings,
            "normalized_statuses": statuses,
            "normalized_artifact_groups": artifact_groups,
            "diagnostic": diagnostic,
            "allowed_statuses": sorted(self.ALLOWED_STATUSES),
        }

    def _normalize_status(self, status: Any) -> str:
        lowered = str(status or "").strip().lower()
        if lowered in self.ALLOWED_STATUSES:
            return lowered
        if lowered in {"required_generated", "optional_generated", "unexpected_generated"}:
            return "generated"
        if lowered in {"required_missing", "optional_missing", "missing", "partial", "pending", "skipped", "reused", "detected"}:
            return "missing"
        if lowered == "complete":
            return "generated"
        return "missing"

    def _normalize_groups(self, groups: Any) -> dict[str, list[str]]:
        groups = groups or {}
        return {
            "infrastructure": self._normalize_paths(groups.get("infrastructure") or []),
            "cicd": self._normalize_paths(groups.get("cicd") or []),
            "deployment": self._normalize_paths(groups.get("deployment") or []),
            "security": self._normalize_paths(groups.get("security") or []),
        }

    def _normalize_artifact_targets(self, targets: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in (targets or {}).items():
            if isinstance(value, list):
                normalized[key] = self._normalize_paths(value)
            elif isinstance(value, str):
                normalized[key] = self._normalize_path(value)
            else:
                normalized[key] = deepcopy(value)
        return normalized

    def _normalize_paths(self, paths: list[str] | tuple[str, ...]) -> list[str]:
        return sorted(
            {
                self._normalize_path(path)
                for path in paths
                if self._normalize_path(path)
            }
        )

    def _normalize_path(self, path: Any) -> str:
        if path is None:
            return ""
        return str(path).replace("\\", "/").strip()

    def _default_source_for(self, status: str) -> str:
        if status == "generated":
            return "generated"
        return "planned"

    def _validate_execution_policy(
        self,
        execution_policy: dict[str, Any],
        issues: list[str],
    ) -> None:
        required_truthy = (
            "artifact_generation_only",
            "no_real_deployment",
            "non_executing_agent",
            "generated_scripts_are_artifacts_only",
            "artifacts_are_text_only",
        )
        required_falsey = (
            "real_deployment_executed",
            "docker_build_executed",
            "docker_push_executed",
            "kubectl_apply_executed",
            "terraform_apply_executed",
            "helm_executed",
            "git_push_executed",
            "shell_commands_executed",
            "tests_executed_by_agent",
        )

        for key in required_truthy:
            if execution_policy.get(key) is not True:
                issues.append(f"execution_policy.{key} must be True")

        for key in required_falsey:
            if execution_policy.get(key) is not False:
                issues.append(f"execution_policy.{key} must be False")

    def _validate_workflow_yaml(self, path: str, content: str) -> list[str]:
        issues: list[str] = []
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return [f"Workflow YAML is invalid for {path}: {exc}"]

        if not isinstance(parsed, dict):
            return [f"Workflow YAML must parse to an object for {path}"]

        required_keys = ("name", "jobs")
        for key in required_keys:
            if key not in parsed:
                issues.append(f"Workflow YAML missing '{key}' in {path}")
        if "on" not in parsed and True not in parsed:
            issues.append(f"Workflow YAML missing 'on' in {path}")

        jobs = parsed.get("jobs")
        if jobs is not None and not isinstance(jobs, dict):
            issues.append(f"Workflow YAML 'jobs' must be an object in {path}")
        elif isinstance(jobs, dict) and not jobs:
            issues.append(f"Workflow YAML 'jobs' must not be empty in {path}")

        return issues

    def _build_diagnostic(
        self,
        *,
        cicd_group: list[str],
        generated_artifacts: list[str],
        statuses: list[dict[str, Any]],
        artifact_targets: dict[str, Any],
        issues: list[str],
    ) -> dict[str, Any]:
        cicd_statuses = [item for item in statuses if item["group"] == "cicd"]
        return {
            "cicd_artifact_count": len(cicd_group),
            "generated_count": len(generated_artifacts),
            "missing_count": sum(1 for item in cicd_statuses if item["status"] == "missing"),
            "target_paths": deepcopy(artifact_targets.get("cicd") or []),
            "workflow_paths": deepcopy(cicd_group),
            "non_executing_agent": not issues,
        }
