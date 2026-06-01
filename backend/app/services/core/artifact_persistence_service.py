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
_CLASSIFICATION_RULES: List[Tuple[str, str]] = [
    # (substring or extension to match in lowercase filename, artifact_type)
    ("dockerfile",        "docker"),
    (".dockerignore",     "docker"),
    ("docker-compose",    "docker"),
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
    ) -> List[Artifact]:
        """Persist every classifiable artifact in state.

        Returns the list of ``Artifact`` rows that were created or updated.
        Unclassifiable files are silently skipped — they're not artifacts.
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

        db.commit()
        logger.info(
            "[ArtifactPersistence] persisted %d artifacts for project=%s workflow=%s",
            len(persisted), project_id, workflow_id,
        )
        return persisted

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
