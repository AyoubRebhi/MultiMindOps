"""Typed monitoring observations + the bootstrap/deploy pipeline registry.

The two installed pipelines are matched by their **file name** (rename-proof:
the workflow's display ``name:`` is user-editable, the file path is stable), the
same identity the GitHub Actions projection uses. The GitHub "list workflow runs
for a workflow" endpoint accepts the file basename in place of the numeric id,
so a single request per pipeline resolves its latest run — no extra
``/actions/workflows`` listing call is needed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Canonical installed paths (mirror RepositoryInstallation + GH-Actions phases).
BOOTSTRAP_PATH = ".github/workflows/bootstrap.yml"
DEPLOY_PATH = ".github/workflows/deploy.yml"

# Pipeline registry keyed by the stable ``kind``. ``file`` is the workflow file
# basename used to query runs; ``name`` is the human pipeline label shown in the
# UI (the SAME split the GitHub Actions projection uses).
PIPELINES: Dict[str, Dict[str, str]] = {
    "bootstrap": {
        "file": "bootstrap.yml",
        "path": BOOTSTRAP_PATH,
        "name": "Infrastructure Pipeline",
    },
    "deploy": {
        "file": "deploy.yml",
        "path": DEPLOY_PATH,
        "name": "Delivery Pipeline",
    },
}

# GitHub Actions run ``status`` values that mean the run is still going — the
# only case where we spend the optional extra request to read the current step.
ACTIVE_RUN_STATUSES = frozenset(
    {"queued", "in_progress", "waiting", "requested", "pending"}
)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse a GitHub ISO-8601 timestamp (``...Z``) to an aware datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def compute_duration_seconds(
    started_at: Optional[str],
    completed_at: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """Whole-second run duration.

    For a finished run: ``completed_at - started_at``. For a still-running run
    (no ``completed_at``): ``now - started_at`` (a snapshot — the UI keeps it
    ticking from ``started_at``). Returns None when there is no start time.
    """
    start = _parse_ts(started_at)
    if start is None:
        return None
    end = _parse_ts(completed_at) or (now or datetime.now(timezone.utc))
    delta = (end - start).total_seconds()
    return int(delta) if delta >= 0 else None


@dataclass
class RunObservation:
    """The latest observed run of ONE pipeline (bootstrap or deploy).

    ``available`` = we could query the GitHub Actions API for this pipeline
    (auth + network OK). ``found`` = a run actually exists. So a freshly
    installed repo that has never dispatched bootstrap is
    ``available=True, found=False`` (an honest "no runs yet"), distinct from
    ``available=False`` (a token/permission/rate-limit/API failure, with
    ``error`` set).
    """

    pipeline: str                       # "bootstrap" | "deploy"
    name: str                           # "Infrastructure Pipeline" | "Delivery Pipeline"
    workflow_file: str                  # "bootstrap.yml" | "deploy.yml"
    workflow_url: Optional[str] = None  # repo's workflow page (runs list)

    available: bool = True
    found: bool = False

    run_id: Optional[int] = None
    run_number: Optional[int] = None
    status: Optional[str] = None        # queued | in_progress | completed | ...
    conclusion: Optional[str] = None    # success | failure | cancelled | ... | None
    branch: Optional[str] = None
    commit_sha: Optional[str] = None
    actor: Optional[str] = None
    event: Optional[str] = None         # push | workflow_dispatch | ...
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    html_url: Optional[str] = None      # the run URL

    # Optional step data (only fetched for an active run; best-effort).
    current_job: Optional[str] = None
    current_step: Optional[str] = None

    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RunObservation":
        """Rebuild from a persisted snapshot dict, ignoring unknown keys."""
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


@dataclass
class MonitoringSnapshot:
    """The full monitoring state for a workflow at a point in time."""

    repo_url: Optional[str]
    fetched_at: str
    monitoring_available: bool
    error: Optional[str]
    bootstrap: RunObservation
    deploy: RunObservation
    stale: bool = False

    def to_artifact_dict(self) -> dict:
        """Durable record persisted as the ``workflow_monitoring`` artifact."""
        return {
            "repo_url": self.repo_url,
            "fetched_at": self.fetched_at,
            "monitoring_available": self.monitoring_available,
            "error": self.error,
            "bootstrap": self.bootstrap.to_dict(),
            "deploy": self.deploy.to_dict(),
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
