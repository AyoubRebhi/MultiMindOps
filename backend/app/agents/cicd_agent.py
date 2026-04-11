from __future__ import annotations

from typing import Any

from backend.app.agents.base_agent import BaseAgent
from backend.app.services.cicd.artifact_contract_service import ArtifactContractService
from backend.app.services.cicd.cicd_contract_validation_service import (
    CicdContractValidationService,
)
from backend.app.services.cicd.cicd_handoff_service import CicdHandoffService
from backend.app.services.cicd.cicd_workflow_builder_service import (
    CicdWorkflowBuilderService,
)
from backend.app.services.rag.rag_pipeline_service import RAGPipelineService


class CICDAgent(BaseAgent):
    """Minimal Sprint 3 foundation for CI/CD artifact preparation.

    Bloc A only reads the upstream handoff contract, detects existing CI/CD artifacts,
    normalizes statuses, and returns a stable output contract for the next iteration.
    It never executes deployment, container, or infrastructure commands.
    """

    def __init__(self) -> None:
        super().__init__(name="CICDAgent")
        self.handoff_service = CicdHandoffService()
        self.contract_service = ArtifactContractService()
        self.validation_service = CicdContractValidationService()
        self.workflow_builder = CicdWorkflowBuilderService()
        # RAG sémantique pour enrichir les workflows CI/CD générés
        self._rag_pipeline = RAGPipelineService()

    def run(self, *args, **kwargs) -> dict[str, Any]:
        """BaseAgent compatibility entrypoint."""

        handoff_context = kwargs.get("handoff_context")
        github_token = kwargs.get("github_token")
        if handoff_context is None and args:
            handoff_context = args[0]
        return self.generate_cicd_artifacts(handoff_context or {}, github_token=github_token)

    def generate_cicd_artifacts(
        self,
        handoff_context: dict[str, Any],
        *,
        github_token: str | None = None,
    ) -> dict[str, Any]:
        """Analyze the upstream artifact contract and prepare a CI/CD-only handoff.

        The returned payload remains deterministic and side-effect free. Bloc B adds
        GitHub Actions workflow generation under `.github/workflows/` while preserving
        path-awareness and never executing any delivery command.
        """

        normalized_handoff = self.handoff_service.normalize(
            handoff_context,
            github_token=github_token,
        )
        runtime_info = self.workflow_builder.detect_project_runtime(normalized_handoff)

        # Enrichir le contexte avec le RAG sémantique CI/CD
        rag_context = self._retrieve_cicd_context(normalized_handoff, runtime_info)
        if rag_context:
            normalized_handoff["rag_cicd_context"] = rag_context

        artifacts, cicd_statuses, generation_notes = self.workflow_builder.generate_workflow_artifacts(
            normalized_handoff,
        )
        merged_statuses = self.validation_service.normalize_statuses(self._merge_statuses(
            normalized_handoff.get("artifact_statuses") or [],
            cicd_statuses,
        ))

        artifact_groups = dict(normalized_handoff.get("artifact_groups") or {})
        artifact_groups["cicd"] = normalized_handoff.get("candidate_cicd_artifacts") or []
        artifact_targets = normalized_handoff.get("artifact_targets") or {}
        requested_artifacts = normalized_handoff.get("requested_artifacts") or []

        output = {
            "agent": self.name,
            "prototype_scope": "artifact_generation_only",
            "execution_policy": self.contract_service.default_execution_policy(),
            "artifact_groups": artifact_groups,
            "artifact_targets": artifact_targets,
            "requested_artifacts": requested_artifacts,
            "generated_artifacts": sorted(artifacts.keys()),
            "artifact_statuses": merged_statuses,
            "artifacts": artifacts,
            "handoff_context": {
                **normalized_handoff,
                "detected_runtime": runtime_info,
                "artifact_groups": artifact_groups,
                "artifact_statuses": merged_statuses,
            },
            "summary": self._build_summary(cicd_statuses, runtime_info),
            "notes": [
                f"Detected runtime: {runtime_info['language']} ({runtime_info['framework']}).",
                "CI/CD output is limited to GitHub Actions workflow artifacts.",
                "Infrastructure and deployment artifacts remain owned by upstream agents.",
            ]
            + [f"{path}: {reason}" for path, reason in generation_notes.items()],
        }
        output["artifact_contract"] = self.contract_service.build_contract(
            repo_summary=(normalized_handoff.get("repo_summary") or {}),
            categorized_files={
                "ci_cd_files": normalized_handoff.get("ci_cd_files") or [],
                "deployment_files": normalized_handoff.get("deployment_files") or [],
            },
            key_entrypoints=normalized_handoff.get("key_entrypoints") or [],
            plan={
                "approved_artifacts": normalized_handoff.get("requested_artifacts") or [],
                "required_artifacts": normalized_handoff.get("requested_artifacts") or [],
            },
            infrastructure={
                "generated_artifacts": output["generated_artifacts"],
                "context_used": {
                    "requested_artifacts": normalized_handoff.get("requested_artifacts") or [],
                    "artifact_targets": artifact_targets,
                },
            },
            validation={
                "required_artifacts": requested_artifacts,
                "artifact_statuses": merged_statuses,
            },
            artifact_statuses=merged_statuses,
            artifact_groups=artifact_groups,
            artifact_targets=artifact_targets,
            requested_artifacts=requested_artifacts,
        )
        output["artifact_groups"] = output["artifact_contract"]["artifact_groups"]
        output["artifact_statuses"] = output["artifact_contract"]["artifact_statuses"]
        output["generated_artifacts"] = [
            item["path"]
            for item in output["artifact_contract"]["artifact_statuses"]
            if item.get("group") == "cicd" and item.get("status") == "generated"
        ]
        output["requested_artifacts"] = output["artifact_contract"]["requested_artifacts"]
        output["artifact_entries"] = self._build_artifact_entries(
            normalized_handoff=normalized_handoff,
            artifact_statuses=output["artifact_statuses"],
            generated_artifacts=set(output["generated_artifacts"]),
        )
        output["handoff_context"] = {
            **output["handoff_context"],
            "artifact_groups": output["artifact_groups"],
            "artifact_statuses": output["artifact_statuses"],
            "generated_artifacts": output["generated_artifacts"],
            "missing_artifacts": output["artifact_contract"]["missing_artifacts"],
            "has_ci_cd": output["artifact_contract"]["has_ci_cd"],
            "ci_cd_files": output["artifact_contract"]["ci_cd_files"],
            "existing_cicd_artifacts": output["artifact_contract"]["existing_cicd_artifacts"],
        }
        output["validation"] = self.validation_service.validate_output(output)
        output["readiness_summary"] = self._build_readiness_summary(output["validation"])
        return output

    def _merge_statuses(
        self,
        upstream_statuses: list[dict[str, Any]],
        cicd_statuses: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Keep upstream non-CI/CD statuses untouched and replace CI/CD with normalized ones."""

        merged: dict[str, dict[str, Any]] = {}

        for item in upstream_statuses:
            path = item.get("path")
            if not path:
                continue
            if self.contract_service.classify_artifact(path) == "cicd":
                continue
            merged[str(path)] = dict(item)

        for item in cicd_statuses:
            merged[item["path"]] = dict(item)

        return [merged[key] for key in sorted(merged)]

    def _build_summary(
        self,
        cicd_statuses: list[dict[str, Any]],
        runtime_info: dict[str, str],
    ) -> str:
        generated = sum(1 for item in cicd_statuses if item["status"] == "generated")
        missing = sum(1 for item in cicd_statuses if item["status"] == "missing")
        return (
            f"CICD workflows prepared for {runtime_info['language']}: "
            f"{generated} generated, {missing} missing."
        )

    def _build_readiness_summary(self, validation: dict[str, Any]) -> str:
        diagnostic = validation.get("diagnostic") or {}
        return (
            f"CICD contract {validation.get('status', 'unknown')} with "
            f"{diagnostic.get('generated_count', 0)} generated, "
            f"{diagnostic.get('missing_count', 0)} missing workflow artifacts."
        )

    def _retrieve_cicd_context(
        self,
        normalized_handoff: dict[str, Any],
        runtime_info: dict[str, str],
    ) -> str:
        """Récupère le contexte RAG CI/CD depuis Qdrant."""
        try:
            language = runtime_info.get("language", "")
            framework = runtime_info.get("framework", "")
            query = f"github actions ci cd workflow {language} {framework} security scan"

            result = self._rag_pipeline.retrieve_context(
                query=query,
                doc_type="cicd",
                top_k=3,
                use_hybrid=True,
            )
            if result.get("available") and result.get("results"):
                return result["context"]
        except Exception:
            pass
        return ""

    def _build_artifact_entries(
        self,
        *,
        normalized_handoff: dict[str, Any],
        artifact_statuses: list[dict[str, Any]],
        generated_artifacts: set[str],
    ) -> list[dict[str, Any]]:
        entries = []
        for item in artifact_statuses:
            if item.get("group") != "cicd":
                continue

            path = item.get("path")
            if not path:
                continue

            status = str(item.get("status") or "")
            source = "generated" if path in generated_artifacts else "planned"
            entry = {
                "path": path,
                "status": status,
                "source": source,
                "view_url": None,
            }

            entries.append(entry)

        return entries
