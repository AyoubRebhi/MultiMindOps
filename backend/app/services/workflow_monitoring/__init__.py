"""Workflow Monitoring — READ-ONLY observation of GitHub Actions runs.

This package observes the two pipelines the REPOSITORY_INSTALLATION phase
installed into the user's repository:

    .github/workflows/bootstrap.yml  → Infrastructure Pipeline
    .github/workflows/deploy.yml     → Delivery Pipeline

It NEVER triggers, reruns, cancels, or modifies anything on GitHub. It only
issues authenticated GET requests against the GitHub Actions REST API and
reshapes the latest run of each workflow into a monitoring snapshot. A
monitoring failure (bad token, missing permission, deleted repo/workflow, rate
limit, network error) is always captured and surfaced as a degraded state —
it NEVER raises into, and NEVER fails, the workflow.
"""

from backend.app.services.workflow_monitoring.github_actions_client import (
    GitHubActionsApiError,
    GitHubActionsClient,
)
from backend.app.services.workflow_monitoring.models import (
    PIPELINES,
    RunObservation,
)
from backend.app.services.workflow_monitoring.monitoring_service import (
    WorkflowMonitoringService,
)

__all__ = [
    "GitHubActionsApiError",
    "GitHubActionsClient",
    "PIPELINES",
    "RunObservation",
    "WorkflowMonitoringService",
]
