"""Optional Pull Request creation via the GitHub REST API.

ALWAYS non-fatal. The branch is pushed and reviewable regardless of whether a PR
can be opened, so every failure path here returns a :class:`PullRequestOutcome`
with a human ``skipped_reason`` rather than raising — the installation as a whole
still succeeds. This is the "If PR creation is difficult: skip it, document the
limitation" contract.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from backend.app.services.repository_installation.models import PullRequestOutcome

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


def open_pull_request(
    *,
    owner: str,
    repo: str,
    token: str,
    head: str,
    base: str,
    title: str,
    body: str,
    timeout: int = 30,
) -> PullRequestOutcome:
    """Open a PR ``head`` → ``base``; return the outcome (never raise).

    On a 422 (the usual "a PR already exists for this branch", or "no commits
    between base and head") it looks up the existing PR so a rerun still surfaces
    a usable link. Auth / permission / network problems degrade to a skip.
    """
    endpoint = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }
    payload = {"title": title, "head": head, "base": base, "body": body}

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        return PullRequestOutcome(
            created=False,
            skipped_reason=f"network error contacting GitHub ({exc.__class__.__name__})",
        )

    if resp.status_code == 201:
        url = (resp.json() or {}).get("html_url")
        logger.info("[RepoInstall] opened pull request %s", url)
        return PullRequestOutcome(created=True, url=url)

    if resp.status_code == 422:
        # Most commonly the PR already exists — find and reuse it.
        existing = _find_existing_pr(
            owner=owner, repo=repo, token=token, head=head, base=base, timeout=timeout
        )
        if existing:
            return PullRequestOutcome(created=False, url=existing)
        return PullRequestOutcome(
            created=False,
            skipped_reason=(
                "GitHub rejected the pull request (422 — it may already exist or "
                "the installation branch has no new commits relative to the base)"
            ),
        )

    if resp.status_code in (401, 403):
        return PullRequestOutcome(
            created=False,
            skipped_reason=(
                "the GitHub token lacks permission to open a pull request "
                "(a token with pull-request / repo scope is required)"
            ),
        )

    return PullRequestOutcome(
        created=False,
        skipped_reason=f"GitHub pull request API returned HTTP {resp.status_code}",
    )


def _find_existing_pr(
    *, owner: str, repo: str, token: str, head: str, base: str, timeout: int
) -> Optional[str]:
    """Best-effort lookup of an open PR for ``head`` → ``base``; None on any issue."""
    endpoint = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    }
    params = {"head": f"{owner}:{head}", "base": base, "state": "open"}
    try:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=timeout)
        if resp.status_code == 200:
            items = resp.json() or []
            if items:
                return items[0].get("html_url")
    except requests.RequestException:
        return None
    return None
