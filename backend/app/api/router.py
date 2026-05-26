from fastapi import APIRouter

from backend.app.api.routes.artifact_edit import router as artifact_edit_router
from backend.app.api.routes.artifacts import router as artifacts_router
from backend.app.api.routes.auth import router as auth_router
from backend.app.api.routes.corrector import router as corrector_router
from backend.app.api.routes.evaluation import router as evaluation_router
from backend.app.api.routes.execution import router as execution_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.projects import router as projects_router
from backend.app.api.routes.tasks import router as tasks_router
from backend.app.api.routes.workflow import router as workflow_router

api_router = APIRouter()
api_router.include_router(health_router)
# Auth must be public — registered before any other API routes so it
# is clearly visible in the route table and order-independent.
api_router.include_router(auth_router)
api_router.include_router(artifacts_router)
api_router.include_router(tasks_router)
api_router.include_router(evaluation_router)
api_router.include_router(workflow_router, prefix="/api")
# Project-centric routes — defines its own full /api/projects prefix.
api_router.include_router(projects_router)
# Execution engine routes define their own full paths (/api/execution/... and /ws/execution/...)
api_router.include_router(execution_router)
# Corrector agent routes (/api/corrector/...)
api_router.include_router(corrector_router)
# Editable artifact persistence (/api/tasks/{id}/artifacts)
api_router.include_router(artifact_edit_router)
