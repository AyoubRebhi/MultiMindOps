"""HTTP tests for the typed project credential routes + settings aggregator.

Boots a FastAPI app with the credentials + projects routers over in-memory
SQLite and an APP_SECRET_KEY so the encryption layer is live. Verifies:

* GitHub/AWS create + rotate + delete via the typed endpoints,
* the encryption invariant (stored payload ≠ plaintext; round-trips),
* NO endpoint ever returns a secret value,
* the settings aggregator reports connected/missing + non-secret AWS metadata,
* project isolation (non-member → 404) and the role gate (DEVELOPER → 403),
* a present-but-invalid token → 401.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.routes.credentials import router as credentials_router
from backend.app.api.routes.projects import router as projects_router
from backend.app.core import encryption, security
from backend.app.models.credentials import ProjectCredential
from backend.app.models.project import Project, ProjectMember
from backend.app.models.user import User

GH_TOKEN = "ghp_superSecretValue7890"
AWS_KEY_ID = "AKIAEXAMPLEKEY2345"
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/SECRETvalue"


@pytest.fixture
def app_secret_key(monkeypatch):
    key = encryption.generate_app_secret_key()
    monkeypatch.setenv("APP_SECRET_KEY", key)
    encryption.get_cipher.cache_clear()
    yield key
    encryption.get_cipher.cache_clear()


@pytest.fixture
def env(app_secret_key):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for model in (User, Project, ProjectMember, ProjectCredential):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    db.add_all([
        User(id="u_owner", email="owner@x.io", display_name="Owner", role="DEVOPS_ENGINEER"),
        User(id="u_arch", email="arch@x.io", display_name="Arch", role="DEVOPS_ENGINEER"),
        User(id="u_dev", email="dev@x.io", display_name="Dev", role="DEVOPS_ENGINEER"),
        User(id="u_out", email="out@x.io", display_name="Out", role="DEVOPS_ENGINEER"),
    ])
    db.add_all([
        Project(id="p1", owner_id="u_owner", name="Alpha", current_status="active"),
        Project(id="p2", owner_id="u_out", name="Beta", current_status="active"),
    ])
    db.add_all([
        ProjectMember(project_id="p1", user_id="u_owner", role="OWNER"),
        ProjectMember(project_id="p1", user_id="u_arch", role="CLOUD_ARCHITECT"),
        ProjectMember(project_id="p1", user_id="u_dev", role="DEVELOPER"),
        ProjectMember(project_id="p2", user_id="u_out", role="OWNER"),
    ])
    db.commit()
    db.close()

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.include_router(credentials_router)
    app.include_router(projects_router)
    app.dependency_overrides[security.get_db] = _override_get_db

    state = {"user_id": "u_owner"}

    def _override_user():
        s = Session()
        try:
            return s.query(User).filter(User.id == state["user_id"]).first()
        finally:
            s.close()

    app.dependency_overrides[security.get_current_user] = _override_user

    client = TestClient(app)
    try:
        yield client, state, Session
    finally:
        client.close()
        engine.dispose()


def _body_text(resp) -> str:
    return json.dumps(resp.json())


# ── GitHub credential ─────────────────────────────────────────────────────


def test_github_create_returns_masked_never_token(env):
    client, _, _ = env
    r = client.post("/api/projects/p1/credentials/github", json={"token": GH_TOKEN, "label": "repo X"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "github_pat"
    # Masked preview shows only the last 4; the full token must NEVER appear.
    assert GH_TOKEN not in _body_text(r)
    assert body["masked_preview"].endswith("7890")
    assert "encrypted_payload" not in body  # ciphertext never serialized


def test_github_rotate_keeps_single_row(env):
    client, _, Session = env
    client.post("/api/projects/p1/credentials/github", json={"token": GH_TOKEN})
    client.post("/api/projects/p1/credentials/github", json={"token": "ghp_rotatedValue4321"})
    s = Session()
    try:
        rows = s.query(ProjectCredential).filter(
            ProjectCredential.project_id == "p1",
            ProjectCredential.provider == "github_pat",
        ).all()
        assert len(rows) == 1
        assert encryption.decrypt_string(rows[0].encrypted_payload) == "ghp_rotatedValue4321"
    finally:
        s.close()


# ── AWS credential ─────────────────────────────────────────────────────────


def test_aws_create_status_hides_secret_and_encrypts(env):
    client, _, Session = env
    r = client.post("/api/projects/p1/credentials/aws", json={
        "access_key_id": AWS_KEY_ID,
        "secret_access_key": AWS_SECRET,
        "region": "eu-west-1",
        "account_name": "prod",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["configured"] is True
    assert body["region"] == "eu-west-1"
    assert body["account_name"] == "prod"
    assert body["access_key_id_last4"] == "2345"
    # Neither secret value may appear anywhere in the response.
    txt = _body_text(r)
    assert AWS_SECRET not in txt
    assert AWS_KEY_ID not in txt

    # Encryption invariant + non-secret label split.
    s = Session()
    try:
        row = s.query(ProjectCredential).filter(
            ProjectCredential.project_id == "p1",
            ProjectCredential.provider == "aws_iam",
        ).first()
        assert AWS_SECRET not in row.encrypted_payload  # not stored in clear
        bundle = json.loads(encryption.decrypt_string(row.encrypted_payload))
        assert bundle["access_key_id"] == AWS_KEY_ID
        assert bundle["secret_access_key"] == AWS_SECRET
        label = json.loads(row.label)
        assert label["region"] == "eu-west-1"
        assert label["account_name"] == "prod"
        assert label["access_key_id_last4"] == "2345"
        assert AWS_SECRET not in (row.label or "")  # secret never in label
    finally:
        s.close()


# ── Settings aggregator ─────────────────────────────────────────────────────


def test_settings_reports_connected_and_missing(env):
    client, _, _ = env
    # Initially both missing.
    r0 = client.get("/api/projects/p1/settings")
    assert r0.status_code == 200, r0.text
    assert r0.json()["credentials"]["github"]["configured"] is False
    assert r0.json()["credentials"]["aws"]["configured"] is False

    client.post("/api/projects/p1/credentials/github", json={"token": GH_TOKEN})
    client.post("/api/projects/p1/credentials/aws", json={
        "access_key_id": AWS_KEY_ID, "secret_access_key": AWS_SECRET,
        "region": "us-east-1", "account_name": "staging",
    })

    r = client.get("/api/projects/p1/settings")
    assert r.status_code == 200, r.text
    creds = r.json()["credentials"]
    assert creds["github"]["configured"] is True
    assert creds["aws"]["configured"] is True
    assert creds["aws"]["region"] == "us-east-1"
    assert creds["aws"]["access_key_id_last4"] == "2345"
    # The settings read must never leak secrets.
    assert AWS_SECRET not in _body_text(r)
    assert GH_TOKEN not in _body_text(r)


def test_settings_update_repository_and_default_branch(env):
    client, _, _ = env
    r = client.put("/api/projects/p1/settings", json={
        "repository_url": "https://github.com/acme/app",
        "default_branch": "develop",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["repository_url"] == "https://github.com/acme/app"
    assert body["default_branch"] == "develop"


def test_delete_credential_flips_status_to_missing(env):
    client, _, _ = env
    client.post("/api/projects/p1/credentials/aws", json={
        "access_key_id": AWS_KEY_ID, "secret_access_key": AWS_SECRET, "region": "eu-west-1",
    })
    d = client.delete("/api/projects/p1/credentials/aws_iam")
    assert d.status_code == 200, d.text
    assert client.get("/api/projects/p1/settings").json()["credentials"]["aws"]["configured"] is False


def test_list_credentials_is_masked(env):
    client, _, _ = env
    client.post("/api/projects/p1/credentials/github", json={"token": GH_TOKEN})
    r = client.get("/api/projects/p1/credentials")
    assert r.status_code == 200, r.text
    txt = _body_text(r)
    assert GH_TOKEN not in txt
    assert "encrypted_payload" not in txt


# ── Authorization: isolation + role gate + auth ─────────────────────────────


def test_developer_cannot_write_credentials(env):
    client, state, _ = env
    state["user_id"] = "u_dev"  # DEVELOPER, below CLOUD_ARCHITECT
    r = client.post("/api/projects/p1/credentials/github", json={"token": GH_TOKEN})
    assert r.status_code == 403, r.text


def test_architect_can_write_credentials(env):
    client, state, _ = env
    state["user_id"] = "u_arch"  # CLOUD_ARCHITECT — approver tier
    r = client.post("/api/projects/p1/credentials/github", json={"token": GH_TOKEN})
    assert r.status_code == 201, r.text


def test_non_member_cannot_read_settings(env):
    client, state, _ = env
    state["user_id"] = "u_out"  # member of p2 only
    r = client.get("/api/projects/p1/settings")
    assert r.status_code == 404, r.text  # existence hidden across projects


def test_cross_project_write_is_blocked(env):
    client, state, _ = env
    state["user_id"] = "u_out"  # not a member of p1
    r = client.post("/api/projects/p1/credentials/aws", json={
        "access_key_id": AWS_KEY_ID, "secret_access_key": AWS_SECRET, "region": "eu-west-1",
    })
    assert r.status_code == 404, r.text


def test_invalid_token_is_401(app_secret_key):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    for model in (User, Project, ProjectMember, ProjectCredential):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.include_router(credentials_router)
    app.dependency_overrides[security.get_db] = _override_get_db  # real auth
    client = TestClient(app)
    try:
        r = client.get(
            "/api/projects/p1/credentials",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert r.status_code == 401, r.text
    finally:
        client.close()
        engine.dispose()
