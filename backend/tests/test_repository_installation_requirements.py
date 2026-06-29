"""Tests for the Repository Installation REQUIREMENTS pre-flight (UX-only).

The projection surfaces ``has_repo_url`` / ``has_github_token`` /
``missing_requirements`` so the UI can show the requirements checklist and
disable Install BEFORE the user clicks — turning the install service's
prerequisite 400 ("a GitHub token is required") into an exceptional case.

These tests pin the requirement computation WITHOUT a database by stubbing the
three read helpers the projection calls (artifacts / credentials / task state).
The token check is an EXISTENCE probe — ``has_credential`` never decrypts.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services.core import repository_installation_projection_service as mod
from backend.app.services.core.repository_installation_projection_service import (
    RepositoryInstallationProjectionService,
)
from backend.app.services.repository_installation.models import (
    BOOTSTRAP_PATH,
    DEPLOY_PATH,
)


@pytest.fixture
def stub_reads(monkeypatch):
    """Stub the projection's DB reads; returns a setter for token presence."""
    # Pipelines generated → prerequisites met (so we exercise the cred gate).
    monkeypatch.setattr(
        mod.ArtifactPersistenceService,
        "get_github_actions_files",
        staticmethod(lambda *a, **k: {BOOTSTRAP_PATH: "x", DEPLOY_PATH: "y"}),
    )
    monkeypatch.setattr(
        mod.TaskService, "load_workflow_state", staticmethod(lambda *a, **k: {})
    )

    def set_token(present):
        monkeypatch.setattr(
            mod.CredentialsService,
            "has_credential",
            staticmethod(lambda *a, **k: present),
        )

    return set_token


def _workflow():
    return SimpleNamespace(
        id="wf-1", project_id="proj-1", current_phase="REPOSITORY_INSTALLATION",
        status="running", phases_state={},
    )


def _build(set_token, *, repo_url, token):
    set_token(token)
    project = SimpleNamespace(id="proj-1", repository_url=repo_url)
    return RepositoryInstallationProjectionService.build(
        db=None, project_id="proj-1", workflow=_workflow(), task=None, project=project,
    )


def test_missing_token_is_reported(stub_reads):
    resp = _build(stub_reads, repo_url="https://github.com/acme/widget", token=False)
    assert resp.has_repo_url is True
    assert resp.has_github_token is False
    assert resp.missing_requirements == ["github_token"]
    # Pipelines exist, so the only blocker is the credential.
    assert resp.prerequisites_met is True


def test_all_requirements_met(stub_reads):
    resp = _build(stub_reads, repo_url="https://github.com/acme/widget", token=True)
    assert resp.has_repo_url is True
    assert resp.has_github_token is True
    assert resp.missing_requirements == []


def test_missing_repo_and_token(stub_reads):
    resp = _build(stub_reads, repo_url=None, token=False)
    assert resp.has_repo_url is False
    assert resp.has_github_token is False
    assert resp.missing_requirements == ["repository_url", "github_token"]
