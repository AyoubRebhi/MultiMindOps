"""Docker Generation phase — aggregated read-only response schema.

Powers the single request the Docker phase surface makes:

    GET /api/projects/{project_id}/workflows/{workflow_id}/docker
        -> DockerPhaseResponse

The Docker phase is ONE phase with FOUR steps the UI renders side by side
(generation · validation · correction · approved artifact), NOT four phases.
The frontend makes exactly one call and distributes the result to its panels.

Every field is assembled READ-ONLY from data the DOCKER phase already persisted
in ``Workflow.phases_state`` / the backing task's ``workflow_state`` / the
DB-backed ``Artifact`` rows. Nothing here re-runs the InfrastructureAgent, the
corrector, or calls an LLM. All sub-objects are optional/defaulted so a workflow
that has NOT reached Docker yet (or generated via deterministic fallback)
renders without throwing — mirroring the Analysis/Architecture projections.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ─── Reusable value objects ───────────────────────────────────────────────────

class ValidationIssue(BaseModel):
    """One generation/validation finding (error, warning or recommendation)."""

    rule: Optional[str] = None
    message: str = ""
    severity: Optional[str] = None
    section_id: Optional[str] = None


# ─── Step DTOs ─────────────────────────────────────────────────────────────────

class DockerfileArtifact(BaseModel):
    """The generated Dockerfile — read-only, with edit/approval provenance."""

    filename: str = "Dockerfile"
    content: str = ""             # latest content (a user edit wins over generated)
    original_content: str = ""    # exactly as the agent generated it
    edited: bool = False          # content != original_content
    version: Optional[int] = None
    approval_state: Optional[str] = None      # approved | pending_review | rejected
    validation_status: Optional[str] = None   # artifact-level status (DB)


class DockerGenerationMetadata(BaseModel):
    """Provenance + detected build shape (faithfully read from generation state)."""

    detected_runtime: Optional[str] = None    # framework or language label
    language: Optional[str] = None
    framework: Optional[str] = None
    base_image: Optional[str] = None          # last FROM in the Dockerfile
    port: Optional[str] = None                # EXPOSE / detected service port
    build_strategy: Optional[str] = None      # multi_stage | single_stage (blueprint)
    container_type: Optional[str] = None      # project/service type (e.g. python_fastapi)
    blueprint_id: Optional[str] = None
    # Phase-completion contract metadata (also surfaced as a UX badge).
    used_llm: bool = True
    fallback_used: bool = False
    generation_mode: str = "llm"              # llm | llm_with_fallback | deterministic | degraded


class DockerValidation(BaseModel):
    """Generation/static validation findings, split for clear display."""

    status: str = "not_run"        # passed | warnings | failed | not_run
    valid: bool = True
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []
    recommendations: List[ValidationIssue] = []


class DockerCorrector(BaseModel):
    """The Docker corrector's latest analysis for this task (if any)."""

    available: bool = False
    status: Optional[str] = None              # completed | running | error
    retry_count: int = 0
    max_retries: int = 3
    analysis: Optional[Dict[str, Any]] = None  # CorrectorResult.to_dict()
    # The corrected Dockerfile shown side-by-side with the original. Present only
    # when a correction has actually changed the file (current != original);
    # otherwise the UI surfaces the corrector's proposed fixes/patches instead.
    corrected_dockerfile: Optional[str] = None


# ─── Top-level response ────────────────────────────────────────────────────────

class DockerPhaseResponse(BaseModel):
    """ONE response → the whole Docker Generation phase surface."""

    workflow_id: str
    project_id: str
    task_id: Optional[str] = None
    current_phase: Optional[str] = None
    status: Optional[str] = None              # Workflow.status
    docker_phase_status: Optional[str] = None  # phases_state["DOCKER"].status (None = not run)
    generated: bool = False                   # a Dockerfile exists

    dockerfile: Optional[DockerfileArtifact] = None
    metadata: DockerGenerationMetadata = DockerGenerationMetadata()
    validation: DockerValidation = DockerValidation()
    corrector: DockerCorrector = DockerCorrector()
    # Presence flags for the companion artifacts (kept lightweight on purpose).
    has_dockerignore: bool = False
    has_compose: bool = False
