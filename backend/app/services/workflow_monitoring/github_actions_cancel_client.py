"""Cancel a running GitHub Actions workflow run.

The WRITE counterpart to the read-only :class:`GitHubActionsClient` and the
sibling of ``repository_installation.workflow_dispatch_client``: a single
authenticated ``POST`` to the GitHub Actions *cancel* endpoint. It mirrors the
dispatch client's contract — ALWAYS non-fatal: every failure path returns a
:class:`CancelRunOutcome` with a human ``error`` rather than raising, so a cancel
problem never breaks the (idempotent) workflow-cancellation flow.

GitHub returns ``202 Accepted`` when a cancel is queued and ``409 Conflict`` when
the run is already finished (so it cannot be cancelled) — both are reported, not
raised.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


@dataclass
class CancelRunOutcome:
    """Result of a single run-cancel attempt (never raised)."""

    run_id: int
    requested: bool = False          # GitHub accepted the cancel (202)
    already_finished: bool = False   # the run had already completed (409)
    status_code: Optional[int] = None
    error: Optional[str] = None

    def to_record(self, *, pipeline: str) -> dict:
        return {
            "pipeline": pipeline,
            "run_id": self.run_id,
            "requested": self.requested,
            "already_finished": self.already_finished,
            "status_code": self.status_code,
            "error": self.error,
        }


def cancel_workflow_run(
    *,
    owner: str,
    repo: str,
    token: str,
    run_id: int,
    timeout: int = 30,
) -> CancelRunOutcome:
    """Cancel run ``run_id`` via the GitHub Actions API. Never raises.

    ``POST /repos/{owner}/{repo}/actions/runs/{run_id}/cancel``. A 202 means the
    cancel was queued; a 409 means the run already finished (nothing to cancel).
    """
    endpoint = f"{GITHUB_API}/repos/{owner}/{repo}/actions/runs/{run_id}/cancel"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }

    try:
        resp = requests.post(endpoint, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return CancelRunOutcome(
            run_id=run_id,
            error=f"network error contacting GitHub ({exc.__class__.__name__})",
        )

    if resp.status_code == 202:
        logger.info("[Cancel] cancel queued for run=%s (%s/%s)", run_id, owner, repo)
        return CancelRunOutcome(run_id=run_id, requested=True, status_code=202)

    if resp.status_code == 409:
        # The run already reached a terminal state — not cancellable, not an error.
        return CancelRunOutcome(
            run_id=run_id, already_finished=True, status_code=409,
            error="the run had already finished, so it could not be cancelled",
        )

    if resp.status_code in (401, 403):
        return CancelRunOutcome(
            run_id=run_id, status_code=resp.status_code,
            error=(
                "the GitHub token lacks permission to cancel workflow runs "
                "(a token with actions:write scope is required)"
            ),
        )

    if resp.status_code == 404:
        return CancelRunOutcome(
            run_id=run_id, status_code=404,
            error="the workflow run was not found",
        )

    return CancelRunOutcome(
        run_id=run_id, status_code=resp.status_code,
        error=f"GitHub cancel API returned HTTP {resp.status_code}",
    )
