"""DashboardService — read-only aggregation for the landing dashboard.

Everything here is scoped to the calling user's project memberships (the same
visibility rule ``ProjectService.list_projects_for_user`` enforces) and is
strictly read-only: it counts rows and rolls up recent records, never mutating
workflow or project state.

Design notes
------------
* Volumes on this platform are small (a handful of projects / workflows per
  user), so the day-bucketing for the usage trend and the activity merge are
  done in Python rather than with DB-specific date functions. This keeps the
  service portable across the Postgres (prod) / SQLite (tests) split the models
  already support, with no measurable cost.
* ``monthly_cloud_spend`` reads the ``cost_summary`` ProjectContext the cost
  estimation agent writes (see project_context_service); there is no separate
  billing store yet, so this is the authoritative estimate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.models.artifact import Artifact
from backend.app.models.project import Project, ProjectContext, ProjectMember
from backend.app.models.user import User
from backend.app.models.workflow import Workflow
from backend.app.models.workflow_event import WorkflowPhaseEvent
from backend.app.schemas.dashboard import (
    ActivityItem,
    DashboardMetrics,
    MetricValue,
    RecentProject,
    UsagePoint,
)

logger = logging.getLogger(__name__)

# Workflow.status buckets.
_RUNNING_STATUSES = ("running", "pending", "awaiting_input")
_TERMINAL_STATUSES = ("completed", "failed", "cancelled")
_SUCCESS_STATUS = "completed"

# Artifact types worth surfacing in the activity feed (others are internal
# rollups / analysis blobs that would only add noise).
_ACTIVITY_ARTIFACT_TYPES = ("terraform", "docker", "kubernetes", "cicd")

# Solid Font Awesome icons keyed by artifact type — the frontend ActivityFeed
# renders with the `fa-solid` prefix, so brand icons (fa-docker) are avoided.
_ARTIFACT_ICON = {
    "terraform": "fa-cubes",
    "docker": "fa-cube",
    "kubernetes": "fa-dharmachakra",
    "cicd": "fa-code-branch",
}
_ARTIFACT_VERB = {
    "terraform": "Terraform generated",
    "docker": "Docker artifact generated",
    "kubernetes": "Kubernetes manifests generated",
    "cicd": "CI/CD pipeline generated",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_amount(value) -> Optional[float]:
    """Best-effort parse a monthly_cost into a float.

    The cost agent may store a number or a formatted string ("$412/mo"). We
    strip everything that isn't part of a number and parse what's left.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = "".join(ch for ch in str(value) if ch.isdigit() or ch in ".-")
    if not cleaned or cleaned in (".", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize a possibly-naive datetime to UTC-aware for safe comparison."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class DashboardService:
    # ── shared scoping helper ────────────────────────────────────────────────
    @staticmethod
    def _user_project_ids(db: Session, user: User) -> List[str]:
        rows = (
            db.query(ProjectMember.project_id)
            .filter(ProjectMember.user_id == user.id)
            .all()
        )
        return [r[0] for r in rows]

    # ── metrics ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_metrics(db: Session, user: User) -> DashboardMetrics:
        project_ids = DashboardService._user_project_ids(db, user)
        if not project_ids:
            zero = MetricValue(value=0, trend="flat")
            return DashboardMetrics(
                active_projects=zero,
                running_workflows=MetricValue(value=0, trend="flat"),
                pipeline_success_rate=MetricValue(value=None),
                monthly_cloud_spend=MetricValue(value=None),
            )

        now = _utcnow()
        month_ago = now - timedelta(days=30)
        two_months_ago = now - timedelta(days=60)

        projects = db.query(Project).filter(Project.id.in_(project_ids)).all()
        workflows = db.query(Workflow).filter(Workflow.project_id.in_(project_ids)).all()

        # 1) Active projects (everything not archived) + new-this-month delta.
        active = [p for p in projects if (p.current_status or "").lower() != "archived"]
        new_this_month = sum(
            1 for p in projects if _aware(p.created_at) and _aware(p.created_at) >= month_ago
        )
        active_metric = MetricValue(
            value=len(active),
            delta=f"+{new_this_month} this month" if new_this_month else None,
            trend="up" if new_this_month else "flat",
        )

        # 2) Running workflows — point-in-time gauge, no delta.
        running_count = sum(
            1 for w in workflows if (w.status or "").lower() in _RUNNING_STATUSES
        )
        running_metric = MetricValue(value=running_count, trend="flat")

        # 3) Pipeline success rate — lifetime value, trend = last-30d vs prior-30d.
        success_metric = DashboardService._success_rate_metric(
            workflows, month_ago, two_months_ago
        )

        # 4) Monthly cloud spend — sum of cost_summary estimates.
        spend_metric = DashboardService._monthly_spend_metric(db, project_ids)

        return DashboardMetrics(
            active_projects=active_metric,
            running_workflows=running_metric,
            pipeline_success_rate=success_metric,
            monthly_cloud_spend=spend_metric,
        )

    @staticmethod
    def _success_rate_metric(
        workflows: List[Workflow], month_ago: datetime, two_months_ago: datetime
    ) -> MetricValue:
        def rate(items: List[Workflow]) -> Optional[float]:
            finished = [w for w in items if (w.status or "").lower() in _TERMINAL_STATUSES]
            if not finished:
                return None
            ok = sum(1 for w in finished if (w.status or "").lower() == _SUCCESS_STATUS)
            return round(ok / len(finished) * 100, 1)

        lifetime = rate(workflows)
        if lifetime is None:
            return MetricValue(value=None)

        recent = rate([w for w in workflows if _aware(w.created_at) and _aware(w.created_at) >= month_ago])
        prior = rate(
            [
                w
                for w in workflows
                if _aware(w.created_at)
                and two_months_ago <= _aware(w.created_at) < month_ago
            ]
        )
        delta = None
        trend = "flat"
        if recent is not None and prior is not None:
            diff = round(recent - prior, 1)
            if diff != 0:
                delta = f"{'+' if diff > 0 else ''}{diff}%"
                trend = "up" if diff > 0 else "down"
        return MetricValue(value=lifetime, delta=delta, trend=trend)

    @staticmethod
    def _monthly_spend_metric(db: Session, project_ids: List[str]) -> MetricValue:
        contexts = (
            db.query(ProjectContext)
            .filter(
                ProjectContext.project_id.in_(project_ids),
                ProjectContext.context_type == "cost_summary",
            )
            .all()
        )
        amounts = [
            _coerce_amount((c.content or {}).get("monthly_cost")) for c in contexts
        ]
        amounts = [a for a in amounts if a is not None]
        if not amounts:
            return MetricValue(value=None)
        return MetricValue(value=round(sum(amounts), 2), trend="flat")

    # ── usage trend ──────────────────────────────────────────────────────────
    @staticmethod
    def get_usage(db: Session, user: User, days: int = 14) -> List[UsagePoint]:
        days = max(1, min(days, 90))
        project_ids = DashboardService._user_project_ids(db, user)

        # Pre-seed every day in the window with a zero count so the chart always
        # renders a continuous series even on sparse days.
        today = _utcnow().date()
        start = today - timedelta(days=days - 1)
        buckets = {start + timedelta(days=i): 0 for i in range(days)}

        if project_ids:
            since = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
            rows = (
                db.query(Workflow.created_at)
                .filter(
                    Workflow.project_id.in_(project_ids),
                    Workflow.created_at >= since,
                )
                .all()
            )
            for (created_at,) in rows:
                created = _aware(created_at)
                if created is None:
                    continue
                day = created.date()
                if day in buckets:
                    buckets[day] += 1

        return [
            UsagePoint(date=day.isoformat(), count=count)
            for day, count in sorted(buckets.items())
        ]

    # ── recent projects ──────────────────────────────────────────────────────
    @staticmethod
    def get_recent_projects(db: Session, user: User, limit: int = 6) -> List[RecentProject]:
        limit = max(1, min(limit, 24))
        project_ids = DashboardService._user_project_ids(db, user)
        if not project_ids:
            return []

        projects = (
            db.query(Project)
            .filter(Project.id.in_(project_ids))
            .order_by(Project.updated_at.desc())
            .limit(limit)
            .all()
        )

        # Roll up cost_summary estimates for just these projects in one query.
        recent_ids = [p.id for p in projects]
        cost_by_project = {}
        if recent_ids:
            for c in (
                db.query(ProjectContext)
                .filter(
                    ProjectContext.project_id.in_(recent_ids),
                    ProjectContext.context_type == "cost_summary",
                )
                .all()
            ):
                cost_by_project[c.project_id] = _coerce_amount(
                    (c.content or {}).get("monthly_cost")
                )

        return [
            RecentProject(
                id=p.id,
                name=p.name,
                description=p.description,
                status=p.current_status,
                bootstrap_status=p.bootstrap_status,
                repository_url=p.repository_url,
                architecture_type=p.architecture_type,
                monthly_cost=cost_by_project.get(p.id),
                updated_at=p.updated_at,
                created_at=p.created_at,
            )
            for p in projects
        ]

    # ── live activity ────────────────────────────────────────────────────────
    @staticmethod
    def get_activity(db: Session, user: User, limit: int = 8) -> List[ActivityItem]:
        limit = max(1, min(limit, 50))
        project_ids = DashboardService._user_project_ids(db, user)
        if not project_ids:
            return []

        items: List[ActivityItem] = []

        # Source 1 — workflow phase events (richest signal).
        events = (
            db.query(WorkflowPhaseEvent)
            .filter(WorkflowPhaseEvent.project_id.in_(project_ids))
            .order_by(WorkflowPhaseEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        for e in events:
            items.append(DashboardService._event_to_item(e))

        # Source 2 — project creations.
        for p in (
            db.query(Project)
            .filter(Project.id.in_(project_ids))
            .order_by(Project.created_at.desc())
            .limit(limit)
            .all()
        ):
            items.append(
                ActivityItem(
                    id=f"proj-{p.id}",
                    type="info",
                    icon="fa-folder-plus",
                    message=f'Project "{p.name}" created',
                    status="created",
                    at=p.created_at,
                )
            )

        # Source 3 — generated infrastructure artifacts.
        for a in (
            db.query(Artifact)
            .filter(
                Artifact.project_id.in_(project_ids),
                Artifact.artifact_type.in_(_ACTIVITY_ARTIFACT_TYPES),
            )
            .order_by(Artifact.created_at.desc())
            .limit(limit)
            .all()
        ):
            atype = (a.artifact_type or "").lower()
            items.append(
                ActivityItem(
                    id=f"art-{a.id}",
                    type="success",
                    icon=_ARTIFACT_ICON.get(atype, "fa-file-code"),
                    message=_ARTIFACT_VERB.get(atype, f"{a.artifact_subtype} generated"),
                    status="generated",
                    at=a.created_at,
                )
            )

        # Merge: newest-first, capped at the requested limit.
        items.sort(key=lambda it: _aware(it.at) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return items[:limit]

    @staticmethod
    def _event_to_item(e: WorkflowPhaseEvent) -> ActivityItem:
        status = (e.status or "").lower()
        if status in ("succeeded", "approved"):
            atype, icon = "success", "fa-circle-check"
        elif status in ("failed", "rejected"):
            atype, icon = "danger", "fa-circle-xmark"
        elif status == "started":
            atype, icon = "running", "fa-spinner"
        elif status in ("awaiting_input",):
            atype, icon = "warning", "fa-user-check"
        elif status in ("cancelled", "superseded"):
            atype, icon = "warning", "fa-ban"
        else:
            atype, icon = "info", "fa-circle-info"

        message = e.message
        if not message:
            phase = (e.phase or "").replace("_", " ").title()
            message = f"{phase} {status}".strip()
        return ActivityItem(
            id=f"evt-{e.id}",
            type=atype,
            icon=icon,
            message=message,
            status=status or None,
            at=e.created_at,
        )
