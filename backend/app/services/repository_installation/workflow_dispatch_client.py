"""FIX 1 — trigger the Infrastructure pipeline (bootstrap.yml) once installed.

A single authenticated POST to the GitHub Actions ``workflow_dispatch`` endpoint,
the write counterpart of the read-only monitoring client. It mirrors
``pull_request_client``: ALWAYS non-fatal — every failure path returns a
:class:`WorkflowDispatchOutcome` with a human ``error`` rather than raising, so a
dispatch problem never fails the (already successful) repository installation.

No polling, no waiting: the dispatch endpoint returns ``204 No Content`` with no
body, so there is no run id to read back — ``run_id`` stays ``None`` and the
monitoring phase (which already queries ``bootstrap.yml``) surfaces the actual
run on its next poll.

NOTE: GitHub resolves the workflow by file name against the repository's DEFAULT
branch. If bootstrap.yml has not yet reached the default branch (the install PR
is still open), GitHub returns 404 — captured here as a non-fatal dispatch
failure, distinct from a permission or transport error.
"""

from __future__ import annotations

import logging

import requests

from backend.app.services.repository_installation.models import (
    WorkflowDispatchOutcome,
)

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


def dispatch_workflow(
    *,
    owner: str,
    repo: str,
    token: str,
    workflow_file: str,
    ref: str,
    timeout: int = 30,
) -> WorkflowDispatchOutcome:
    """Trigger ``workflow_file`` on ``ref`` via workflow_dispatch. Never raises.

    ``workflow_file`` is the basename (e.g. ``bootstrap.yml``); ``ref`` is the
    branch the run executes against. Returns the typed outcome — the caller
    records ``dispatched`` / ``run_id`` regardless of result.
    """
    endpoint = (
        f"{GITHUB_API}/repos/{owner}/{repo}/actions/workflows/"
        f"{workflow_file}/dispatches"
    )
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }

    try:
        resp = requests.post(
            endpoint, headers=headers, json={"ref": ref}, timeout=timeout
        )
    except requests.RequestException as exc:
        return WorkflowDispatchOutcome(
            dispatched=False,
            error=f"network error contacting GitHub ({exc.__class__.__name__})",
        )

    if resp.status_code == 204:
        logger.info(
            "[RepoInstall] dispatched %s on ref=%s for %s/%s",
            workflow_file, ref, owner, repo,
        )
        return WorkflowDispatchOutcome(dispatched=True, status_code=204)

    if resp.status_code in (401, 403):
        return WorkflowDispatchOutcome(
            dispatched=False,
            status_code=resp.status_code,
            error=(
                "the GitHub token lacks permission to dispatch workflows "
                "(a token with actions:write / workflow scope is required)"
            ),
        )

    if resp.status_code == 404:
        return WorkflowDispatchOutcome(
            dispatched=False,
            status_code=404,
            error=(
                f"GitHub could not find a dispatchable '{workflow_file}' — the "
                "workflow must exist on the repository's default branch with an "
                "'on: workflow_dispatch' trigger (merge the installation PR, then "
                "dispatch)"
            ),
        )

    return WorkflowDispatchOutcome(
        dispatched=False,
        status_code=resp.status_code,
        error=f"GitHub workflow dispatch API returned HTTP {resp.status_code}",
    )
