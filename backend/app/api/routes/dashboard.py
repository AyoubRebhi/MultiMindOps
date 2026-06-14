"""Dashboard aggregation API.

Read-only landing-page rollups, scoped to the authenticated user's project
memberships. This is the first frontend↔backend integration surface — four
narrow endpoints, one per dashboard widget, so each widget can load, empty,
error and retry independently on the client.

    GET /api/dashboard/metrics              4 KPI tiles
    GET /api/dashboard/usage?days=14        workflow-runs-per-day series
    GET /api/dashboard/recent-projects      most-recently-updated projects
    GET /api/dashboard/activity?limit=8     merged live activity feed

None of these mutate state; see services/core/dashboard_service.py.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.core.security import get_current_user, get_db
from backend.app.models.user import User
from backend.app.schemas.dashboard import (
    ActivityItem,
    DashboardMetrics,
    RecentProject,
    UsagePoint,
)
from backend.app.services.core.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/metrics", response_model=DashboardMetrics)
def get_dashboard_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Active projects, running workflows, pipeline success %, monthly spend."""
    return DashboardService.get_metrics(db, current_user)


@router.get("/usage", response_model=List[UsagePoint])
def get_dashboard_usage(
    days: int = Query(14, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Workflow runs per calendar day over the last ``days`` days (zero-filled)."""
    return DashboardService.get_usage(db, current_user, days=days)


@router.get("/recent-projects", response_model=List[RecentProject])
def get_dashboard_recent_projects(
    limit: int = Query(6, ge=1, le=24),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Most-recently-updated projects the caller is a member of."""
    return DashboardService.get_recent_projects(db, current_user, limit=limit)


@router.get("/activity", response_model=List[ActivityItem])
def get_dashboard_activity(
    limit: int = Query(8, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Merged, newest-first feed of workflow events, project + artifact creation."""
    return DashboardService.get_activity(db, current_user, limit=limit)
