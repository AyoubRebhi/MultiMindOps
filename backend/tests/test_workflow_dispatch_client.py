"""FIX 1 — bootstrap.yml workflow_dispatch client.

Verifies the single authenticated POST: success (204), the pre-merge 404 (the
workflow not yet on the default branch), permission errors, and a transport
error — all non-raising, each mapped to a typed WorkflowDispatchOutcome. No
network: ``requests.post`` is monkeypatched.
"""

from __future__ import annotations

import requests

from backend.app.services.repository_installation import workflow_dispatch_client
from backend.app.services.repository_installation.workflow_dispatch_client import (
    dispatch_workflow,
)

OWNER, REPO, TOKEN = "acme", "widget", "ghp_secrettoken123"


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


def _patch_post(monkeypatch, *, capture=None, status_code=204, raise_exc=None):
    def fake_post(url, headers=None, json=None, timeout=None):
        if capture is not None:
            capture["url"] = url
            capture["headers"] = headers
            capture["json"] = json
        if raise_exc is not None:
            raise raise_exc
        return _FakeResponse(status_code)

    monkeypatch.setattr(workflow_dispatch_client.requests, "post", fake_post)


def test_dispatch_success_204(monkeypatch):
    capture: dict = {}
    _patch_post(monkeypatch, capture=capture, status_code=204)

    outcome = dispatch_workflow(
        owner=OWNER, repo=REPO, token=TOKEN,
        workflow_file="bootstrap.yml", ref="multiminds/devops-pipelines",
    )

    assert outcome.dispatched is True
    assert outcome.status_code == 204
    assert outcome.error is None
    # Correct endpoint + ref payload + auth header.
    assert capture["url"].endswith(
        "/repos/acme/widget/actions/workflows/bootstrap.yml/dispatches"
    )
    assert capture["json"] == {"ref": "multiminds/devops-pipelines"}
    assert capture["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_dispatch_404_not_on_default_branch(monkeypatch):
    _patch_post(monkeypatch, status_code=404)

    outcome = dispatch_workflow(
        owner=OWNER, repo=REPO, token=TOKEN,
        workflow_file="bootstrap.yml", ref="feature/x",
    )

    assert outcome.dispatched is False
    assert outcome.status_code == 404
    assert "default branch" in (outcome.error or "")


def test_dispatch_permission_error(monkeypatch):
    _patch_post(monkeypatch, status_code=403)

    outcome = dispatch_workflow(
        owner=OWNER, repo=REPO, token=TOKEN,
        workflow_file="bootstrap.yml", ref="main",
    )

    assert outcome.dispatched is False
    assert outcome.status_code == 403
    assert "permission" in (outcome.error or "")


def test_dispatch_network_error_is_non_fatal(monkeypatch):
    _patch_post(monkeypatch, raise_exc=requests.RequestException("boom"))

    outcome = dispatch_workflow(
        owner=OWNER, repo=REPO, token=TOKEN,
        workflow_file="bootstrap.yml", ref="main",
    )

    assert outcome.dispatched is False
    assert outcome.run_id is None
    assert "network error" in (outcome.error or "")


def test_outcome_to_record_shape(monkeypatch):
    _patch_post(monkeypatch, status_code=204)
    outcome = dispatch_workflow(
        owner=OWNER, repo=REPO, token=TOKEN,
        workflow_file="bootstrap.yml", ref="main",
    )
    record = outcome.to_record(ref="main", workflow_file="bootstrap.yml")
    assert record == {
        "dispatched": True,
        "run_id": None,
        "ref": "main",
        "workflow_file": "bootstrap.yml",
        "status_code": 204,
        "error": None,
    }
