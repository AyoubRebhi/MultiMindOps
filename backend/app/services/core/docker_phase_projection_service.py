"""DockerPhaseProjectionService — read-only projection of the DOCKER phase.

Assembles the ONE payload the Docker Generation surface consumes
(``GET /api/projects/{pid}/workflows/{wid}/docker``) by RESHAPING data the
DOCKER phase already persisted. It is the Docker analogue of
``WorkflowAnalysisAggregationService`` / ``get_architecture_decision``:

* reads the backing task's ``workflow_state`` (generated artifacts, generation
  metadata, inline validation, corrector analysis),
* reads ``Workflow.phases_state`` for the authoritative DOCKER phase status,
* reads the DB-backed ``Artifact`` row for the Dockerfile's version + approval
  + validation status (the single source of truth for the persisted file).

It NEVER re-runs the InfrastructureAgent, the corrector, or calls an LLM, and it
NEVER mutates workflow state. A workflow that has not reached DOCKER yet projects
to ``generated=False`` with empty (but well-formed) sub-objects.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.schemas.docker_phase import (
    DockerCorrector,
    DockerGenerationMetadata,
    DockerPhaseResponse,
    DockerValidation,
    DockerfileArtifact,
    ValidationIssue,
)
from backend.app.services.core.artifact_service import ArtifactStateResolver
from backend.app.services.core.task_service import TaskService

_DEFAULT_MAX_RETRIES = 3


class DockerPhaseProjectionService:
    """Pure read projection — no generation, no orchestration, no LLM."""

    @staticmethod
    def build(
        db: Session,
        *,
        project_id: str,
        workflow: Workflow,
        task: Optional[Task],
    ) -> DockerPhaseResponse:
        state: Dict[str, Any] = (
            TaskService.load_workflow_state(db, task) if task else {}
        ) or {}

        infra: Dict[str, Any] = state.get("infra") or {}
        generated_artifacts: Dict[str, Any] = dict(infra.get("artifacts") or {})
        latest_artifacts = ArtifactStateResolver.get_latest_artifacts(state)

        original_dockerfile = str(generated_artifacts.get("dockerfile") or "")
        current_dockerfile = str(
            latest_artifacts.get("dockerfile") or original_dockerfile
        )
        generated = bool(current_dockerfile.strip())

        # DB-backed Dockerfile row carries the authoritative version/approval.
        df_row = DockerPhaseProjectionService._dockerfile_row(
            db, project_id=project_id
        )

        dockerfile: Optional[DockerfileArtifact] = None
        if generated:
            # The DB content wins as the canonical "current" when present — it is
            # the persisted artifact later phases build from — but fall back to
            # the edited state content so an un-persisted edit still shows.
            db_content = str(getattr(df_row, "content", "") or "")
            content = db_content or current_dockerfile
            dockerfile = DockerfileArtifact(
                filename="Dockerfile",
                content=content,
                original_content=original_dockerfile or content,
                edited=bool(original_dockerfile)
                and content.strip() != original_dockerfile.strip(),
                version=getattr(df_row, "version", None),
                approval_state=getattr(df_row, "approval_state", None),
                validation_status=getattr(df_row, "validation_status", None),
            )

        metadata = DockerPhaseProjectionService._build_metadata(
            state, infra, dockerfile_content=current_dockerfile
        )
        validation = DockerPhaseProjectionService._build_validation(infra)
        corrector = DockerPhaseProjectionService._build_corrector(
            state, original=original_dockerfile, current=current_dockerfile
        )

        phases_state = workflow.phases_state or {}
        docker_phase_status = (phases_state.get("DOCKER") or {}).get("status")

        return DockerPhaseResponse(
            workflow_id=workflow.id,
            project_id=project_id,
            task_id=getattr(task, "id", None),
            current_phase=workflow.current_phase,
            status=workflow.status,
            docker_phase_status=docker_phase_status,
            generated=generated,
            dockerfile=dockerfile,
            metadata=metadata,
            validation=validation,
            corrector=corrector,
            has_dockerignore=bool(
                latest_artifacts.get("dockerignore")
                or generated_artifacts.get("dockerignore")
            ),
            has_compose=bool(
                latest_artifacts.get("docker_compose")
                or generated_artifacts.get("docker_compose")
            ),
        )

    # ── Dockerfile DB row ─────────────────────────────────────────────────────

    @staticmethod
    def _dockerfile_row(db: Session, *, project_id: str) -> Optional[Artifact]:
        """The persisted Dockerfile artifact (canonical subtype or filename)."""
        rows = (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.artifact_type == "docker",
            )
            .all()
        )
        for row in rows:
            sub = (row.artifact_subtype or "").lower()
            if sub == "dockerfile":
                return row
        return None

    # ── Generation metadata ───────────────────────────────────────────────────

    @staticmethod
    def _build_metadata(
        state: Dict[str, Any],
        infra: Dict[str, Any],
        *,
        dockerfile_content: str,
    ) -> DockerGenerationMetadata:
        infra_gen = infra.get("infrastructure_generation") or {}
        gen_meta = infra_gen.get("generation_metadata") or {}
        context_used = state.get("context_used") or infra.get("context_used") or {}
        runtime = context_used.get("runtime") or {}
        docker_phase = state.get("docker_phase") or {}

        language = (
            gen_meta.get("language")
            or DockerPhaseProjectionService._first(runtime.get("languages"))
        )
        framework = (
            gen_meta.get("framework")
            or DockerPhaseProjectionService._first(runtime.get("frameworks"))
        )
        detected_runtime = framework or language

        container_type = (
            context_used.get("project_type")
            or DockerPhaseProjectionService._main_service_type(context_used)
            or gen_meta.get("blueprint_id")
        )

        return DockerGenerationMetadata(
            detected_runtime=detected_runtime,
            language=language,
            framework=framework,
            base_image=DockerPhaseProjectionService._extract_base_image(
                dockerfile_content
            ),
            port=DockerPhaseProjectionService._extract_port(
                dockerfile_content, context_used
            ),
            build_strategy=gen_meta.get("strategy"),
            container_type=container_type,
            blueprint_id=gen_meta.get("blueprint_id"),
            # Prefer the phase-level contract metadata; fall back to the infra
            # response copy so a fallback generation is never mislabeled "llm".
            used_llm=bool(
                docker_phase.get("used_llm", infra.get("used_llm", True))
            ),
            fallback_used=bool(
                docker_phase.get("fallback_used", infra.get("fallback_used", False))
            ),
            generation_mode=str(
                docker_phase.get(
                    "generation_mode", infra.get("generation_mode", "llm")
                )
            ),
        )

    # ── Validation ────────────────────────────────────────────────────────────

    @staticmethod
    def _build_validation(infra: Dict[str, Any]) -> DockerValidation:
        infra_gen = infra.get("infrastructure_generation") or {}
        structured = infra_gen.get("validation") or {}

        if structured:
            errors = DockerPhaseProjectionService._issues(structured.get("errors"))
            warnings = DockerPhaseProjectionService._issues(structured.get("warnings"))
            recs = DockerPhaseProjectionService._issues(
                structured.get("recommendations")
            )
            # Fold static COPY validation issues in when present.
            static_val = infra_gen.get("static_validation") or {}
            for issue in DockerPhaseProjectionService._issues(
                static_val.get("issues")
            ):
                bucket = errors if (issue.severity or "") in ("error", "critical") else warnings
                bucket.append(issue)

            valid = not errors
            status = "failed" if errors else ("warnings" if warnings else "passed")
            return DockerValidation(
                status=status,
                valid=valid,
                errors=errors,
                warnings=warnings,
                recommendations=recs,
            )

        # Fall back to the artifact-level validation summary.
        summary = infra.get("validation_summary") or {}
        if summary:
            issues = summary.get("issues") or []
            errors = [
                DockerPhaseProjectionService._issue(i)
                for i in issues
                if (i.get("severity") if isinstance(i, dict) else "") in ("error", "critical")
            ]
            warnings = [
                DockerPhaseProjectionService._issue(i)
                for i in issues
                if (i.get("severity") if isinstance(i, dict) else "") == "warning"
            ]
            raw_status = str(summary.get("status") or "").lower()
            status = (
                "passed"
                if raw_status in ("passed", "ok", "valid", "success")
                else ("failed" if errors else ("warnings" if warnings else "passed"))
            )
            return DockerValidation(
                status=status,
                valid=not errors,
                errors=errors,
                warnings=warnings,
                recommendations=[],
            )

        return DockerValidation(status="not_run", valid=True)

    # ── Corrector ─────────────────────────────────────────────────────────────

    @staticmethod
    def _build_corrector(
        state: Dict[str, Any],
        *,
        original: str,
        current: str,
    ) -> DockerCorrector:
        corrector_state = (state.get("execution") or {}).get("corrector") or {}
        analysis = corrector_state.get("analysis")

        # A correction is "applied" when the live Dockerfile diverges from the
        # originally generated one. That divergent content IS the corrected file
        # shown side-by-side; absent a divergence we expose only the proposed
        # fixes/patches carried inside ``analysis``.
        corrected_dockerfile = None
        if original and current and current.strip() != original.strip():
            corrected_dockerfile = current

        return DockerCorrector(
            available=bool(analysis),
            status=corrector_state.get("status"),
            retry_count=int(corrector_state.get("retry_count", 0) or 0),
            max_retries=int(
                corrector_state.get("max_retries", _DEFAULT_MAX_RETRIES)
                or _DEFAULT_MAX_RETRIES
            ),
            analysis=analysis if isinstance(analysis, dict) else None,
            corrected_dockerfile=corrected_dockerfile,
        )

    # ── Small helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _issues(raw: Any) -> list[ValidationIssue]:
        if not isinstance(raw, list):
            return []
        return [DockerPhaseProjectionService._issue(item) for item in raw]

    @staticmethod
    def _issue(item: Any) -> ValidationIssue:
        if isinstance(item, dict):
            return ValidationIssue(
                rule=item.get("rule"),
                message=str(item.get("message") or item.get("text") or ""),
                severity=item.get("severity"),
                section_id=item.get("section_id"),
            )
        return ValidationIssue(message=str(item))

    @staticmethod
    def _first(seq: Any) -> Optional[str]:
        if isinstance(seq, (list, tuple)) and seq:
            return str(seq[0])
        if isinstance(seq, str) and seq:
            return seq
        return None

    @staticmethod
    def _main_service_type(context_used: Dict[str, Any]) -> Optional[str]:
        main = context_used.get("main_service")
        services = context_used.get("services") or []
        if isinstance(services, list):
            for svc in services:
                if not isinstance(svc, dict):
                    continue
                if main and svc.get("name") == main:
                    return svc.get("framework") or svc.get("type")
            if services and isinstance(services[0], dict):
                return services[0].get("framework") or services[0].get("type")
        return None

    @staticmethod
    def _extract_base_image(dockerfile: str) -> Optional[str]:
        if not dockerfile:
            return None
        # The runtime stage = the LAST FROM (multi-stage builds copy into it).
        matches = re.findall(
            r"(?im)^\s*FROM\s+(\S+?)(?:\s+AS\s+\S+)?\s*$", dockerfile
        )
        return matches[-1] if matches else None

    @staticmethod
    def _extract_port(
        dockerfile: str, context_used: Dict[str, Any]
    ) -> Optional[str]:
        if dockerfile:
            m = re.search(r"(?im)^\s*EXPOSE\s+(\d+)", dockerfile)
            if m:
                return m.group(1)
        services = context_used.get("services") or []
        if isinstance(services, list):
            for svc in services:
                if isinstance(svc, dict) and svc.get("port"):
                    return str(svc.get("port"))
        return None
