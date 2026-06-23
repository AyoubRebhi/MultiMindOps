"""GitHub Actions Generation phase — aggregated read-only response schema.

Powers the single request the GitHub Actions phase surface makes:

    GET /api/projects/{project_id}/workflows/{workflow_id}/github-actions
        -> GitHubActionsPhaseResponse

Every field is assembled READ-ONLY from data the GITHUB_ACTIONS_GENERATION phase
already persisted (``Workflow.phases_state`` + the backing task's
``workflow_state`` + the DB-backed ``github_actions`` Artifact row). Nothing here
re-runs generation or calls an LLM. All sub-objects are optional/defaulted so a
workflow that has NOT reached the phase renders ``generated=False`` without
throwing — mirroring the Docker/Analysis projections.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class DeploymentContextView(BaseModel):
    """What the deploy workflow targets and which artifacts it consumes."""

    cloud_provider: str = "aws"
    deployment_target: Optional[str] = None   # ecs | eks | lambda | ec2
    aws_region: Optional[str] = None
    project_name: Optional[str] = None
    repository_name: Optional[str] = None
    cluster_name: Optional[str] = None
    service_name: Optional[str] = None
    function_name: Optional[str] = None
    container_port: Optional[int] = None
    terraform_directory: Optional[str] = None
    docker_artifacts: List[str] = []
    terraform_artifacts: List[str] = []


class WorkflowYamlValidation(BaseModel):
    status: str = "not_run"        # passed | warnings | failed | not_run
    valid: bool = True
    errors: List[str] = []
    warnings: List[str] = []


class GitHubActionsArtifact(BaseModel):
    """The generated deploy.yml — read-only, with version/approval provenance.

    Retained for backward compatibility; new clients should read ``pipelines``.
    """

    path: str = ".github/workflows/deploy.yml"
    content: str = ""
    version: Optional[int] = None
    approval_state: Optional[str] = None
    validation_status: Optional[str] = None


class PipelineFileView(BaseModel):
    """One generated workflow file in the bootstrap/deploy split.

    ``kind`` is ``bootstrap`` (Infrastructure Pipeline — provisioning + first
    deploy, manual trigger) or ``deploy`` (Delivery Pipeline — continuous delivery
    on every push, no Terraform).
    """

    name: str = ""                            # human label
    kind: str = ""                            # bootstrap | deploy
    path: str = ""                            # .github/workflows/<file>.yml
    content: str = ""
    template: Optional[str] = None
    version: Optional[int] = None
    approval_state: Optional[str] = None
    validation_status: Optional[str] = None
    validation: WorkflowYamlValidation = WorkflowYamlValidation()
    enrichment_applied: bool = False


class GitHubActionsPhaseResponse(BaseModel):
    """ONE response → the whole GitHub Actions Generation phase surface."""

    workflow_id: str
    project_id: str
    task_id: Optional[str] = None
    current_phase: Optional[str] = None
    status: Optional[str] = None              # Workflow.status
    phase_status: Optional[str] = None        # phases_state[...].status (None = not run)
    generated: bool = False                   # a deploy.yml exists

    deployment_target: Optional[str] = None   # convenience mirror of context
    template: Optional[str] = None            # template filename used
    enrichment_applied: bool = False

    deployment_context: DeploymentContextView = DeploymentContextView()
    validation: WorkflowYamlValidation = WorkflowYamlValidation()
    # The bootstrap + deploy split. Empty until the phase has generated files.
    pipelines: List[PipelineFileView] = []
    # Back-compat: the delivery (deploy.yml) file. New clients should read
    # ``pipelines``; this mirrors the deploy pipeline so existing readers keep
    # working during the migration.
    workflow_file: Optional[GitHubActionsArtifact] = None
    infrastructure_summary: Dict[str, Any] = {}
