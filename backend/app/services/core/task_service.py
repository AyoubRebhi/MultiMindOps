from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.models.task import Task


class TaskService:
    @staticmethod
    def create_task(db: Session, prompt: str) -> Task:
        task = Task(
            prompt=prompt,
            status="pending",
            logs=[{"step": "task_created", "message": "Task created successfully"}],
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def get_task(db: Session, task_id: str) -> Optional[Task]:
        return db.query(Task).filter(Task.id == task_id).first()

    @staticmethod
    def list_tasks(db: Session):
        return db.query(Task).order_by(Task.created_at.desc()).all()

    @staticmethod
    def update_task_status(db: Session, task: Task, status: str) -> Task:
        task.status = status
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def append_log(db: Session, task: Task, step: str, message: str) -> Task:
        if task.logs is None:
            task.logs = []

        task.logs.append({
            "step": step,
            "message": message
        })

        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def save_plan(db: Session, task: Task, plan: dict) -> Task:
        task.plan = plan
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def save_result(db: Session, task: Task, result: dict) -> Task:
        task.result = result
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def initialize_human_review(db: Session, task: Task) -> Task:
        result = dict(task.result or {})
        infrastructure = dict(result.get("infrastructure") or {})
        artifacts = dict(infrastructure.get("artifacts") or {})

        if not artifacts:
            return task

        result["status"] = "awaiting_human_review"
        result["human_review"] = {
            "status": "awaiting_review",
            "original_artifacts": artifacts,
            "reviewed_artifacts": artifacts,
            "changed_artifacts": [],
            "review_notes": None,
            "reviewed_at": None,
        }

        task.result = result
        task.status = "awaiting_human_review"
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def apply_human_review(
        db: Session,
        task: Task,
        reviewed_artifacts: dict[str, str],
        review_notes: str | None = None,
    ) -> Task:
        result = dict(task.result or {})
        infrastructure = dict(result.get("infrastructure") or {})
        human_review = dict(result.get("human_review") or {})
        original_artifacts = dict(human_review.get("original_artifacts") or {})

        changed_artifacts = sorted(
            artifact_name
            for artifact_name in set(original_artifacts) | set(reviewed_artifacts)
            if original_artifacts.get(artifact_name) != reviewed_artifacts.get(artifact_name)
        )

        infrastructure["artifacts"] = reviewed_artifacts
        result["infrastructure"] = infrastructure
        result["status"] = (
            "human_approved_with_changes" if changed_artifacts else "human_approved"
        )
        result["human_review"] = {
            "status": "approved_with_changes" if changed_artifacts else "approved",
            "original_artifacts": original_artifacts,
            "reviewed_artifacts": reviewed_artifacts,
            "changed_artifacts": changed_artifacts,
            "review_notes": review_notes,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }

        task.result = result
        task.status = result["status"]
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def save_error(db: Session, task: Task, error_message: str) -> Task:
        task.error_message = error_message
        task.status = "failed"

        if task.logs is None:
            task.logs = []

        task.logs.append({
            "step": "error",
            "message": error_message
        })

        db.commit()
        db.refresh(task)
        return task
