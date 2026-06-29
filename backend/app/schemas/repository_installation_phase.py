"""Repository Installation phase — aggregated read-only response schema.

Powers the single request the installation surface makes:

    GET /api/projects/{project_id}/workflows/{workflow_id}/repository-installation
        -> RepositoryInstallationPhaseResponse

Every field is assembled READ-ONLY from data the REPOSITORY_INSTALLATION phase
already persisted (``Workflow.phases_state`` + the backing task's
``workflow_state['repository_installation']`` + the DB-backed
``installation.json`` artifact). Nothing here clones, commits, or pushes. All
fields are optional/defaulted so a workflow that has NOT reached the phase
renders ``installed=False`` without throwing — mirroring the Docker / GitHub
Actions projections.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class RepositoryInstallationPhaseResponse(BaseModel):
    """ONE response → the whole Repository Installation phase surface."""

    workflow_id: str
    project_id: str
    task_id: Optional[str] = None
    current_phase: Optional[str] = None
    status: Optional[str] = None              # Workflow.status
    phase_status: Optional[str] = None        # phases_state[...].status (None = not run)

    # True once the workflows are committed + pushed onto the installation branch.
    installed: bool = False
    # True when the prerequisite artifacts (bootstrap.yml + deploy.yml) exist, so
    # the surface can offer "Install" instead of "generate the pipelines first".
    prerequisites_met: bool = False

    # ── Installation requirements (UX-only pre-flight) ───────────────────────
    # Surfaced so the UI can show the requirements checklist + DISABLE the
    # Install action BEFORE the user clicks, turning the backend prerequisite
    # 400 ("a GitHub token is required") into an exceptional case rather than the
    # first feedback the user sees. ``has_github_token`` is an EXISTENCE probe
    # (``CredentialsService.has_credential``) — it never decrypts or returns the
    # secret. ``missing_requirements`` lists the keys still needed to install,
    # e.g. ``["github_token"]``.
    has_repo_url: bool = False
    has_github_token: bool = False
    missing_requirements: List[str] = []

    repo_url: Optional[str] = None
    branch: Optional[str] = None              # installation branch
    base_branch: Optional[str] = None
    commit_sha: Optional[str] = None

    pushed: bool = False
    committed: bool = False
    no_changes: bool = False

    pr_url: Optional[str] = None
    pr_created: bool = False
    pr_skipped_reason: Optional[str] = None

    files: List[str] = []
    error: Optional[str] = None
    logs: List[str] = []
