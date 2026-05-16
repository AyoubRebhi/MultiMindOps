"""
ArtifactService — Editable artifact persistence layer.

Artifacts have two content slots:
  generated_content  — immutable original from the agent; never overwritten
  current_content    — user-editable; used by ALL execution paths

State location: workflow_state["artifacts"][key] = { generated_content, current_content, ... }
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.services.core.task_service import TaskService

logger = logging.getLogger(__name__)

DOCKER_ARTIFACT_KEYS = frozenset({"dockerfile", "dockerignore", "docker_compose", "env_example"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactService:

    @staticmethod
    def initialize_from_state(state: dict, generated_artifacts: dict[str, str]) -> dict:
        """
        Initialize the editable artifact layer inside an already-loaded state dict.

        Called right after run_docker_phase() so that workflow_state["artifacts"]
        is populated before the final save_workflow_state() call.  Returns the
        mutated state (also modified in-place).
        """
        artifacts_store: dict = {}
        now = _now()
        for key, content in generated_artifacts.items():
            if key not in DOCKER_ARTIFACT_KEYS:
                continue
            artifacts_store[key] = {
                "generated_content": content,
                "current_content": content,
                "last_modified_by": "agent",
                "last_modified_at": now,
                "version": 1,
            }
        state["artifacts"] = artifacts_store
        logger.info(
            "[ArtifactService] Initialized %d artifacts in state (keys: %s)",
            len(artifacts_store),
            list(artifacts_store.keys()),
        )
        return state

    # ── DB-backed operations ──────────────────────────────────────────────────

    @staticmethod
    def save_artifact(
        db: Session,
        task,
        artifact_type: str,
        content: str,
        modified_by: str = "user",
    ) -> dict:
        """Persist an edited artifact.  Bumps version, preserves generated_content."""
        state = dict(TaskService.load_workflow_state(db, task) or {})
        artifacts_store: dict = state.setdefault("artifacts", {})

        existing = artifacts_store.get(artifact_type) or {}
        new_version = (existing.get("version") or 0) + 1
        checksum = hashlib.sha256(content.encode()).hexdigest()[:12]

        artifacts_store[artifact_type] = {
            "generated_content": existing.get("generated_content", content),
            "current_content": content,
            "last_modified_by": modified_by,
            "last_modified_at": _now(),
            "version": new_version,
            "checksum": checksum,
        }

        TaskService.save_workflow_state(db, task, state)
        logger.info(
            "[ArtifactService] Saved artifact=%s version=%d modified_by=%s checksum=%s task=%s",
            artifact_type, new_version, modified_by, checksum, task.id,
        )
        return artifacts_store[artifact_type]

    @staticmethod
    def save_many_artifacts(
        db: Session,
        task,
        artifacts: dict[str, str],
        modified_by: str = "user",
    ) -> dict[str, dict]:
        """Persist multiple artifacts in a single DB round-trip."""
        state = dict(TaskService.load_workflow_state(db, task) or {})
        artifacts_store: dict = state.setdefault("artifacts", {})
        now = _now()
        saved: dict[str, dict] = {}

        for artifact_type, content in artifacts.items():
            existing = artifacts_store.get(artifact_type) or {}
            new_version = (existing.get("version") or 0) + 1
            checksum = hashlib.sha256(content.encode()).hexdigest()[:12]
            entry = {
                "generated_content": existing.get("generated_content", content),
                "current_content": content,
                "last_modified_by": modified_by,
                "last_modified_at": now,
                "version": new_version,
                "checksum": checksum,
            }
            artifacts_store[artifact_type] = entry
            saved[artifact_type] = entry

        TaskService.save_workflow_state(db, task, state)
        logger.info(
            "[ArtifactService] Saved %d artifacts modified_by=%s task=%s",
            len(saved), modified_by, task.id,
        )
        return saved

    @staticmethod
    def get_current_artifact(db: Session, task, artifact_type: str) -> str | None:
        """Return the latest editable content for a single artifact."""
        state = TaskService.load_workflow_state(db, task) or {}
        artifact = (state.get("artifacts") or {}).get(artifact_type)
        if isinstance(artifact, dict):
            return artifact.get("current_content") or None
        return None

    @staticmethod
    def get_all_current_artifacts(db: Session, task) -> dict[str, str]:
        """Return {key: current_content} for all persisted editable artifacts."""
        state = TaskService.load_workflow_state(db, task) or {}
        result: dict[str, str] = {}
        for key, artifact in (state.get("artifacts") or {}).items():
            if isinstance(artifact, dict):
                content = artifact.get("current_content")
                if content:
                    result[key] = content
        return result

    @staticmethod
    def get_artifact_metadata(db: Session, task) -> dict:
        """Return the full structured artifact store (with version/timestamps)."""
        state = TaskService.load_workflow_state(db, task) or {}
        return state.get("artifacts") or {}

    @staticmethod
    def reset_artifact(db: Session, task, artifact_type: str) -> dict | None:
        """Reset current_content to generated_content for one artifact."""
        state = dict(TaskService.load_workflow_state(db, task) or {})
        artifacts_store = state.get("artifacts") or {}
        artifact = artifacts_store.get(artifact_type)
        if not artifact:
            return None

        artifact["current_content"] = artifact.get("generated_content", "")
        artifact["last_modified_by"] = "reset"
        artifact["last_modified_at"] = _now()
        artifact["version"] = (artifact.get("version") or 0) + 1

        TaskService.save_workflow_state(db, task, state)
        logger.info(
            "[ArtifactService] Reset artifact=%s to generated content task=%s",
            artifact_type, task.id,
        )
        return artifact


# ── Stateless helper used by execution/corrector routes ──────────────────────

def extract_current_from_state(workflow_state: dict) -> dict[str, str]:
    """
    Extract {key: current_content} from workflow_state["artifacts"].

    Returns only keys present in DOCKER_ARTIFACT_KEYS with non-empty content.
    Does NOT touch the DB — works on the already-loaded state dict.
    """
    result: dict[str, str] = {}
    for key, artifact in (workflow_state.get("artifacts") or {}).items():
        if key in DOCKER_ARTIFACT_KEYS and isinstance(artifact, dict):
            content = artifact.get("current_content")
            if content:
                result[key] = content
    return result
