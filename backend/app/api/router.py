from fastapi import APIRouter

from backend.app.api.routes.artifact_edit import router as artifact_edit_router
from backend.app.api.routes.artifacts import router as artifacts_router
from backend.app.api.routes.auth import router as auth_router
from backend.app.api.routes.corrector import router as corrector_router
from backend.app.api.routes.credentials import router as credentials_router
from backend.app.api.routes.dashboard import router as dashboard_router
from backend.app.api.routes.evaluation import router as evaluation_router
from backend.app.api.routes.execution import router as execution_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.invitations import router as invitations_router
from backend.app.api.routes.jobs import router as jobs_router
from backend.app.api.routes.releases import router as releases_router
from backend.app.api.routes.projects import router as projects_router
from backend.app.api.routes.tasks import router as tasks_router
from backend.app.api.routes.workflows import router as workflows_router

# NOTE: the legacy task-scoped `/workflow/*` router and the unauthenticated
# `/terraform/*` router are intentionally NOT mounted. They were duplicate
# workflow surfaces that bypassed the single source of truth
# (`Workflow.phases_state`). The canonical surface is the project-scoped
# `POST /api/projects/{pid}/workflows...` (projects_router). The route modules
# remain on disk (dormant) but are unreachable.

api_router = APIRouter()
api_router.include_router(health_router)
# Auth must be public — registered before any other API routes so it
# is clearly visible in the route table and order-independent.
api_router.include_router(auth_router)
# Workspace invitations — admin create/list/resend/revoke (gated) + public
# token landing/accept. Mounted near auth since it shares the identity layer.
api_router.include_router(invitations_router)
api_router.include_router(artifacts_router)
api_router.include_router(tasks_router)
api_router.include_router(evaluation_router)
# Dashboard aggregation routes — read-only landing-page rollups
# (/api/dashboard/...). First frontend↔backend integration surface.
api_router.include_router(dashboard_router)
# Project-centric routes — defines its own full /api/projects prefix. This is
# the ONLY workflow *execution* surface (start/run/select-plan/replay).
api_router.include_router(projects_router)
# Platform-wide, read-only workflow listing (/api/workflows). Role-aware
# visibility (ADMIN = all, DEVOPS_ENGINEER = own). Powers the Workflows page;
# carries NO execution actions.
api_router.include_router(workflows_router)
# Credentials routes are project-scoped — full path is /api/projects/{pid}/credentials.
# Mounted alongside projects_router so the project-role gate applies.
api_router.include_router(credentials_router)
# Execution-jobs routes are project-scoped — /api/projects/{pid}/jobs/...
api_router.include_router(jobs_router)
# Release-candidate routes are project-scoped — /api/projects/{pid}/releases/...
api_router.include_router(releases_router)
# Execution engine routes define their own full paths (/api/execution/... and /ws/execution/...)
api_router.include_router(execution_router)
# Corrector agent routes (/api/corrector/...)
api_router.include_router(corrector_router)
# Editable artifact persistence (/api/tasks/{id}/artifacts)
api_router.include_router(artifact_edit_router)
