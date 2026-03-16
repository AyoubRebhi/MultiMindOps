from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database.session import get_db
from ...schemas.task import TaskCreate, TaskRead
from ...services.task_service import create_task, get_tasks

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
def read_tasks(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return get_tasks(db, skip=skip, limit=limit)


@router.post("", response_model=TaskRead, status_code=201)
def create_new_task(task_in: TaskCreate, db: Session = Depends(get_db)):
    return create_task(db, task_in)
