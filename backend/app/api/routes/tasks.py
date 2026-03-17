from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agents.orchestrator_agent import OrchestratorAgent
from backend.app.database.session import SessionLocal
from backend.app.schemas.task import TaskCreate, TaskResponse
from backend.app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/", response_model=TaskResponse)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)):
    task = TaskService.create_task(db, payload.prompt)

    try:
        TaskService.update_task_status(db, task, "in_progress")
        TaskService.append_log(db, task, "orchestrator", "Starting orchestration")

        orchestrator = OrchestratorAgent()
        result = orchestrator.process_request(payload.prompt)

        TaskService.append_log(db, task, "planner", "Execution plan generated")
        TaskService.save_plan(db, task, result["plan"])
        TaskService.save_result(db, task, result)
        TaskService.update_task_status(db, task, "completed")
        TaskService.append_log(db, task, "completed", "Task completed successfully")

    except Exception as e:
        task = TaskService.save_error(db, task, str(e))
        raise HTTPException(status_code=500, detail=f"Task processing failed: {str(e)}")

    return task


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db)):
    task = TaskService.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

@router.get("/", response_model=list[TaskResponse])
def list_tasks(db: Session = Depends(get_db)):
    return TaskService.list_tasks(db)