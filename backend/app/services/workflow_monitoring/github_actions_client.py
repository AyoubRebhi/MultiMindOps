"""Read-only GitHub Actions REST client.

ONLY issues authenticated ``GET`` requests. It never triggers, reruns, cancels,
or modifies anything — there is deliberately no POST/PUT/DELETE method on this
class. It is the monitoring analogue of ``pull_request_client``: every failure is
mapped to a typed :class:`GitHubActionsApiError` (with a coarse ``kind`` the
service maps to a human, non-leaking message); the caller decides how to degrade.

Minimum requests (see :mod:`monitoring_service`)
------------------------------------------------
* latest run per pipeline: ``GET /actions/workflows/{file}/runs?per_page=1``
  — the file basename is accepted in place of the numeric workflow id, so the
  two pipelines cost exactly **2 requests** for status/conclusion/branch/commit/
  actor/timestamps/url.
* OPTIONAL current step (only for a run that is still active):
  ``GET /actions/runs/{run_id}/jobs`` — at most +1 per active pipeline.

So: 2 requests typical, ≤4 worst case. No ``/actions/workflows`` listing call is
needed because the workflow URL is derived deterministically from the file name.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


class GitHubActionsApiError(Exception):
    """A GitHub Actions API call failed. ``kind`` is a coarse classification:

    * ``invalid_token``  — 401 (token missing/expired/revoked)
    * ``forbidden``      — 403 without a spent rate-limit (token lacks Actions read)
    * ``rate_limited``   — 403/429 with the rate limit exhausted
    * ``not_found``      — 404 (repository, workflow file, or branch not found)
    * ``api_error``      — any other status, or a network/transport error
    """

    def __init__(self, kind: str, message: str, *, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status


class GitHubActionsClient:
    """Minimal read-only client for the GitHub Actions REST API."""

    def __init__(
        self,
        token: str,
        *,
        timeout: int = 20,
        api_base: str = GITHUB_API,
        session: Optional[object] = None,
    ) -> None:
        # ``session`` is any object exposing ``.get(url, headers=, params=,
        # timeout=)`` — defaults to the ``requests`` module. Injectable so tests
        # never hit the network.
        self._token = token
        self._timeout = timeout
        self._api = api_base.rstrip("/")
        self._session = session or requests

    # ── Internal ───────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    def _get(self, path: str, *, params: Optional[dict] = None) -> dict:
        url = f"{self._api}{path}"
        try:
            resp = self._session.get(
                url, headers=self._headers(), params=params, timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise GitHubActionsApiError(
                "api_error",
                f"network error contacting GitHub ({exc.__class__.__name__})",
            ) from exc
        self._raise_for_status(resp)
        try:
            return resp.json() or {}
        except ValueError as exc:
            raise GitHubActionsApiError(
                "api_error", "GitHub returned a non-JSON response",
            ) from exc

    @staticmethod
    def _raise_for_status(resp) -> None:
        sc = getattr(resp, "status_code", None)
        if sc == 200:
            return
        if sc == 401:
            raise GitHubActionsApiError(
                "invalid_token",
                "the GitHub token is invalid or expired",
                status=401,
            )
        if sc in (403, 429):
            remaining = str((getattr(resp, "headers", {}) or {}).get(
                "X-RateLimit-Remaining", ""
            )).strip()
            if sc == 429 or remaining == "0":
                raise GitHubActionsApiError(
                    "rate_limited",
                    "GitHub API rate limit reached — monitoring will refresh shortly",
                    status=sc,
                )
            raise GitHubActionsApiError(
                "forbidden",
                "the GitHub token lacks permission to read Actions "
                "(a token with repo / actions:read scope is required)",
                status=sc,
            )
        if sc == 404:
            raise GitHubActionsApiError(
                "not_found",
                "the repository, workflow, or branch was not found",
                status=404,
            )
        raise GitHubActionsApiError(
            "api_error",
            f"the GitHub Actions API returned HTTP {sc}",
            status=sc,
        )

    # ── Read operations ────────────────────────────────────────────────────────

    def latest_run(
        self,
        owner: str,
        repo: str,
        workflow_file: str,
        *,
        branch: Optional[str] = None,
    ) -> Optional[dict]:
        """Return the most recent run for ``workflow_file`` (or None if none).

        ``workflow_file`` is the basename (e.g. ``bootstrap.yml``). One request.
        """
        params: dict = {"per_page": 1}
        if branch:
            params["branch"] = branch
        data = self._get(
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_file}/runs",
            params=params,
        )
        runs = data.get("workflow_runs") or []
        return runs[0] if runs else None

    def run_jobs(self, owner: str, repo: str, run_id: int) -> List[dict]:
        """Return the jobs of a run (for the optional current-step read)."""
        data = self._get(
            f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
            params={"per_page": 30},
        )
        return data.get("jobs") or []
