"""ProjectContextService.

Persistent project-intelligence layer. Every meaningful phase output (repo
analysis, architecture decision, Docker hints, Terraform topology, validation
rollup) is captured as a ``ProjectContext`` row keyed by ``context_type`` so
later workflow reruns, RAG layers, and recommendation surfaces can consult
project memory instead of re-running expensive agents.

Design rules
------------
1. Upsert by ``(project_id, context_type)`` — there is one canonical
   "repository_summary" per project; history is appended into ``content``
   only when callers explicitly opt in (see ``write_versioned``).
2. ``content`` is JSONB — store small, structured digests, not raw repo
   contents. Raw blobs belong in object storage with an
   ``embedding_reference`` pointer.
3. Extraction logic lives here, NOT in agents. Agents emit state; this
   service classifies state into ProjectContext rows. Keeps agents pure.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import ProjectContext

logger = logging.getLogger(__name__)


# ─── Known context types ────────────────────────────────────────────────────

CONTEXT_REPOSITORY_SUMMARY      = "repository_summary"
CONTEXT_DETECTED_STACK          = "detected_stack"
CONTEXT_DETECTED_SERVICES       = "detected_services"
CONTEXT_ARCHITECTURE_DECISION   = "architecture_decision"
CONTEXT_SELECTED_PLAN           = "selected_plan"
CONTEXT_DOCKER_HINTS            = "docker_hints"
CONTEXT_TERRAFORM_HINTS         = "terraform_hints"
CONTEXT_INFRASTRUCTURE_SUMMARY  = "infrastructure_summary"
CONTEXT_VALIDATION_SUMMARY      = "validation_summary"
CONTEXT_COST_SUMMARY            = "cost_summary"


# ─── Core service ───────────────────────────────────────────────────────────

class ProjectContextService:
    @staticmethod
    def upsert(
        db: Session,
        *,
        project_id: str,
        context_type: str,
        content: Dict[str, Any],
        generated_by: Optional[str] = None,
        embedding_reference: Optional[str] = None,
        commit: bool = True,
    ) -> ProjectContext:
        """Insert or update a single context row.

        ``content`` is shallow-merged with whatever is already stored so that
        partial writes (e.g. only updating validation rollup) do not erase
        earlier fields written by another phase.
        """
        if not content:
            # Nothing to persist — silently skip rather than write empty JSON.
            existing = ProjectContextService.get(db, project_id, context_type)
            return existing  # type: ignore[return-value]

        existing = ProjectContextService.get(db, project_id, context_type)
        merged = dict((existing.content or {}) if existing else {})
        merged.update(content)
        merged["_updated_at"] = datetime.now(timezone.utc).isoformat()

        if existing is None:
            row = ProjectContext(
                project_id=project_id,
                context_type=context_type,
                content=merged,
                generated_by=generated_by,
                embedding_reference=embedding_reference,
            )
            db.add(row)
        else:
            existing.content = merged
            if generated_by:
                existing.generated_by = generated_by
            if embedding_reference:
                existing.embedding_reference = embedding_reference
            row = existing

        if commit:
            db.commit()
            db.refresh(row)
        else:
            db.flush()
        return row

    @staticmethod
    def get(
        db: Session,
        project_id: str,
        context_type: str,
    ) -> Optional[ProjectContext]:
        return (
            db.query(ProjectContext)
            .filter(
                ProjectContext.project_id == project_id,
                ProjectContext.context_type == context_type,
            )
            .first()
        )

    @staticmethod
    def list_for_project(db: Session, project_id: str) -> List[ProjectContext]:
        return (
            db.query(ProjectContext)
            .filter(ProjectContext.project_id == project_id)
            .order_by(ProjectContext.context_type.asc())
            .all()
        )

    # ── Extraction helpers ──────────────────────────────────────────────────
    #
    # These translate a slice of orchestrator state into a digest dictionary.
    # Each helper is conservative: missing keys produce an empty dict, never
    # an exception — orchestrator state shape evolves, and a failed digest
    # must not break a workflow.

    @staticmethod
    def _digest_repo_summary(state: Dict[str, Any]) -> Dict[str, Any]:
        agent_ctx = state.get("agent_context") or {}
        repo_meta = state.get("repository_metadata") or {}
        analysis  = state.get("codebase_analysis") or {}
        return {
            "language":          analysis.get("language") or repo_meta.get("language"),
            "frameworks":        analysis.get("frameworks") or [],
            "build_systems":     analysis.get("build_systems") or [],
            "service_count":     len(analysis.get("services") or []),
            "lines_of_code":     analysis.get("lines_of_code"),
            "has_dockerfile":    bool(analysis.get("has_dockerfile")),
            "has_compose":       bool(analysis.get("has_compose")),
            "has_ci":            bool(analysis.get("has_ci")),
            "application_profile": agent_ctx.get("application_profile") or state.get("application_profile"),
        }

    @staticmethod
    def _digest_detected_stack(state: Dict[str, Any]) -> Dict[str, Any]:
        analysis = state.get("codebase_analysis") or {}
        return {
            "language":      analysis.get("language"),
            "runtime":       analysis.get("runtime"),
            "frameworks":    analysis.get("frameworks") or [],
            "dependencies":  (analysis.get("dependencies") or [])[:50],
        }

    @staticmethod
    def _digest_detected_services(state: Dict[str, Any]) -> Dict[str, Any]:
        analysis = state.get("codebase_analysis") or {}
        services = analysis.get("services") or []
        return {"services": services[:32]}

    @staticmethod
    def _digest_architecture_decision(state: Dict[str, Any]) -> Dict[str, Any]:
        arch = state.get("architecture_decision") or {}
        plans = arch.get("plans") or []
        return {
            "plans": [
                {
                    "id":                 p.get("id"),
                    "title":              p.get("title"),
                    "monthly_cost":       p.get("monthly_cost"),
                    "scalability_tier":   p.get("scalability_tier"),
                    "availability_level": p.get("availability_level"),
                    "aws_services":       p.get("aws_services") or [],
                }
                for p in plans
            ],
            "recommended_plan": arch.get("recommended_plan"),
        }

    @staticmethod
    def _digest_selected_plan(state: Dict[str, Any]) -> Dict[str, Any]:
        plan_id = state.get("selected_plan_id")
        if not plan_id:
            return {}
        cost = state.get("cost_estimation") or {}
        return {
            "selected_plan_id": plan_id,
            "monthly_cost":     cost.get("monthly_cost"),
            "cost_profile":     cost.get("cost_profile"),
            "assumptions":      cost.get("assumptions") or [],
        }

    @staticmethod
    def _digest_docker_hints(state: Dict[str, Any]) -> Dict[str, Any]:
        infra = state.get("infra") or {}
        docker_meta = (infra.get("docker") or infra.get("docker_metadata") or {})
        if not docker_meta:
            return {}
        return {
            "base_image":      docker_meta.get("base_image"),
            "distro":          docker_meta.get("distro"),
            "build_strategy":  docker_meta.get("build_strategy"),
            "user":            docker_meta.get("user"),
            "exposed_ports":   docker_meta.get("exposed_ports") or [],
        }

    @staticmethod
    def _digest_terraform_hints(state: Dict[str, Any]) -> Dict[str, Any]:
        infra = state.get("infra") or {}
        tf_meta = infra.get("terraform_metadata") or infra.get("terraform") or {}
        if not tf_meta:
            return {}
        return {
            "provider":     tf_meta.get("provider"),
            "region":       tf_meta.get("region"),
            "modules":      tf_meta.get("modules") or [],
            "resource_count": tf_meta.get("resource_count"),
            "multi_az":     bool(tf_meta.get("multi_az")),
        }

    @staticmethod
    def _digest_infrastructure_summary(state: Dict[str, Any]) -> Dict[str, Any]:
        infra = state.get("infra") or {}
        artifacts = infra.get("artifacts") or {}
        if not artifacts:
            return {}
        return {
            "artifact_count":  len(artifacts),
            "artifact_files":  sorted(list(artifacts.keys()))[:40],
        }

    @staticmethod
    def _digest_validation_summary(state: Dict[str, Any]) -> Dict[str, Any]:
        validation = state.get("validation") or (state.get("result") or {}).get("validation") or {}
        if not validation:
            return {}
        return {
            "status":              validation.get("status"),
            "missing_artifacts":   validation.get("missing_artifacts") or [],
            "quality_issues":      (validation.get("quality_issues") or [])[:40],
            "warnings":            (validation.get("warnings") or [])[:40],
        }

    @staticmethod
    def _digest_cost_summary(state: Dict[str, Any]) -> Dict[str, Any]:
        cost = state.get("cost_estimation") or {}
        if not cost:
            return {}
        return {
            "monthly_cost":  cost.get("monthly_cost"),
            "cost_profile": cost.get("cost_profile"),
            "breakdown":     cost.get("breakdown") or {},
        }

    # ── High-level capture hooks ────────────────────────────────────────────

    @staticmethod
    def capture_from_state(
        db: Session,
        *,
        project_id: str,
        state: Dict[str, Any],
        phase: str,
        generated_by: Optional[str] = None,
    ) -> List[ProjectContext]:
        """Capture every digest derivable from ``state`` for the given phase.

        Idempotent — calling repeatedly for the same project replaces fields
        without losing previously-captured ones (shallow merge in ``upsert``).
        """
        writers: Dict[str, Dict[str, Any]] = {}
        phase_upper = (phase or "").upper()

        # Analysis-time captures
        if phase_upper in ("ANALYSIS", "ARCHITECTURE_DECISION", "PLANNING", "*"):
            writers[CONTEXT_REPOSITORY_SUMMARY]    = ProjectContextService._digest_repo_summary(state)
            writers[CONTEXT_DETECTED_STACK]        = ProjectContextService._digest_detected_stack(state)
            writers[CONTEXT_DETECTED_SERVICES]     = ProjectContextService._digest_detected_services(state)

        # Architecture decision captures
        if phase_upper in ("ARCHITECTURE_DECISION", "PLANNING", "*"):
            writers[CONTEXT_ARCHITECTURE_DECISION] = ProjectContextService._digest_architecture_decision(state)

        if phase_upper in ("PLAN_SELECTED", "PLANNING", "*"):
            writers[CONTEXT_SELECTED_PLAN]         = ProjectContextService._digest_selected_plan(state)
            writers[CONTEXT_COST_SUMMARY]          = ProjectContextService._digest_cost_summary(state)

        # Docker / Terraform / Validation
        if phase_upper in ("DOCKER", "TERRAFORM", "KUBERNETES", "CICD", "*"):
            writers[CONTEXT_DOCKER_HINTS]          = ProjectContextService._digest_docker_hints(state)
            writers[CONTEXT_TERRAFORM_HINTS]       = ProjectContextService._digest_terraform_hints(state)
            writers[CONTEXT_INFRASTRUCTURE_SUMMARY] = ProjectContextService._digest_infrastructure_summary(state)
            writers[CONTEXT_VALIDATION_SUMMARY]    = ProjectContextService._digest_validation_summary(state)

        persisted: List[ProjectContext] = []
        for ctx_type, content in writers.items():
            if not content:
                continue
            row = ProjectContextService.upsert(
                db,
                project_id=project_id,
                context_type=ctx_type,
                content=content,
                generated_by=generated_by,
                commit=False,
            )
            persisted.append(row)

        if persisted:
            db.commit()
            for r in persisted:
                db.refresh(r)
            logger.info(
                "[ProjectContext] captured %d digests for project=%s phase=%s",
                len(persisted), project_id, phase_upper,
            )
        return persisted
