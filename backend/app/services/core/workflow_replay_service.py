"""WorkflowReplayService — deterministic, read-only re-execution from the DB.

Replay re-runs the *executable* steps of a workflow (terraform validate/plan,
docker build) using ONLY artifacts already persisted in the database. It is
strictly deterministic and side-effect-bounded:

* NO LLM calls — the orchestrator/agents are never imported here.
* NO regeneration — terraform HCL and the Dockerfile are read from the DB
  (``ArtifactPersistenceService.get_terraform_files`` / ``get_docker_artifacts``),
  never re-produced.
* ONLY DB artifacts — the on-disk terraform working dir is rebuilt from DB; the
  docker build context is fed the DB artifacts. The source repo is re-cloned by
  the executor from the stored ``repo_url`` (config, not a generated artifact)
  because a build inherently needs its source tree.

It reuses the EXISTING durable job handlers (``terraform_validate`` /
``terraform_plan`` / ``docker_build``) — it does not fork or modify any workflow
logic; it just enqueues the same jobs the normal phases would, pointed at DB
artifacts, and records ``source='replay'`` trace rows.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.task import Task
from backend.app.models.workflow import Workflow
from backend.app.services.core.artifact_persistence_service import ArtifactPersistenceService
from backend.app.services.core.task_service import TaskService
from backend.app.services.core.workflow_trace_service import WorkflowTraceService
from backend.app.services.execution.docker_registry import generate_image_tag
from backend.app.services.execution.job_service import JobService

logger = logging.getLogger(__name__)


class WorkflowReplayService:
    @staticmethod
    def replay(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        task: Optional[Task],
    ) -> dict:
        """Replay a workflow's executable steps from DB artifacts only.

        Returns a structured summary of what was re-enqueued (job ids, stream
        keys) and what was skipped (no DB artifact). Never calls an LLM and never
        regenerates terraform/Dockerfile.
        """
        from backend.app.services.core.workflow_orchestration_service import (
            terraform_stream_key,
        )
        from backend.app.services.terraform_pipeline import TerraformPipelineService

        replay_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        steps: list[dict] = []
        skipped: list[dict] = []

        task_state = TaskService.load_workflow_state(db, task) if task else {}
        task_state = task_state or {}
        task_id = task.id if task else None

        # ── Terraform: rehydrate DB HCL → fresh dir → validate + plan jobs ────
        tf_files = ArtifactPersistenceService.get_terraform_files(
            db, project_id=project.id, workflow_id=workflow.id,
        )
        if tf_files:
            artifact_id = uuid.uuid4().hex[:12]
            TerraformPipelineService().rehydrate(
                artifact_id,
                tf_files,
                metadata={
                    "source": "replay",
                    "replay_id": replay_id,
                    "project_id": project.id,
                    "workflow_id": workflow.id,
                    "files": sorted(tf_files),
                    "generated_at": now.isoformat(),
                },
            )
            tf_inputs = {
                "artifact_id": artifact_id,
                "files": sorted(tf_files),
                "file_count": len(tf_files),
                "source": "db_artifacts",
            }
            for phase_name, job_phase in (
                ("TERRAFORM_VALIDATION", "terraform_validate"),
                ("TERRAFORM_PLAN", "terraform_plan"),
            ):
                stream_key = terraform_stream_key(task_id or workflow.id, job_phase)
                job = JobService.enqueue(
                    db,
                    project_id=project.id,
                    workflow_id=workflow.id,
                    task_id=task_id,
                    phase=job_phase,
                    max_retries=0,
                    idempotency_key=f"replay:{workflow.id}:{job_phase}:{replay_id}",
                    execution_context={
                        "artifact_id": artifact_id,
                        "task_id": task_id,
                        "workflow_id": workflow.id,
                        "phase": phase_name,
                        "stream_key": stream_key,
                        "replay_id": replay_id,
                    },
                )
                WorkflowTraceService.record_replay_step(
                    db,
                    workflow=workflow,
                    phase=phase_name,
                    status="enqueued",
                    started_at=now,
                    inputs=tf_inputs,
                    detail={"job_id": job.id, "stream_key": stream_key, "replay_id": replay_id},
                )
                steps.append({"phase": phase_name, "job_id": job.id, "stream_key": stream_key})
        else:
            skipped.append({"phase": "TERRAFORM", "reason": "no terraform artifacts in DB"})

        # ── Docker: build context from DB artifacts → docker_build job ────────
        docker_artifacts = ArtifactPersistenceService.get_docker_artifacts(
            db, project_id=project.id, workflow_id=workflow.id,
        )
        if docker_artifacts.get("dockerfile") and task_id:
            plan = task_state.get("plan") or (task.plan if task else None) or {}
            project_name = (
                plan.get("project_name") or plan.get("name") or project.name or "app"
            )
            image_tag = generate_image_tag(project_name=project_name, task_id=task_id)
            execution_session_id = (
                f"{task_id[:8]}-replay-{now.strftime('%Y%m%dT%H%M%S')}"
            )
            repo_url = task_state.get("repo_url") or task_state.get("repository_url")
            visibility = task_state.get("repository_visibility") or "public"

            job = JobService.enqueue(
                db,
                project_id=project.id,
                workflow_id=workflow.id,
                task_id=task_id,
                phase="docker_build",
                idempotency_key=f"replay:{workflow.id}:docker_build:{replay_id}",
                logs_reference="workflow_state.execution.docker.logs",
                execution_context={
                    "task_id": task_id,
                    "artifacts": docker_artifacts,  # DB-sourced, NOT regenerated
                    "image_tag": image_tag,
                    "is_retry": False,
                    "build_number": 1,
                    "build_strategy": {},
                    "repo_source_path": None,   # executor re-clones from repo_url
                    "execution_session_id": execution_session_id,
                    "repo_url": repo_url,
                    "repository_visibility": visibility,
                    "replay_id": replay_id,
                },
            )
            WorkflowTraceService.record_replay_step(
                db,
                workflow=workflow,
                phase="DOCKER_BUILD",
                status="enqueued",
                started_at=now,
                inputs={
                    "image_tag": image_tag,
                    "docker_keys": sorted(docker_artifacts),
                    "source": "db_artifacts",
                },
                detail={"job_id": job.id, "replay_id": replay_id, "ws_url": f"/ws/execution/{task_id}"},
            )
            steps.append(
                {"phase": "DOCKER_BUILD", "job_id": job.id, "ws_url": f"/ws/execution/{task_id}"}
            )
        elif not docker_artifacts.get("dockerfile"):
            skipped.append({"phase": "DOCKER_BUILD", "reason": "no Dockerfile artifact in DB"})
        elif not task_id:
            skipped.append({"phase": "DOCKER_BUILD", "reason": "workflow has no backing task"})

        logger.info(
            "[Replay] workflow=%s replay_id=%s enqueued=%d skipped=%d (DB-only, no LLM)",
            workflow.id, replay_id, len(steps), len(skipped),
        )
        return {
            "workflow_id": workflow.id,
            "replay_id": replay_id,
            "mode": "read_only_db_artifacts",
            "llm_used": False,
            "regenerated": False,
            "replayed": bool(steps),
            "steps": steps,
            "skipped": skipped,
        }
