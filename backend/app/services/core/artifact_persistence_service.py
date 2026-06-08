"""ArtifactPersistenceService.

Single integration point between the orchestrator's in-memory state and the
project-centric DB model. Agents do not need to know about the DB — the
workflow router calls ``persist_state_artifacts`` after each phase, and this
service classifies + upserts + appends history.

Contract guarantees
-------------------
1. Regeneration NEVER overwrites a previous ``ArtifactVersion`` row.
2. The ``Artifact`` row always points at the latest content and the latest
   integer version. Reads are O(1).
3. Upsert key is ``(project_id, artifact_type, artifact_subtype)`` — there is
   one canonical "Dockerfile" per project, with N versions behind it.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact, ArtifactVersion

logger = logging.getLogger(__name__)


def compute_content_hash(content: str) -> str:
    """SHA-256 of an artifact's content, deterministic across runs.

    UTF-8 encoded; newlines are NOT normalised — a CRLF↔LF flip is a real
    content change and the gate should treat it as such (it produces a
    different file on disk and a different docker build).
    """
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


# ─── Classification ──────────────────────────────────────────────────────────

# Order matters: more specific rules first. The first matching rule wins.
#
# Build inputs are keyed in orchestrator state by CANONICAL KEY (e.g.
# ``dockerignore``, ``docker_compose``, ``env_example``) — NOT by on-disk
# filename. Earlier rules only matched the filename forms (``.dockerignore``,
# ``docker-compose``), so compose/env/.dockerignore silently failed to persist
# and lived ONLY in the editable scratch store / build temp dir. The canonical-key
# rules below close that gap: every Docker build input is now a DB-backed Artifact.
_CLASSIFICATION_RULES: List[Tuple[str, str]] = [
    # (substring or extension to match in lowercase filename, artifact_type)
    ("dockerfile",        "docker"),
    (".dockerignore",     "docker"),
    ("dockerignore",      "docker"),   # canonical state key (no leading dot)
    ("docker-compose",    "docker"),
    ("docker_compose",    "docker"),   # canonical state key (underscore)
    ("compose.yaml",      "docker"),
    ("compose.yml",       "docker"),
    ("env_example",       "docker"),   # canonical state key for .env.example
    (".env",              "docker"),   # .env / .env.example / .env.* filenames
    # Canonical TerraformAgent state keys (terraform_main, terraform_providers,
    # terraform_outputs, terraform_variables, terraform_tfvars, terraform_backend,
    # terraform_vpc/eks/ecs). These are NOT on-disk filenames, so the .tf/.tfvars
    # rules below never matched them and ALL terraform artifacts were dropped from
    # the DB. The prefix rule maps every terraform_* key → terraform.
    ("terraform_",        "terraform"),
    (".tf",               "terraform"),
    (".tfvars",           "terraform"),
    (".tfstate",          "terraform"),
    ("kustomization",     "kubernetes"),
    ("deployment.yaml",   "kubernetes"),
    ("service.yaml",      "kubernetes"),
    ("ingress.yaml",      "kubernetes"),
    ("configmap.yaml",    "kubernetes"),
    ("secret.yaml",       "kubernetes"),
    ("hpa.yaml",          "kubernetes"),
    (".github/workflows", "cicd"),
    (".gitlab-ci",        "cicd"),
    ("jenkinsfile",       "cicd"),
    ("bitbucket-pipelines", "cicd"),
    (".circleci",         "cicd"),
]


def classify_artifact(filename: str) -> Optional[str]:
    """Return the ``artifact_type`` for a filename, or ``None`` to skip.

    Unrecognized files are returned as ``None`` rather than a catch-all type
    so we don't accidentally persist transient state blobs (logs, prompts,
    repo summaries) as artifacts.
    """
    lower = filename.lower()
    for needle, kind in _CLASSIFICATION_RULES:
        if needle in lower:
            return kind
    # Fallback: any .yaml/.yml file generated alongside k8s artifacts is also k8s
    if lower.endswith((".yaml", ".yml")):
        return "kubernetes"
    return None


# Canonical TerraformAgent artifact key → on-disk filename. The DB preserves the
# canonical key as ``artifact_subtype`` (granularity), but terraform must run
# against real ``.tf`` files, so the rehydration adapter (``get_terraform_files``)
# translates the key back to its filename. Mirrors terraform_generation's map.
_TF_KEY_TO_FILENAME: Dict[str, str] = {
    "terraform_providers": "providers.tf",
    "terraform_main":      "main.tf",
    "terraform_vpc":       "vpc.tf",
    "terraform_eks":       "eks.tf",
    "terraform_ecs":       "ecs.tf",
    "terraform_variables": "variables.tf",
    "terraform_tfvars":    "terraform.tfvars",
    "terraform_outputs":   "outputs.tf",
    "terraform_backend":   "backend.tf",
}


def _terraform_subtype_to_filename(subtype: str) -> Optional[str]:
    """Map a stored terraform ``artifact_subtype`` to an on-disk filename.

    Accepts both the canonical key (``terraform_main``) and an already-resolved
    filename (``main.tf``). Returns ``None`` for values that are neither.
    """
    if not subtype:
        return None
    if subtype in _TF_KEY_TO_FILENAME:
        return _TF_KEY_TO_FILENAME[subtype]
    low = subtype.lower()
    if low.endswith((".tf", ".tfvars", ".tfstate")):
        return subtype  # already a filename
    if low.startswith("terraform_"):
        # Unknown terraform_* key — best-effort: strip prefix + .tf extension.
        return subtype[len("terraform_"):] + ".tf"
    return None


# ─── Extraction from orchestrator state ──────────────────────────────────────

def extract_artifacts_from_state(state: dict) -> Dict[str, str]:
    """Pull the artifact map out of orchestrator state.

    Reuses the same priority rules as the existing workflow router:
    user-edited content (from ``state["artifacts"]``) wins over the original
    generated content (``state["infra"]["artifacts"]``).
    """
    result: Dict[str, str] = {}

    infra = state.get("infra") or {}
    result.update(dict(infra.get("artifacts") or {}))

    # User-edited artifact store (ArtifactService.initialize_from_state).
    edited = state.get("artifacts") or {}
    for filename, entry in edited.items():
        if isinstance(entry, dict):
            current = entry.get("current_content")
            if isinstance(current, str):
                result[filename] = current
    return result


# ─── Persistence ─────────────────────────────────────────────────────────────

class ArtifactPersistenceService:
    @staticmethod
    def persist_state_artifacts(
        db: Session,
        *,
        project_id: str,
        workflow_id: Optional[str],
        state: dict,
        generated_by_agent: Optional[str] = None,
        validation_status: str = "pending",
        commit: bool = True,
    ) -> List[Artifact]:
        """Persist every classifiable artifact in state.

        Returns the list of ``Artifact`` rows that were created or updated.
        Unclassifiable files are silently skipped — they're not artifacts.

        ``commit=False`` lets a caller fold this persistence into a larger
        single-transaction phase (the upserts are flushed but not committed),
        so artifact rows and the ``Workflow.phases_state`` update land
        atomically — either both or neither.
        """
        artifacts_map = extract_artifacts_from_state(state)
        if not artifacts_map:
            return []

        persisted: List[Artifact] = []
        for filename, content in artifacts_map.items():
            if not isinstance(content, str):
                continue
            artifact_type = classify_artifact(filename)
            if artifact_type is None:
                continue
            row = ArtifactPersistenceService.upsert_artifact(
                db,
                project_id=project_id,
                workflow_id=workflow_id,
                artifact_type=artifact_type,
                artifact_subtype=filename,
                content=content,
                generated_by_agent=generated_by_agent,
                validation_status=validation_status,
            )
            persisted.append(row)

        if commit:
            db.commit()
        logger.info(
            "[ArtifactPersistence] persisted %d artifacts for project=%s workflow=%s (commit=%s)",
            len(persisted), project_id, workflow_id, commit,
        )
        return persisted

    @staticmethod
    def get_terraform_files(
        db: Session,
        *,
        project_id: str,
        workflow_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Return ``{filename: content}`` for the project's Terraform artifacts.

        The DB is the source of truth for generated HCL. Each ``terraform``
        ``Artifact`` row carries the canonical TerraformAgent key in
        ``artifact_subtype`` (e.g. ``terraform_main``) — this method translates
        it back to the on-disk filename (``main.tf``) so the rehydrated working
        directory contains real ``.tf`` files terraform can init/validate/plan.
        Rows already stored under a filename subtype (legacy) pass through.

        ``workflow_id`` is accepted for symmetry but NOT used to filter: the
        upsert key is ``(project_id, artifact_type, artifact_subtype)``, so
        there is exactly one canonical terraform file-set per project.
        """
        rows = (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.artifact_type == "terraform",
            )
            .all()
        )
        files: Dict[str, str] = {}
        for row in rows:
            if not isinstance(row.content, str) or not row.artifact_subtype:
                continue
            filename = _terraform_subtype_to_filename(row.artifact_subtype)
            if filename:
                files[filename] = row.content
        return files

    @staticmethod
    def get_docker_artifacts(
        db: Session,
        *,
        project_id: str,
        workflow_id: Optional[str] = None,
    ) -> Dict[str, str]:
        """Return ``{canonical_key: content}`` for the project's Docker artifacts.

        Symmetric to :meth:`get_terraform_files`. The DB is the source of truth
        for build inputs: each ``docker`` ``Artifact`` row carries the canonical
        key (``dockerfile`` / ``dockerignore`` / ``docker_compose`` /
        ``env_example``) in ``artifact_subtype``. Subtypes persisted as on-disk
        filenames (``.dockerignore``, ``docker-compose.yml``, ``.env.example``)
        are normalised back to the canonical key the DockerExecutor expects.

        Used by replay so a build re-runs from DB artifacts ONLY — never from a
        regenerated Dockerfile or transient on-disk state.
        """
        # filename → canonical key (mirrors ArtifactService FILENAME map).
        _FILENAME_TO_KEY = {
            "dockerfile": "dockerfile",
            ".dockerignore": "dockerignore",
            "docker-compose.yml": "docker_compose",
            "docker-compose.yaml": "docker_compose",
            "compose.yml": "docker_compose",
            "compose.yaml": "docker_compose",
            ".env.example": "env_example",
            ".env": "env_example",
        }
        _CANONICAL = {"dockerfile", "dockerignore", "docker_compose", "env_example"}

        rows = (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.artifact_type == "docker",
            )
            .all()
        )
        files: Dict[str, str] = {}
        for row in rows:
            if not isinstance(row.content, str) or not row.artifact_subtype:
                continue
            sub = row.artifact_subtype
            key = sub if sub in _CANONICAL else _FILENAME_TO_KEY.get(sub.lower())
            if key:
                files[key] = row.content
        return files

    @staticmethod
    def upsert_artifact(
        db: Session,
        *,
        project_id: str,
        workflow_id: Optional[str],
        artifact_type: str,
        artifact_subtype: str,
        content: str,
        generated_by_agent: Optional[str] = None,
        validation_status: str = "pending",
    ) -> Artifact:
        """Upsert one artifact and append a new ``ArtifactVersion`` if changed.

        Behaviour:
          * No existing row → create with version=1, write v1 history.
          * Existing row with identical content → no-op, return row unchanged.
          * Existing row with new content → bump version, append history.
        """
        existing = (
            db.query(Artifact)
            .filter(
                Artifact.project_id == project_id,
                Artifact.artifact_type == artifact_type,
                Artifact.artifact_subtype == artifact_subtype,
            )
            .first()
        )

        new_hash = compute_content_hash(content)

        if existing is None:
            artifact = Artifact(
                project_id=project_id,
                workflow_id=workflow_id,
                artifact_type=artifact_type,
                artifact_subtype=artifact_subtype,
                content=content,
                content_hash=new_hash,
                version=1,
                validation_status=validation_status,
                generated_by_agent=generated_by_agent,
            )
            db.add(artifact)
            db.flush()  # populate artifact.id for the version row

            db.add(
                ArtifactVersion(
                    artifact_id=artifact.id,
                    version=1,
                    content=content,
                    content_hash=new_hash,
                    workflow_id=workflow_id,
                    generated_by=generated_by_agent,
                )
            )
            return artifact

        # Existing — only append a version if content actually changed.
        # Compare on HASH (not content) so a flag-day re-hash doesn't
        # silently treat a real change as a no-op.
        if existing.content_hash == new_hash:
            # Still refresh denormalized fields in case they moved. Approval
            # state is preserved — same content means the approval still applies.
            existing.validation_status = validation_status
            existing.generated_by_agent = generated_by_agent or existing.generated_by_agent
            existing.workflow_id = workflow_id or existing.workflow_id
            return existing

        # ── Phase 2 — content change invalidates approval ─────────────────
        # The reviewer approved the OLD content. The new bytes have not been
        # reviewed; the enforcement gate must reject any execution attempt
        # until a CLOUD_ARCHITECT re-approves.
        if existing.approval_state == "approved" or existing.approved_content_hash:
            logger.warning(
                "[ArtifactGovernance] content changed on artifact=%s "
                "(was hash=%s now hash=%s) — invalidating approval",
                existing.id, existing.approved_content_hash, new_hash,
            )
            existing.approval_state = "pending_review"
            existing.approved_by = None
            existing.approved_at = None
            existing.approved_content_hash = None

        next_version = (existing.version or 1) + 1
        existing.version = next_version
        existing.content = content
        existing.content_hash = new_hash
        existing.validation_status = validation_status
        existing.generated_by_agent = generated_by_agent or existing.generated_by_agent
        existing.workflow_id = workflow_id or existing.workflow_id

        db.add(
            ArtifactVersion(
                artifact_id=existing.id,
                version=next_version,
                content=content,
                content_hash=new_hash,
                workflow_id=workflow_id,
                generated_by=generated_by_agent,
            )
        )
        return existing

    @staticmethod
    def get_artifact(db: Session, artifact_id: str) -> Optional[Artifact]:
        return db.query(Artifact).filter(Artifact.id == artifact_id).first()

    @staticmethod
    def list_versions(db: Session, artifact_id: str) -> List[ArtifactVersion]:
        return (
            db.query(ArtifactVersion)
            .filter(ArtifactVersion.artifact_id == artifact_id)
            .order_by(ArtifactVersion.version.desc())
            .all()
        )

    @staticmethod
    def get_version(db: Session, artifact_id: str, version: int) -> Optional[ArtifactVersion]:
        return (
            db.query(ArtifactVersion)
            .filter(
                ArtifactVersion.artifact_id == artifact_id,
                ArtifactVersion.version == version,
            )
            .first()
        )

    @staticmethod
    def set_approval(
        db: Session,
        artifact: Artifact,
        *,
        approved_by_user_id: str,
        validation_status: str = "passed",
    ) -> Artifact:
        artifact.approved_by = approved_by_user_id
        artifact.validation_status = validation_status
        db.commit()
        db.refresh(artifact)
        return artifact
