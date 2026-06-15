"""ProjectAnalysisService.

Read-only assembler that consolidates everything the frontend needs to render
a project's *analysis* and *security* results into a single payload, sourced
exclusively from data the bootstrap pipeline already persisted:

* Codebase-analysis digests live in ``ProjectContext`` rows
  (``detected_stack`` / ``repository_summary`` / ``detected_services``),
  written by :class:`ProjectContextService` during the architecture-decision
  phase.
* Security results live in the backing task's ``workflow_state["security"]``
  (already transformed by :class:`SecurityScoreTransformer`). When that is not
  available (e.g. an older run, or the state was trimmed) we fall back to the
  raw ``RepositoryAnalysis`` record and run the transformer on demand.

Nothing here mutates state, re-runs an agent, or calls an LLM. It is the read
side of the project-analysis feature — the write side already happened during
bootstrap. Every lookup degrades to an empty/None shape rather than raising so
a half-finished bootstrap still renders a sensible "analyzing…" view.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.repository_analysis import RepositoryAnalysis
from backend.app.services.core.project_context_service import (
    CONTEXT_DETECTED_SERVICES,
    CONTEXT_DETECTED_STACK,
    CONTEXT_REPOSITORY_SUMMARY,
    ProjectContextService,
)
from backend.app.services.core.project_service import ProjectService
from backend.app.services.core.task_service import TaskService
from backend.app.services.core.workflow_orchestration_service import (
    WorkflowOrchestrationService,
)
from backend.app.services.repository.repository_fingerprint_service import (
    RepositoryFingerprintService,
)
from backend.app.services.security.security_score_transformer import (
    SecurityScoreTransformer,
)

logger = logging.getLogger(__name__)

# bootstrap_status values for which analysis output is expected to be present.
_READY_STATES = {"ready", "context_building"}


class ProjectAnalysisService:
    """Assemble the consolidated analysis + security payload for a project."""

    @staticmethod
    def build_payload(db: Session, project: Project) -> Dict[str, Any]:
        analysis = ProjectAnalysisService._build_analysis(db, project)
        security = ProjectAnalysisService._build_security(db, project)

        # "available" means the analyzer produced at least a primary language
        # OR the bootstrap reached a ready-ish state. Lets the UI distinguish
        # "still analyzing" from "analyzed but genuinely empty repo".
        analysis_available = bool(
            analysis.get("language")
            or analysis.get("languages")
            or analysis.get("services")
        )

        return {
            "project_id": project.id,
            "bootstrap_status": project.bootstrap_status or "pending",
            "bootstrap_error": project.bootstrap_error,
            "analysis_available": analysis_available,
            **analysis,
            "security": security,
        }

    # ─── Analysis (codebase) ─────────────────────────────────────────────────

    @staticmethod
    def _build_analysis(db: Session, project: Project) -> Dict[str, Any]:
        stack = ProjectAnalysisService._context_content(
            db, project.id, CONTEXT_DETECTED_STACK,
        )
        summary = ProjectAnalysisService._context_content(
            db, project.id, CONTEXT_REPOSITORY_SUMMARY,
        )
        services_ctx = ProjectAnalysisService._context_content(
            db, project.id, CONTEXT_DETECTED_SERVICES,
        )

        languages = stack.get("languages") or summary.get("languages") or []
        frameworks = stack.get("frameworks") or summary.get("frameworks") or []

        # The codebase analyzer records framework names; the first one is the
        # headline "framework" the UI shows in the summary card.
        framework = frameworks[0] if frameworks else None

        return {
            "language": stack.get("language") or summary.get("language"),
            "languages": languages,
            "framework": framework,
            "frameworks": frameworks,
            "runtime": stack.get("runtime"),
            "dependencies": stack.get("dependencies") or summary.get("build_systems") or [],
            "services": services_ctx.get("services") or [],
            "stats": {
                "project_type": summary.get("project_type"),
                "service_count": summary.get("service_count"),
                "lines_of_code": summary.get("lines_of_code"),
                "has_dockerfile": summary.get("has_dockerfile"),
                "has_compose": summary.get("has_compose"),
                "has_ci": summary.get("has_ci"),
                "build_systems": summary.get("build_systems") or [],
                "devops_tools": summary.get("devops_tools") or [],
                "application_profile": ProjectAnalysisService._normalize_application_profile(
                    summary.get("application_profile"),
                ),
            },
        }

    @staticmethod
    def _normalize_application_profile(raw: Any) -> Optional[Dict[str, Any]]:
        """Map the raw ``application_profile`` into the structured contract.

        ``ApplicationProfilerService`` persists a dict (application_type,
        architecture_pattern, workload_profile, statefulness, scalability_level,
        entrypoints, detected_services). Returns a normalized dict matching
        :class:`ApplicationProfileResponse`, or ``None`` when no profile exists.
        We never flatten to a string and never serialize to JSON — the typed
        structure is preserved.
        """
        if not isinstance(raw, dict) or not raw:
            return None

        def _str(key: str) -> Optional[str]:
            val = raw.get(key)
            return val if isinstance(val, str) and val.strip() else None

        def _list(key: str) -> List[str]:
            val = raw.get(key)
            if not isinstance(val, list):
                return []
            return [str(item) for item in val if item is not None]

        return {
            "application_type": _str("application_type"),
            "architecture_pattern": _str("architecture_pattern"),
            "workload_profile": _str("workload_profile"),
            "statefulness": _str("statefulness"),
            "scalability_level": _str("scalability_level"),
            "entrypoints": _list("entrypoints"),
            "detected_services": _list("detected_services"),
        }

    @staticmethod
    def _context_content(db: Session, project_id: str, context_type: str) -> Dict[str, Any]:
        row = ProjectContextService.get(db, project_id, context_type)
        return dict(row.content or {}) if row is not None else {}

    # ─── Security ────────────────────────────────────────────────────────────

    @staticmethod
    def _build_security(db: Session, project: Project) -> Optional[Dict[str, Any]]:
        raw = ProjectAnalysisService._security_from_workflow_state(db, project)
        if raw is None:
            raw = ProjectAnalysisService._security_from_repository_analysis(db, project)
        if not raw:
            return None
        return ProjectAnalysisService._normalize_security(raw)

    @staticmethod
    def _security_from_workflow_state(db: Session, project: Project) -> Optional[Dict[str, Any]]:
        """Primary source — the transformed ``security`` block on the task state.

        Reads the project's most recent workflow's backing task. The orchestrator
        writes ``state["security"]`` (already in SecurityAnalysis shape) at the
        end of the architecture-decision phase; that survives the secret scrub.
        """
        workflows = ProjectService.list_workflows(db, project.id)
        if not workflows:
            return None
        workflow = workflows[0]  # list_workflows() is ordered created_at desc
        task = WorkflowOrchestrationService.get_backing_task(db, workflow)
        if task is None:
            return None
        state = TaskService.load_workflow_state(db, task) or {}
        security = state.get("security")
        if isinstance(security, dict) and ("score" in security or "vulnerabilities" in security):
            return security
        return None

    @staticmethod
    def _security_from_repository_analysis(
        db: Session, project: Project,
    ) -> Optional[Dict[str, Any]]:
        """Fallback — re-derive the SecurityAnalysis from the stored raw scan.

        ``RepositoryAnalysis.analysis_output["security"]`` holds the raw
        RepositorySecurityService result; running it back through
        SecurityScoreTransformer reproduces the same shape the workflow state
        would have carried.
        """
        if not project.repository_url:
            return None
        try:
            normalized = RepositoryFingerprintService().normalize_repo_url(
                project.repository_url,
            )
        except Exception:  # noqa: BLE001 — defensive; never break the read path
            return None

        record = (
            db.query(RepositoryAnalysis)
            .filter(RepositoryAnalysis.normalized_url == normalized)
            .order_by(RepositoryAnalysis.updated_at.desc())
            .first()
        )
        if record is None:
            return None
        output = dict(record.analysis_output or {})
        repository_security = output.get("security")
        if not repository_security:
            return None
        return SecurityScoreTransformer.transform(
            repository_security=repository_security,
            env_security_runtime=output.get("env_security_runtime"),
        )

    @staticmethod
    def _normalize_security(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Map a SecurityAnalysis dict into the frontend security contract.

        Accepts both the transformer output (``vulnerabilities`` + top-level
        ``critical``/``high``/...) and is tolerant of missing keys.
        """
        vulns = raw.get("vulnerabilities") or []
        findings: List[Dict[str, Any]] = [
            {
                "severity": (v.get("severity") or "low"),
                "title": v.get("title") or v.get("description") or "Security finding",
                "description": v.get("description") or v.get("title") or "",
                "recommendation": v.get("recommendation"),
                "category": v.get("category"),
                "file": v.get("file"),
            }
            for v in vulns
        ]

        def _count(level: str) -> int:
            if isinstance(raw.get(level), int):
                return raw[level]
            return len([f for f in findings if f["severity"] == level])

        return {
            "score": raw.get("score"),
            "grade": raw.get("grade"),
            "status": raw.get("status"),
            "summary": raw.get("summary"),
            "counts": {
                "critical": _count("critical"),
                "high": _count("high"),
                "medium": _count("medium"),
                "low": _count("low"),
            },
            "findings": findings,
            "recommendations": raw.get("recommendations") or [],
        }
