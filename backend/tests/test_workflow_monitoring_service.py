"""Tests for the Workflow Monitoring phase (read-only GitHub Actions observation).

Three layers, none of which touch the network or a real DB:

1. ``GitHubActionsClient`` — error classification (401/403-forbidden/
   403-rate-limited/429/404/network/other) + response parsing, via an injected
   fake HTTP session.
2. ``WorkflowMonitoringService._observe`` / ``build`` — bootstrap/deploy matching,
   run-field mapping, duration, optional current-step, degraded fallbacks, and
   the absolute "monitoring never raises" guarantee, via an injected fake client.
3. ``_current_job_step`` — current job/step derivation from a jobs payload.

Covers the required failure cases: invalid token, missing permissions, repository
/ workflow not found, API failure, and rate limiting — and proves a monitoring
failure NEVER raises (so it can never fail the workflow).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from backend.app.services.core.credentials_service import CredentialsService
from backend.app.services.workflow_monitoring.github_actions_client import (
    GitHubActionsApiError,
    GitHubActionsClient,
)
from backend.app.services.workflow_monitoring.models import compute_duration_seconds
from backend.app.services.workflow_monitoring.monitoring_service import (
    WorkflowMonitoringService,
    _current_job_step,
)

REPO_URL = "https://github.com/acme/widget"


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeResp:
    def __init__(self, status_code=200, json_data=None, headers=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


class FakeSession:
    """A one-response or network-error stand-in for ``requests``."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if self.error:
            raise self.error
        return self.response


class FakeClient:
    """Implements the client surface the service uses (latest_run + run_jobs)."""

    def __init__(self, runs=None, jobs=None, errors=None):
        self.runs = runs or {}
        self.jobs = jobs or []
        self.errors = errors or {}

    def latest_run(self, owner, repo, workflow_file, *, branch=None):
        if workflow_file in self.errors:
            raise self.errors[workflow_file]
        return self.runs.get(workflow_file)

    def run_jobs(self, owner, repo, run_id):
        return self.jobs


class FakeDB:
    """A DB that refuses all access — proves the service degrades/persists
    best-effort WITHOUT a real session (every DB touch is swallowed)."""

    def query(self, *a, **k):
        raise RuntimeError("no database in this unit test")

    def commit(self):
        raise RuntimeError("no database in this unit test")

    def rollback(self):
        pass


def _project(repo_url=REPO_URL):
    return SimpleNamespace(id="proj-1", repository_url=repo_url)


def _workflow(phases_state=None):
    return SimpleNamespace(
        id="wf-1",
        project_id="proj-1",
        current_phase="WORKFLOW_MONITORING",
        status="completed",
        phases_state=phases_state or {"WORKFLOW_MONITORING": {"status": "monitoring"}},
    )


COMPLETED_DEPLOY_RUN = {
    "id": 222,
    "run_number": 5,
    "status": "completed",
    "conclusion": "success",
    "head_branch": "main",
    "head_sha": "a8f2d1cdeadbeef",
    "event": "push",
    "html_url": "https://github.com/acme/widget/actions/runs/222",
    "run_started_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:56Z",
    "triggering_actor": {"login": "octocat"},
}

IN_PROGRESS_BOOTSTRAP_RUN = {
    "id": 111,
    "run_number": 3,
    "status": "in_progress",
    "conclusion": None,
    "head_branch": "multiminds/devops-pipelines",
    "head_sha": "cafebabe1234",
    "event": "workflow_dispatch",
    "html_url": "https://github.com/acme/widget/actions/runs/111",
    "run_started_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:01:00Z",
    "actor": {"login": "octocat"},
}

ACTIVE_JOBS = [
    {
        "name": "terraform",
        "status": "in_progress",
        "steps": [
            {"name": "Checkout", "status": "completed", "conclusion": "success", "number": 1},
            {"name": "terraform apply", "status": "in_progress", "number": 2},
        ],
    }
]


# ── GitHubActionsClient: error classification ────────────────────────────────


@pytest.mark.parametrize(
    "status,headers,kind",
    [
        (401, {}, "invalid_token"),
        (403, {"X-RateLimit-Remaining": "0"}, "rate_limited"),
        (429, {}, "rate_limited"),
        (403, {"X-RateLimit-Remaining": "42"}, "forbidden"),
        (404, {}, "not_found"),
        (500, {}, "api_error"),
    ],
)
def test_client_classifies_http_errors(status, headers, kind):
    session = FakeSession(response=FakeResp(status_code=status, headers=headers))
    client = GitHubActionsClient("tok", session=session)
    with pytest.raises(GitHubActionsApiError) as ei:
        client.latest_run("acme", "widget", "deploy.yml")
    assert ei.value.kind == kind


def test_client_network_error_is_api_error():
    session = FakeSession(error=requests.RequestException("boom"))
    client = GitHubActionsClient("tok", session=session)
    with pytest.raises(GitHubActionsApiError) as ei:
        client.latest_run("acme", "widget", "deploy.yml")
    assert ei.value.kind == "api_error"


def test_client_latest_run_parses_first_run():
    session = FakeSession(
        response=FakeResp(json_data={"workflow_runs": [COMPLETED_DEPLOY_RUN]})
    )
    client = GitHubActionsClient("tok", session=session)
    run = client.latest_run("acme", "widget", "deploy.yml", branch="main")
    assert run["id"] == 222
    # per_page=1 + branch are passed as query params (minimum requests).
    assert session.calls[0]["params"] == {"per_page": 1, "branch": "main"}


def test_client_latest_run_none_when_empty():
    session = FakeSession(response=FakeResp(json_data={"workflow_runs": []}))
    client = GitHubActionsClient("tok", session=session)
    assert client.latest_run("acme", "widget", "deploy.yml") is None


def test_client_only_issues_get_requests():
    # The read-only contract: there is deliberately NO write method on the client.
    for forbidden in ("post", "put", "delete", "patch"):
        assert not hasattr(GitHubActionsClient("tok"), forbidden)


# ── _current_job_step ────────────────────────────────────────────────────────


def test_current_job_step_prefers_in_progress_step():
    assert _current_job_step(ACTIVE_JOBS) == ("terraform", "terraform apply")


def test_current_job_step_none_when_no_active_job():
    jobs = [{"name": "build", "status": "completed", "steps": []}]
    assert _current_job_step(jobs) == (None, None)


def test_current_job_step_falls_back_to_last_started_step():
    jobs = [
        {
            "name": "deploy",
            "status": "in_progress",
            "steps": [
                {"name": "Checkout", "status": "completed", "number": 1},
                {"name": "deploy service", "status": "completed", "number": 2},
                {"name": "Smoke test", "status": "queued", "number": 3},
            ],
        }
    ]
    assert _current_job_step(jobs) == ("deploy", "deploy service")


# ── duration ─────────────────────────────────────────────────────────────────


def test_duration_completed_run_is_exact():
    assert (
        compute_duration_seconds("2024-01-01T00:00:00Z", "2024-01-01T00:00:56Z")
        == 56
    )


def test_duration_none_without_start():
    assert compute_duration_seconds(None, None) is None


# ── WorkflowMonitoringService.build (with injected client) ───────────────────


def test_build_success_maps_both_pipelines(monkeypatch):
    monkeypatch.setattr(
        CredentialsService, "get_credential", staticmethod(lambda *a, **k: "tok")
    )
    client = FakeClient(
        runs={
            "bootstrap.yml": IN_PROGRESS_BOOTSTRAP_RUN,
            "deploy.yml": COMPLETED_DEPLOY_RUN,
        },
        jobs=ACTIVE_JOBS,
    )
    resp = WorkflowMonitoringService.build(
        FakeDB(), project=_project(), workflow=_workflow(), task=None, client=client,
    )

    assert resp.monitoring_available is True
    assert resp.stale is False

    # Infrastructure pipeline = bootstrap.yml (running, with current step).
    infra = resp.infrastructure
    assert infra.kind == "bootstrap"
    assert infra.name == "Infrastructure Pipeline"
    assert infra.status == "in_progress"
    assert infra.current_step == "terraform apply"
    assert infra.branch == "multiminds/devops-pipelines"
    assert infra.html_url.endswith("/runs/111")
    assert infra.workflow_url.endswith("/actions/workflows/bootstrap.yml")

    # Delivery pipeline = deploy.yml (success, 56s).
    deliv = resp.delivery
    assert deliv.kind == "deploy"
    assert deliv.name == "Delivery Pipeline"
    assert deliv.status == "completed"
    assert deliv.conclusion == "success"
    assert deliv.commit_sha == "a8f2d1cdeadbeef"
    assert deliv.actor == "octocat"
    assert deliv.duration_seconds == 56


def test_build_no_runs_is_available_but_not_found(monkeypatch):
    monkeypatch.setattr(
        CredentialsService, "get_credential", staticmethod(lambda *a, **k: "tok")
    )
    # 404 from GitHub = workflow not installed yet / no runs → soft "not found".
    client = FakeClient(
        errors={
            "bootstrap.yml": GitHubActionsApiError("not_found", "nope", status=404),
            "deploy.yml": GitHubActionsApiError("not_found", "nope", status=404),
        }
    )
    resp = WorkflowMonitoringService.build(
        FakeDB(), project=_project(), workflow=_workflow(), task=None, client=client,
    )
    assert resp.monitoring_available is True          # the API was reachable
    assert resp.infrastructure.found is False
    assert resp.infrastructure.available is True
    assert resp.infrastructure.error is None


def test_build_hard_error_degrades(monkeypatch):
    monkeypatch.setattr(
        CredentialsService, "get_credential", staticmethod(lambda *a, **k: "tok")
    )
    err = GitHubActionsApiError("forbidden", "no actions read", status=403)
    client = FakeClient(errors={"bootstrap.yml": err, "deploy.yml": err})
    resp = WorkflowMonitoringService.build(
        FakeDB(), project=_project(), workflow=_workflow(), task=None, client=client,
    )
    assert resp.monitoring_available is False
    assert resp.infrastructure.available is False
    assert "actions read" in (resp.infrastructure.error or "")
    assert resp.error is not None


def test_build_without_repo_url_degrades():
    resp = WorkflowMonitoringService.build(
        FakeDB(), project=_project(repo_url=None), workflow=_workflow(), task=None,
        client=FakeClient(),
    )
    assert resp.monitoring_available is False
    assert "repository URL" in (resp.error or "")
    assert resp.infrastructure.found is False


def test_build_without_token_degrades(monkeypatch):
    monkeypatch.setattr(
        CredentialsService, "get_credential", staticmethod(lambda *a, **k: None)
    )
    resp = WorkflowMonitoringService.build(
        FakeDB(), project=_project(), workflow=_workflow(), task=None,
        client=FakeClient(),
    )
    assert resp.monitoring_available is False
    assert "GitHub token" in (resp.error or "")


def test_build_never_raises_on_unexpected_error(monkeypatch):
    """A non-API exception inside observation must NEVER propagate — monitoring
    can never fail the workflow."""
    monkeypatch.setattr(
        CredentialsService, "get_credential", staticmethod(lambda *a, **k: "tok")
    )

    class ExplodingClient:
        def latest_run(self, *a, **k):
            raise ValueError("unexpected boom")  # not a GitHubActionsApiError

        def run_jobs(self, *a, **k):
            return []

    resp = WorkflowMonitoringService.build(
        FakeDB(), project=_project(), workflow=_workflow(), task=None,
        client=ExplodingClient(),
    )
    assert resp.monitoring_available is False
    assert resp.error is not None
