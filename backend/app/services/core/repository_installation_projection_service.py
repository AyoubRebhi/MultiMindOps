"""RepositoryInstallationProjectionService — read-only projection of the phase.

Assembles the ONE payload the Repository Installation surface consumes
(``GET /api/projects/{pid}/workflows/{wid}/repository-installation``) by
RESHAPING data the REPOSITORY_INSTALLATION phase already persisted. The
installation analogue of ``GitHubActionsPhaseProjectionService``:

* reads ``Workflow.phases_state`` for the authoritative phase status + the
  recorded branch / commit / PR url,
* reads the backing task's ``workflow_state['repository_installation']`` for the
  per-run detail + the human log lines,
* checks the DB-backed ``github_actions`` artifacts so the surface knows whether
  the install can even be offered (both pipelines must exist).

It NEVER clones, commits, or pushes. A workflow that has not reached the phase
projects to ``installed=False`` (200, not 404).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.schemas.repository_installation_phase import (
    RepositoryInstallationPhaseResponse,
)
from backend.app.services.core.artifact_persistence_service import (
    ArtifactPersistenceService,
)
from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.core.task_service import TaskService
from backend.app.services.repository_installation.models import (
    BOOTSTRAP_PATH,
    DEPLOY_PATH,
)

_PHASE_KEY = "REPOSITORY_INSTALLATION"


class RepositoryInstallationProjectionService:
    """Pure read projection — no git, no orchestration, no LLM."""

    @staticmethod
    def build(
        db: Session,
        *,
        project_id: str,
        workflow: Workflow,
        task: Optional[Task],
        project: Optional[Project] = None,
    ) -> RepositoryInstallationPhaseResponse:
        state: Dict[str, Any] = (
            TaskService.load_workflow_state(db, task) if task else {}
        ) or {}
        ri: Dict[str, Any] = state.get("repository_installation") or {}

        phases_state = workflow.phases_state or {}
        phase_entry = phases_state.get(_PHASE_KEY) or {}
        phase_status = phase_entry.get("status")

        # Prerequisites: both generated pipelines must exist in the DB.
        gh_files = ArtifactPersistenceService.get_github_actions_files(
            db, project_id=project_id
        )
        prerequisites_met = bool(
            gh_files.get(BOOTSTRAP_PATH) and gh_files.get(DEPLOY_PATH)
        )

        installed = phase_status == "completed" or bool(ri.get("success"))

        # ── Installation requirements (UX pre-flight) ────────────────────────
        # The same two inputs the install service hard-requires (a repository URL
        # + a GitHub token). The token check is an EXISTENCE probe only — it
        # never decrypts the secret. Surfacing these lets the UI disable Install
        # and explain WHY before the user clicks, so the prerequisite 400 becomes
        # exceptional. If the project row wasn't passed, look it up.
        if project is None:
            project = db.query(Project).filter(Project.id == project_id).first()
        has_repo_url = bool(getattr(project, "repository_url", None))
        has_github_token = CredentialsService.has_credential(
            db, project_id=project_id, provider="github_pat",
        )
        missing_requirements: List[str] = []
        if not has_repo_url:
            missing_requirements.append("repository_url")
        if not has_github_token:
            missing_requirements.append("github_token")

        # Prefer the per-run scratch detail; fall back to the phase entry (which
        # is authoritative for status and always present once the phase has run).
        def pick(key: str, default: Any = None) -> Any:
            if key in ri and ri.get(key) is not None:
                return ri.get(key)
            return phase_entry.get(key, default)

        logs: List[str] = [
            entry.get("message", "")
            for entry in (state.get("logs") or [])
            if isinstance(entry, dict) and entry.get("step") == "repository_installation"
        ]

        return RepositoryInstallationPhaseResponse(
            workflow_id=workflow.id,
            project_id=project_id,
            task_id=getattr(task, "id", None),
            current_phase=workflow.current_phase,
            status=workflow.status,
            phase_status=phase_status,
            installed=installed,
            prerequisites_met=prerequisites_met,
            has_repo_url=has_repo_url,
            has_github_token=has_github_token,
            missing_requirements=missing_requirements,
            repo_url=pick("repo_url"),
            branch=pick("branch"),
            base_branch=pick("base_branch"),
            commit_sha=pick("commit"),
            pushed=bool(pick("pushed", False)),
            committed=bool(pick("committed", False)),
            no_changes=bool(pick("no_changes", False)),
            pr_url=pick("pr_url"),
            pr_created=bool(pick("pr_created", False)),
            pr_skipped_reason=pick("pr_skipped_reason"),
            files=list(pick("files", []) or []),
            error=pick("error"),
            logs=logs,
        )
