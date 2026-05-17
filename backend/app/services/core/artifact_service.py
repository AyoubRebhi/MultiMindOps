"""Editable artifact persistence and resolution.

Canonical state lives at workflow_state["infrastructure"]["artifacts"].
The legacy workflow_state["artifacts"] slot is mirrored for older callers.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.services.core.task_service import TaskService

logger = logging.getLogger(__name__)

DOCKER_ARTIFACT_KEYS = frozenset({"dockerfile", "dockerignore", "docker_compose", "env_example"})
FILE_TO_KEY = {
    "Dockerfile": "dockerfile",
    ".dockerignore": "dockerignore",
    "docker-compose.yml": "docker_compose",
    ".env.example": "env_example",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def _infra(state: dict) -> dict:
    return state.setdefault("infrastructure", {})


def _canonical_store(state: dict) -> dict:
    infra = _infra(state)
    canonical = infra.setdefault("artifacts", {})

    legacy = state.get("artifacts") or {}
    if not canonical and isinstance(legacy, dict):
        for key, entry in legacy.items():
            if key not in DOCKER_ARTIFACT_KEYS:
                continue
            if isinstance(entry, dict):
                original = entry.get("original_content") or entry.get("generated_content") or entry.get("current_content") or ""
                current = entry.get("current_content") or original
                canonical[key] = {
                    "current_content": current,
                    "original_content": original,
                    "generated_content": original,
                    "ai_patched_content": entry.get("ai_patched_content"),
                    "user_modified": bool(entry.get("user_modified") or entry.get("last_modified_by") == "user"),
                    "updated_at": entry.get("updated_at") or entry.get("last_modified_at") or _now(),
                    "last_modified_by": entry.get("last_modified_by") or "agent",
                    "last_modified_at": entry.get("last_modified_at") or entry.get("updated_at") or _now(),
                    "version": entry.get("version") or 1,
                    "checksum": entry.get("checksum") or _checksum(current),
                }

    # Mirror canonical storage for older callers while newer code reads infrastructure.artifacts.
    state["artifacts"] = canonical
    return canonical


def _append_history(
    state: dict,
    *,
    version: int,
    source: str,
    summary: str,
    artifact_type: str | None = None,
) -> None:
    history = _infra(state).setdefault("artifact_history", [])
    history.append({
        "version": version,
        "source": source,
        "timestamp": _now(),
        "summary": summary,
        **({"artifact_type": artifact_type} if artifact_type else {}),
    })


class ArtifactService:
    @staticmethod
    def initialize_from_state(state: dict, generated_artifacts: dict[str, str]) -> dict:
        """Initialize the editable artifact layer after Docker artifact generation."""
        now = _now()
        artifacts_store: dict = {}
        for key, content in generated_artifacts.items():
            if key not in DOCKER_ARTIFACT_KEYS:
                continue
            artifacts_store[key] = {
                "current_content": content,
                "original_content": content,
                "generated_content": content,
                "ai_patched_content": None,
                "user_modified": False,
                "updated_at": now,
                "last_modified_by": "agent",
                "last_modified_at": now,
                "version": 1,
                "checksum": _checksum(content),
            }

        infra = _infra(state)
        infra["artifacts"] = artifacts_store
        infra.setdefault("artifact_history", [])
        if artifacts_store and not infra["artifact_history"]:
            _append_history(
                state,
                version=1,
                source="generator",
                summary="Initial Docker artifact generation",
            )
        state["artifacts"] = artifacts_store
        logger.info(
            "[ArtifactService] Initialized %d artifacts in state (keys: %s)",
            len(artifacts_store),
            list(artifacts_store.keys()),
        )
        return state

    @staticmethod
    def save_artifact(
        db: Session,
        task,
        artifact_type: str,
        content: str,
        modified_by: str = "user",
    ) -> dict:
        saved = ArtifactService.save_many_artifacts(
            db,
            task,
            {artifact_type: content},
            modified_by=modified_by,
        )
        return saved[artifact_type]

    @staticmethod
    def save_many_artifacts(
        db: Session,
        task,
        artifacts: dict[str, str],
        modified_by: str = "user",
    ) -> dict[str, dict]:
        """Persist multiple artifacts in a single DB round-trip."""
        state = dict(TaskService.load_workflow_state(db, task) or {})
        artifacts_store: dict = _canonical_store(state)
        now = _now()
        saved: dict[str, dict] = {}

        for artifact_type, content in artifacts.items():
            if artifact_type not in DOCKER_ARTIFACT_KEYS:
                continue
            existing = artifacts_store.get(artifact_type) or {}
            new_version = (existing.get("version") or 0) + 1
            original = existing.get("original_content") or existing.get("generated_content") or content
            entry = {
                "current_content": content,
                "original_content": original,
                "generated_content": original,
                "ai_patched_content": existing.get("ai_patched_content"),
                "user_modified": modified_by == "user" or bool(existing.get("user_modified")),
                "updated_at": now,
                "last_modified_by": modified_by,
                "last_modified_at": now,
                "version": new_version,
                "checksum": _checksum(content),
            }
            artifacts_store[artifact_type] = entry
            saved[artifact_type] = entry
            _append_history(
                state,
                version=new_version,
                source=modified_by,
                summary=f"{'Manual' if modified_by == 'user' else modified_by} update saved for {artifact_type}",
                artifact_type=artifact_type,
            )

        state["artifacts"] = artifacts_store
        TaskService.save_workflow_state(db, task, state)
        logger.info(
            "[ArtifactService] Saved %d artifacts modified_by=%s task=%s",
            len(saved), modified_by, task.id,
        )
        return saved

    @staticmethod
    def get_current_artifact(db: Session, task, artifact_type: str) -> str | None:
        state = TaskService.load_workflow_state(db, task) or {}
        artifact = _canonical_store(state).get(artifact_type)
        if isinstance(artifact, dict):
            return artifact.get("current_content") or None
        return None

    @staticmethod
    def get_all_current_artifacts(db: Session, task) -> dict[str, str]:
        state = TaskService.load_workflow_state(db, task) or {}
        return extract_current_from_state(state)

    @staticmethod
    def get_artifact_metadata(db: Session, task) -> dict:
        state = TaskService.load_workflow_state(db, task) or {}
        return _canonical_store(state)

    @staticmethod
    def get_artifact_history(db: Session, task) -> list[dict]:
        state = TaskService.load_workflow_state(db, task) or {}
        _canonical_store(state)
        return _infra(state).get("artifact_history") or []

    @staticmethod
    def reset_artifact(db: Session, task, artifact_type: str) -> dict | None:
        state = dict(TaskService.load_workflow_state(db, task) or {})
        artifacts_store = _canonical_store(state)
        artifact = artifacts_store.get(artifact_type)
        if not artifact:
            return None

        artifact["current_content"] = artifact.get("original_content") or artifact.get("generated_content") or ""
        artifact["last_modified_by"] = "reset"
        artifact["last_modified_at"] = _now()
        artifact["updated_at"] = artifact["last_modified_at"]
        artifact["user_modified"] = False
        artifact["version"] = (artifact.get("version") or 0) + 1
        artifact["checksum"] = _checksum(artifact["current_content"])
        _append_history(
            state,
            version=artifact["version"],
            source="reset",
            summary=f"Reset {artifact_type} to original generated content",
            artifact_type=artifact_type,
        )
        state["artifacts"] = artifacts_store
        TaskService.save_workflow_state(db, task, state)
        logger.info(
            "[ArtifactService] Reset artifact=%s to original content task=%s",
            artifact_type, task.id,
        )
        return artifact

    @staticmethod
    def store_ai_patch_suggestions(db: Session, task, analysis: dict[str, Any]) -> dict[str, str]:
        """Store AI proposed content without overwriting current user content."""
        state = dict(TaskService.load_workflow_state(db, task) or {})
        artifacts_store = _canonical_store(state)
        patched: dict[str, str] = {}

        for patch in analysis.get("structured_patches") or []:
            file_name = patch.get("file") or ""
            artifact_key = FILE_TO_KEY.get(file_name, file_name.lower().replace("-", "_").replace(".", ""))
            if artifact_key not in DOCKER_ARTIFACT_KEYS:
                continue
            entry = artifacts_store.get(artifact_key)
            if not isinstance(entry, dict):
                continue
            content = patched.get(artifact_key) or entry.get("current_content") or ""
            target = patch.get("target") or ""
            replacement = patch.get("replacement") or ""
            operation = patch.get("operation") or "replace"
            if operation == "replace" and target in content:
                content = content.replace(target, replacement, 1)
            elif operation == "prepend_before" and target in content:
                content = content.replace(target, f"{replacement}\n{target}", 1)
            elif operation == "append_after" and target in content:
                content = content.replace(target, f"{target}\n{replacement}", 1)
            elif operation == "delete" and target in content:
                content = content.replace(target, "", 1)
            else:
                continue
            patched[artifact_key] = content

        now = _now()
        for key, content in patched.items():
            artifacts_store[key]["ai_patched_content"] = content
            artifacts_store[key]["ai_patch_updated_at"] = now

        if patched:
            _append_history(
                state,
                version=max((artifacts_store[k].get("version") or 1) for k in patched),
                source="corrector_ai",
                summary=f"AI patch proposal stored for {', '.join(sorted(patched))}",
            )
            state["artifacts"] = artifacts_store
            TaskService.save_workflow_state(db, task, state)
            logger.info("[ArtifactService] Stored AI patch previews task=%s keys=%s", task.id, list(patched))
        return patched

    @staticmethod
    def apply_ai_patches(db: Session, task) -> dict[str, dict]:
        state = dict(TaskService.load_workflow_state(db, task) or {})
        artifacts_store = _canonical_store(state)
        updates = {
            key: entry.get("ai_patched_content")
            for key, entry in artifacts_store.items()
            if isinstance(entry, dict) and entry.get("ai_patched_content")
        }
        return ArtifactService.save_many_artifacts(db, task, updates, modified_by="corrector_ai")


class ArtifactStateResolver:
    """Central resolver used by build, retry, and corrector flows."""

    @staticmethod
    def get_latest_artifacts(task_or_state: Any, db: Session | None = None) -> dict[str, str]:
        if isinstance(task_or_state, dict):
            state = task_or_state
        else:
            if db is None:
                raise ValueError("db is required when resolving artifacts from a task")
            state = TaskService.load_workflow_state(db, task_or_state) or {}

        current = extract_current_from_state(state)
        if current.get("dockerfile"):
            return current

        infra = state.get("infra") or {}
        artifacts: dict[str, str] = dict(infra.get("artifacts") or {})
        wf_result = state.get("result") or {}
        infra_result = wf_result.get("infrastructure") or {}
        artifacts.update(infra_result.get("artifacts") or {})
        return {
            key: value
            for key, value in artifacts.items()
            if key in DOCKER_ARTIFACT_KEYS and isinstance(value, str) and value
        }


def extract_current_from_state(workflow_state: dict) -> dict[str, str]:
    """Extract {key: current_content} from canonical editable artifact state."""
    result: dict[str, str] = {}
    for key, artifact in _canonical_store(workflow_state).items():
        if key in DOCKER_ARTIFACT_KEYS and isinstance(artifact, dict):
            content = artifact.get("current_content")
            if content:
                result[key] = content
    return result
