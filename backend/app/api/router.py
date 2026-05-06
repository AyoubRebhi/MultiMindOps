from fastapi import APIRouter

from backend.app.api.routes.artifacts import router as artifacts_router
from backend.app.api.routes.evaluation import router as evaluation_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.tasks import router as tasks_router
from backend.app.api.routes.workflow import router as workflow_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(artifacts_router)
api_router.include_router(tasks_router)
api_router.include_router(evaluation_router)
api_router.include_router(workflow_router, prefix="/api")
