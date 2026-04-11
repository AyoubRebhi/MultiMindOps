from __future__ import annotations

from copy import deepcopy
from typing import Any


class ArtifactContractService:
    """Build and consolidate the cross-agent artifact contract.

    The contract is derived from a single canonical state made of normalized artifact
    statuses. Every other field such as `missing_artifacts`, `artifact_group_status`,
    and `artifact_family_statuses` is computed from that canonical state to avoid
    contradictory views between agents, validators, and the UI.
    """

    GROUPS = ("infrastructure", "cicd", "deployment", "security")
    FINAL_STATUSES = ("generated", "reused", "detected", "skipped", "pending", "missing")
    PRESENT_STATUSES = {"generated", "reused", "detected"}
    STATUS_PRIORITY = {
        "uploaded": 6,
        "generated": 5,
        "reused": 4,
        "detected": 3,
        "pending": 2,
        "skipped": 1,
        "missing": 2,
    }

    def build_contract(
        self,
        *,
        repo_summary: dict[str, Any] | None,
        categorized_files: dict[str, Any] | None,
        key_entrypoints: list[str] | None,
        plan: dict[str, Any] | None,
        infrastructure: dict[str, Any] | None,
        validation: dict[str, Any] | None,
        artifact_statuses: list[dict[str, Any]] | None = None,
        artifact_groups: dict[str, Any] | None = None,
        artifact_targets: dict[str, Any] | None = None,
        requested_artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        repo_summary = deepcopy(repo_summary or {})
        categorized_files = deepcopy(categorized_files or {})
        plan = deepcopy(plan or {})
        infrastructure = deepcopy(infrastructure or {})
        validation = deepcopy(validation or {})
        context_used = deepcopy(infrastructure.get("context_used") or {})

        requested = [
            self._canonicalize_cicd_path(path)
            for path in self._normalize_paths(
                requested_artifacts
                or context_used.get("requested_artifacts")
                or plan.get("approved_artifacts")
                or plan.get("required_artifacts")
                or []
            )
        ]
        required = [
            self._canonicalize_cicd_path(path)
            for path in self._normalize_paths(
                validation.get("required_artifacts") or requested
            )
        ]
        normalized_targets = self.normalize_artifact_targets(
            artifact_targets or context_used.get("artifact_targets") or {}
        )
        inferred_generated_from_artifacts = self.infer_generated_artifacts(
            infrastructure.get("artifacts") or {},
            normalized_targets,
        )
        seeded_groups = self._normalize_artifact_groups(artifact_groups or {})
        incoming_statuses = artifact_statuses or validation.get("artifact_statuses") or []
        incoming_statuses = list(incoming_statuses) + [
            {
                "path": path,
                "status": "generated",
                "required": path in set(required),
                "requested": path in set(requested),
                "generated": True,
                "source": "generated",
            }
            for path in sorted(
                set(self._normalize_paths(infrastructure.get("generated_artifacts") or []))
                | set(inferred_generated_from_artifacts)
            )
        ]
        incoming_statuses = list(incoming_statuses) + self._resolved_uploaded_env_statuses(
            context_used=context_used,
            requested=requested,
            required=required,
            normalized_targets=normalized_targets,
        )

        canonical_statuses = self.normalize_artifact_statuses(
            incoming_statuses,
            requested_artifacts=requested,
            required_artifacts=required,
            artifact_groups=seeded_groups,
        )

        generated_artifacts = self.derive_generated_artifacts(canonical_statuses)
        missing_artifacts = self.derive_missing_artifacts(canonical_statuses)
        all_paths = sorted(
            set(requested)
            | set(self._collect_paths_from_groups(seeded_groups))
            | {item["path"] for item in canonical_statuses}
        )
        final_groups = self.group_artifacts(all_paths)
        artifact_group_status = self.group_status_from_statuses(canonical_statuses)
        artifact_family_statuses = self.build_family_statuses_from_statuses(
            canonical_statuses
        )
        enriched_categorized_files = self.enrich_categorized_files(
            categorized_files,
            canonical_statuses,
        )
        enriched_repo_summary = self.enrich_repo_summary(
            repo_summary,
            canonical_statuses,
            enriched_categorized_files,
        )

        return {
            "prototype_scope": "artifact_generation_only",
            "execution_policy": self.default_execution_policy(),
            "requested_artifacts": requested,
            "required_artifacts": required,
            "generated_artifacts": generated_artifacts,
            "missing_artifacts": missing_artifacts,
            "artifact_targets": normalized_targets,
            "artifact_groups": final_groups,
            "artifact_group_status": artifact_group_status,
            "artifact_statuses": canonical_statuses,
            "artifact_family_statuses": artifact_family_statuses,
            "has_ci_cd": enriched_repo_summary.get("has_ci_cd", False),
            "ci_cd_files": enriched_categorized_files.get("ci_cd_files", []),
            "existing_cicd_artifacts": self._existing_cicd_artifacts(canonical_statuses),
            "handoff_context": {
                "repo_summary": enriched_repo_summary,
                "categorized_files": enriched_categorized_files,
                "key_entrypoints": key_entrypoints
                or enriched_repo_summary.get("key_entrypoints")
                or [],
                "runtime": enriched_repo_summary.get("runtime") or {},
                "services": enriched_repo_summary.get("services") or [],
                "environment_variables": enriched_repo_summary.get("environment_variables")
                or [],
                "sanitized_env_context": enriched_repo_summary.get("sanitized_env_context")
                or {},
                "validation_status": validation.get("status"),
                "artifact_groups": final_groups,
                "requested_artifacts": requested,
                "generated_artifacts": generated_artifacts,
                "missing_artifacts": missing_artifacts,
                "artifact_targets": normalized_targets,
                "infrastructure_context": context_used,
                "has_ci_cd": enriched_repo_summary.get("has_ci_cd", False),
                "ci_cd_files": enriched_categorized_files.get("ci_cd_files", []),
                "existing_cicd_artifacts": self._existing_cicd_artifacts(canonical_statuses),
            },
        }

    def default_execution_policy(self) -> dict[str, Any]:
        return {
            "artifact_generation_only": True,
            "no_real_deployment": True,
            "non_executing_agent": True,
            "real_deployment_executed": False,
            "docker_build_executed": False,
            "docker_push_executed": False,
            "kubectl_apply_executed": False,
            "terraform_apply_executed": False,
            "helm_executed": False,
            "git_push_executed": False,
            "shell_commands_executed": False,
            "tests_executed_by_agent": False,
            "generated_scripts_are_artifacts_only": True,
            "artifacts_are_text_only": True,
        }

    def is_supported_cicd_artifact(self, path: str | None) -> bool:
        lowered = self._normalize_path(path).lower()
        return lowered.startswith(".github/workflows/") and lowered.endswith(
            (".yml", ".yaml")
        )

    def infer_generated_artifacts(
        self,
        artifacts: dict[str, Any] | None,
        artifact_targets: dict[str, Any] | None,
    ) -> list[str]:
        artifacts = artifacts or {}
        artifact_targets = self.normalize_artifact_targets(artifact_targets or {})
        key_to_file = {
            "dockerfile": artifact_targets.get("dockerfile") or "Dockerfile",
            "dockerignore": ".dockerignore",
            "docker_compose": artifact_targets.get("docker_compose") or "docker-compose.yml",
            "env_example": (
                (artifact_targets.get("env_files") or [".env.example"])[0]
                if artifact_targets.get("env_files")
                else ".env.example"
            ),
            "build_script": "scripts/build.sh",
            "deploy_script": "scripts/deploy.sh",
            "test_script": "scripts/test.sh",
            "security_scan_config": ".github/workflows/security-scan.yml",
            "kubernetes_manifests": (
                (artifact_targets.get("kubernetes") or ["kubernetes/app.yaml"])[0]
            ),
            "kubernetes_deployment": self._find_target_path(
                artifact_targets.get("kubernetes") or [],
                "deployment.yaml",
            )
            or "kubernetes/deployment.yaml",
            "kubernetes_service": self._find_target_path(
                artifact_targets.get("kubernetes") or [],
                "service.yaml",
            )
            or "kubernetes/service.yaml",
            "kubernetes_configmap": self._find_target_path(
                artifact_targets.get("kubernetes") or [],
                "configmap.yaml",
            )
            or "kubernetes/configmap.yaml",
            "terraform_main": self._find_target_path(
                artifact_targets.get("terraform") or [],
                "main.tf",
            )
            or "terraform/main.tf",
            "terraform_variables": self._find_target_path(
                artifact_targets.get("terraform") or [],
                "variables.tf",
            )
            or "terraform/variables.tf",
            "terraform_outputs": self._find_target_path(
                artifact_targets.get("terraform") or [],
                "output.tf",
            )
            or self._find_target_path(
                artifact_targets.get("terraform") or [],
                "outputs.tf",
            )
            or "terraform/output.tf",
        }
        inferred = []
        for key, path in key_to_file.items():
            if str(artifacts.get(key) or "").strip():
                inferred.append(path)
        return self._normalize_paths(inferred)

    def infer_uploaded_env_artifacts(
        self,
        *,
        context_used: dict[str, Any] | None,
        normalized_targets: dict[str, Any] | None,
        requested_artifacts: list[str] | None,
    ) -> list[str]:
        context_used = context_used or {}
        normalized_targets = normalized_targets or {}
        uploaded_env_files = context_used.get("uploaded_env_files") or []
        if not uploaded_env_files and not context_used.get("uploaded_env_provided"):
            return []

        requested_env_paths = [
            path for path in self._normalize_paths(requested_artifacts or [])
            if self.classify_family(path) == "env"
        ]
        target_env_paths = self._normalize_paths(normalized_targets.get("env_files") or [])
        resolved_paths = requested_env_paths or target_env_paths
        if not resolved_paths:
            return []
        return self._normalize_paths(resolved_paths)

    def normalize_artifact_statuses(
        self,
        artifact_statuses: list[dict[str, Any]] | None,
        *,
        requested_artifacts: list[str] | None = None,
        required_artifacts: list[str] | None = None,
        artifact_groups: dict[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        requested_set = {
            self._canonicalize_cicd_path(path)
            for path in self._normalize_paths(requested_artifacts or [])
        }
        required_set = {
            self._canonicalize_cicd_path(path)
            for path in self._normalize_paths(required_artifacts or requested_artifacts or [])
        }
        grouped_paths = {
            self._canonicalize_cicd_path(path)
            for path in self._collect_paths_from_groups(artifact_groups or {})
        }

        merged: dict[str, dict[str, Any]] = {}

        for item in artifact_statuses or []:
            path = self._normalize_path(item.get("path"))
            if not path:
                continue

            canonical_group = self.classify_artifact(path)
            if canonical_group == "cicd":
                path = ".github/workflows/ci-cd.yml"
            status = self.normalize_status(item.get("status"))
            canonical_family = self.classify_family(path)
            if canonical_group == "cicd":
                status = "generated" if status == "generated" else "missing"

            source = item.get("source") or self._default_source_for_status(status)
            if canonical_group == "cicd":
                source = "generated" if status == "generated" else "planned"

            normalized_item = {
                "path": path,
                "group": canonical_group,
                "family": canonical_family,
                "status": status,
                "required": bool(item.get("required")) or path in required_set,
                "requested": bool(item.get("requested"))
                or path in requested_set
                or bool(item.get("required")),
                "generated": bool(item.get("generated")) or status == "generated",
                "source": source,
            }
            self._merge_status_entry(merged, normalized_item)

        for path in sorted(requested_set | required_set | grouped_paths):
            if self.classify_artifact(path) == "cicd":
                path = ".github/workflows/ci-cd.yml"
            if path in merged:
                merged[path]["required"] = merged[path]["required"] or path in required_set
                merged[path]["requested"] = merged[path]["requested"] or path in requested_set
                continue

            default_status = "missing" if self.classify_artifact(path) == "cicd" else "pending"
            merged[path] = {
                "path": path,
                "group": self.classify_artifact(path),
                "family": self.classify_family(path),
                "status": default_status,
                "required": path in required_set,
                "requested": path in requested_set or path in required_set,
                "generated": False,
                "source": "planned",
            }

        return [merged[path] for path in sorted(merged)]

    def derive_generated_artifacts(
        self,
        artifact_statuses: list[dict[str, Any]] | None,
    ) -> list[str]:
        return sorted(
            {
                item["path"]
                for item in artifact_statuses or []
                if item.get("status") == "generated"
            }
        )

    def derive_missing_artifacts(
        self,
        artifact_statuses: list[dict[str, Any]] | None,
    ) -> list[str]:
        statuses = artifact_statuses or []
        return sorted(
            {
                item["path"]
                for item in statuses
                if item.get("required")
                and not self._is_present_status(item.get("status"))
                and not self._is_satisfied_by_equivalent(item, statuses)
            }
        )

    def group_artifacts(self, artifact_paths: list[str] | None) -> dict[str, list[str]]:
        groups = {group: [] for group in self.GROUPS}
        for path in self._normalize_paths(artifact_paths or []):
            groups[self.classify_artifact(path)].append(path)
        return {group: sorted(set(items)) for group, items in groups.items()}

    def group_status(
        self,
        *,
        requested_artifacts: list[str],
        generated_artifacts: list[str],
        missing_artifacts: list[str],
    ) -> dict[str, dict[str, list[str]]]:
        statuses = self.normalize_artifact_statuses(
            [
                {
                    "path": path,
                    "status": "generated",
                    "requested": path in set(requested_artifacts or []),
                    "required": path in set(requested_artifacts or []),
                    "generated": True,
                }
                for path in generated_artifacts or []
            ]
            + [
                {
                    "path": path,
                    "status": "pending",
                    "requested": True,
                    "required": True,
                    "generated": False,
                }
                for path in missing_artifacts or []
            ],
            requested_artifacts=requested_artifacts,
            required_artifacts=requested_artifacts,
        )
        return self.group_status_from_statuses(statuses)

    def group_status_from_statuses(
        self,
        artifact_statuses: list[dict[str, Any]] | None,
    ) -> dict[str, dict[str, list[str]]]:
        statuses = artifact_statuses or []
        missing = set(self.derive_missing_artifacts(statuses))
        grouped: dict[str, dict[str, list[str]]] = {
            group: {
                "requested": [],
                "generated": [],
                "resolved": [],
                "missing": [],
            }
            for group in self.GROUPS
        }

        for item in statuses:
            group = item["group"]
            path = item["path"]
            if item.get("requested"):
                grouped[group]["requested"].append(path)
            if item.get("status") == "generated":
                grouped[group]["generated"].append(path)
            if self._is_present_status(item.get("status")):
                grouped[group]["resolved"].append(path)
            if path in missing:
                grouped[group]["missing"].append(path)

        return {
            group: {
                key: sorted(set(values))
                for key, values in payload.items()
            }
            for group, payload in grouped.items()
        }

    def build_artifact_statuses(
        self,
        *,
        requested_artifacts: list[str],
        required_artifacts: list[str],
        generated_artifacts: list[str],
    ) -> list[dict[str, Any]]:
        return self.normalize_artifact_statuses(
            [
                {
                    "path": path,
                    "status": "generated",
                    "requested": path in set(requested_artifacts or []),
                    "required": path in set(required_artifacts or []),
                    "generated": True,
                }
                for path in generated_artifacts or []
            ],
            requested_artifacts=requested_artifacts,
            required_artifacts=required_artifacts,
        )

    def build_family_statuses(
        self,
        *,
        requested_artifacts: list[str],
        generated_artifacts: list[str],
    ) -> list[dict[str, Any]]:
        statuses = self.build_artifact_statuses(
            requested_artifacts=requested_artifacts,
            required_artifacts=requested_artifacts,
            generated_artifacts=generated_artifacts,
        )
        return self.build_family_statuses_from_statuses(statuses)

    def build_family_statuses_from_statuses(
        self,
        artifact_statuses: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        statuses = artifact_statuses or []
        missing = set(self.derive_missing_artifacts(statuses))
        families: dict[str, dict[str, set[str]]] = {}

        for item in statuses:
            family = item["family"]
            bucket = families.setdefault(
                family,
                {
                    "requested": set(),
                    "generated": set(),
                    "resolved": set(),
                    "missing": set(),
                },
            )
            path = item["path"]
            if item.get("requested"):
                bucket["requested"].add(path)
            if item.get("status") == "generated":
                bucket["generated"].add(path)
            if self._is_present_status(item.get("status")):
                bucket["resolved"].add(path)
            if path in missing:
                bucket["missing"].add(path)

        results = []
        for family, payload in sorted(families.items()):
            requested = sorted(payload["requested"])
            generated = sorted(payload["generated"])
            resolved = sorted(payload["resolved"])
            missing_items = sorted(payload["missing"])

            if requested and not missing_items and resolved:
                status = "complete"
            elif requested and missing_items and resolved:
                status = "partial"
            elif requested and missing_items:
                status = "missing"
            elif resolved:
                status = "unexpected"
            else:
                status = "missing"

            results.append(
                {
                    "family": family,
                    "status": status,
                    "requested": requested,
                    "generated": generated,
                    "resolved": resolved,
                    "missing": missing_items,
                }
            )
        return results

    def normalize_status(self, status: Any) -> str:
        lowered = str(status or "").strip().lower()
        if lowered in self.FINAL_STATUSES:
            return lowered
        if lowered in {"required_generated", "optional_generated", "unexpected_generated"}:
            return "generated"
        if lowered in {"required_missing", "optional_missing"}:
            return "missing"
        if lowered == "missing":
            return "missing"
        if lowered == "complete":
            return "generated"
        if lowered == "partial":
            return "pending"
        return "pending"

    def normalize_artifact_targets(self, artifact_targets: dict[str, Any] | None) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in (artifact_targets or {}).items():
            if isinstance(value, list):
                normalized[key] = [
                    self._canonicalize_cicd_path(path)
                    for path in self._normalize_paths(value)
                ]
            elif isinstance(value, str):
                normalized[key] = self._canonicalize_cicd_path(value)
            else:
                normalized[key] = deepcopy(value)
        return normalized

    def enrich_categorized_files(
        self,
        categorized_files: dict[str, Any] | None,
        artifact_statuses: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        categorized_files = deepcopy(categorized_files or {})
        ci_cd_paths = sorted(
            {
                item["path"]
                for item in artifact_statuses or []
                if item["group"] == "cicd"
                and self.is_supported_cicd_artifact(item["path"])
                and self._is_present_status(item["status"])
            }
        )
        categorized_files["ci_cd_files"] = ci_cd_paths
        return categorized_files

    def enrich_repo_summary(
        self,
        repo_summary: dict[str, Any] | None,
        artifact_statuses: list[dict[str, Any]] | None,
        categorized_files: dict[str, Any] | None,
    ) -> dict[str, Any]:
        repo_summary = deepcopy(repo_summary or {})
        categorized_files = categorized_files or {}

        ci_cd_files = self._normalize_paths(categorized_files.get("ci_cd_files") or [])
        if not ci_cd_files:
            ci_cd_files = sorted(
                {
                    item["path"]
                    for item in artifact_statuses or []
                    if item["group"] == "cicd"
                    and self.is_supported_cicd_artifact(item["path"])
                    and self._is_present_status(item["status"])
                }
            )

        repo_summary["ci_cd_files"] = ci_cd_files
        repo_summary["has_ci_cd"] = bool(ci_cd_files)
        return repo_summary

    def classify_artifact(self, path: str) -> str:
        lowered = self._normalize_path(path).lower()
        if any(marker in lowered for marker in ("security", "trivy", "sast", "secret-scan")):
            return "security"
        if self.is_supported_cicd_artifact(lowered):
            return "cicd"
        if (
            lowered.startswith("kubernetes/")
            or lowered.startswith("k8s/")
            or lowered.endswith("deployment.yaml")
            or lowered.endswith("service.yaml")
            or lowered.endswith("ingress.yaml")
            or lowered.endswith("configmap.yaml")
            or lowered.endswith("deploy.sh")
        ):
            return "deployment"
        return "infrastructure"

    def classify_family(self, path: str) -> str:
        lowered = self._normalize_path(path).lower()
        if lowered.endswith("dockerfile"):
            return "dockerfile"
        if lowered.endswith(".dockerignore"):
            return "dockerignore"
        if lowered.endswith(
            (
                "docker-compose.yml",
                "docker-compose.yaml",
                "docker-compose.override.yml",
                "docker-compose.override.yaml",
            )
        ):
            return "docker_compose"
        if lowered.endswith((".env", ".env.example")):
            return "env"
        if lowered.startswith("terraform/") or lowered.endswith(".tf"):
            return "terraform"
        if (
            lowered.startswith("kubernetes/")
            or lowered.startswith("k8s/")
            or lowered.endswith((".yaml", ".yml"))
            and any(
                marker in lowered
                for marker in ("deployment", "service", "configmap", "ingress", "statefulset")
            )
        ):
            return "kubernetes"
        if self.is_supported_cicd_artifact(lowered):
            return "cicd"
        if lowered.endswith("build.sh"):
            return "build_script"
        if lowered.endswith("deploy.sh"):
            return "deploy_script"
        return "other"

    def _merge_status_entry(
        self,
        merged: dict[str, dict[str, Any]],
        entry: dict[str, Any],
    ) -> None:
        current = merged.get(entry["path"])
        if not current:
            merged[entry["path"]] = entry
            return

        current_priority = self._status_priority(current)
        new_priority = self._status_priority(entry)
        chosen = dict(entry if new_priority > current_priority else current)

        chosen["required"] = bool(current.get("required")) or bool(entry.get("required"))
        chosen["requested"] = bool(current.get("requested")) or bool(entry.get("requested"))
        chosen["generated"] = bool(current.get("generated")) or bool(entry.get("generated"))
        chosen["group"] = chosen.get("group") or self.classify_artifact(chosen["path"])
        chosen["family"] = chosen.get("family") or self.classify_family(chosen["path"])
        chosen["source"] = chosen.get("source") or current.get("source") or entry.get("source")
        if chosen["source"] == "uploaded" and chosen["family"] == "env":
            chosen["status"] = "detected"
            chosen["generated"] = False
        merged[entry["path"]] = chosen

    def _is_present_status(self, status: Any) -> bool:
        return str(status or "").strip().lower() in self.PRESENT_STATUSES

    def _is_satisfied_by_equivalent(
        self,
        item: dict[str, Any],
        statuses: list[dict[str, Any]],
    ) -> bool:
        if item.get("group") == "cicd":
            return any(
                other["path"] != item["path"]
                and other.get("group") == "cicd"
                and self.is_supported_cicd_artifact(other["path"])
                and self._is_present_status(other.get("status"))
                for other in statuses
            )
        return False

    def _resolved_uploaded_env_statuses(
        self,
        *,
        context_used: dict[str, Any],
        requested: list[str],
        required: list[str],
        normalized_targets: dict[str, Any],
    ) -> list[dict[str, Any]]:
        resolved_paths = self.infer_uploaded_env_artifacts(
            context_used=context_used,
            normalized_targets=normalized_targets,
            requested_artifacts=requested,
        )
        return [
            {
                "path": path,
                "group": self.classify_artifact(path),
                "family": self.classify_family(path),
                "status": "detected",
                "required": path in set(required),
                "requested": path in set(requested),
                "generated": False,
                "source": "uploaded",
            }
            for path in resolved_paths
        ]

    def _find_target_path(self, targets: list[str], filename: str) -> str | None:
        lowered = filename.lower()
        return next(
            (target for target in targets if str(target).lower().endswith(lowered)),
            None,
        )

    def _existing_cicd_artifacts(
        self,
        artifact_statuses: list[dict[str, Any]] | None,
    ) -> list[str]:
        return []

    def _normalize_artifact_groups(self, artifact_groups: dict[str, Any]) -> dict[str, list[str]]:
        return {
            "infrastructure": self._normalize_paths(artifact_groups.get("infrastructure") or []),
            "cicd": self._normalize_paths(artifact_groups.get("cicd") or []),
            "deployment": self._normalize_paths(artifact_groups.get("deployment") or []),
            "security": self._normalize_paths(artifact_groups.get("security") or []),
        }

    def _collect_paths_from_groups(self, artifact_groups: dict[str, Any]) -> list[str]:
        collected: list[str] = []
        for value in (artifact_groups or {}).values():
            if isinstance(value, list):
                collected.extend(value)
        return self._normalize_paths(collected)

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

    def _canonicalize_cicd_path(self, path: str) -> str:
        normalized = self._normalize_path(path)
        if self.is_supported_cicd_artifact(normalized):
            return ".github/workflows/ci-cd.yml"
        return normalized

    def _default_source_for_status(self, status: str) -> str:
        if status == "generated":
            return "generated"
        if status in {"reused", "detected"}:
            return "existing"
        return "planned"

    def _status_priority(self, entry: dict[str, Any]) -> int:
        if entry.get("source") == "uploaded" and entry.get("family") == "env":
            return self.STATUS_PRIORITY["uploaded"]
        return self.STATUS_PRIORITY.get(str(entry.get("status") or ""), 0)
