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