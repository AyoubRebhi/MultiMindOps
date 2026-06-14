"""Dashboard aggregation schemas.

Response models for the DevOps Engineer Dashboard landing page. These are
READ-ONLY aggregation views — they never mutate workflow/project state, they
roll up counts and recent rows scoped to the calling user's project
memberships. See backend/app/services/core/dashboard_service.py for the
queries and backend/app/api/routes/dashboard.py for the endpoints.

This is the first frontend↔backend integration surface; the shapes are kept
deliberately small and presentation-agnostic (raw numbers + ISO timestamps).
The frontend maps them into KPI tiles / chart series / feed items.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel


# ─── Metrics (KPI tiles) ─────────────────────────────────────────────────────

Trend = Literal["up", "down", "flat"]


class MetricValue(BaseModel):
    """A single KPI. ``value`` is None when there is no data to compute it
    (e.g. success rate with zero finished workflows) so the frontend can render
    an explicit Empty state instead of a misleading 0."""

    value: Optional[float] = None
    # Human-friendly change string ("+2 this month", "-6.2%"). Optional — the
    # tile hides the delta badge when it is absent.
    delta: Optional[str] = None
    trend: Optional[Trend] = None


class DashboardMetrics(BaseModel):
    active_projects: MetricValue
    running_workflows: MetricValue
    # value is a percentage in 0..100 (or None when no finished workflows yet).
    pipeline_success_rate: MetricValue
    # value is a USD amount (or None when no cost has been estimated yet).
    monthly_cloud_spend: MetricValue


# ─── Usage trend (area chart) ────────────────────────────────────────────────

class UsagePoint(BaseModel):
    # Calendar day, ISO date (YYYY-MM-DD).
    date: str
    # Number of workflow runs started that day.
    count: int


# ─── Recent projects ─────────────────────────────────────────────────────────

class RecentProject(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    bootstrap_status: str
    repository_url: Optional[str] = None
    architecture_type: Optional[str] = None
    # Best-effort monthly cost rolled up from the project's cost_summary
    # context; None when no estimate exists yet.
    monthly_cost: Optional[float] = None
    updated_at: datetime
    created_at: datetime


# ─── Live activity ───────────────────────────────────────────────────────────

# Maps to the frontend ActivityFeed color buckets.
ActivityType = Literal["success", "running", "warning", "danger", "info"]


class ActivityItem(BaseModel):
    id: str
    type: ActivityType
    # Font Awesome icon class (e.g. "fa-circle-check").
    icon: str
    message: str
    # The raw backend status verb (started/succeeded/failed/...). Optional.
    status: Optional[str] = None
    at: datetime
