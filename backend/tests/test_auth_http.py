"""HTTP-level tests for the auth + invitation surface.

Boots a minimal FastAPI app with ONLY the auth and invitation routers and a
SQLite-backed get_db override (the full app uses Postgres-only JSONB types).
This exercises the real request/response contract the frontend depends on:
status codes, the token-auth dependency, the admin role gate, and the public
invitation routes — end to end through HTTP.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.routes.auth import router as auth_router
from backend.app.api.routes.invitations import router as invitations_router
from backend.app.core import security
from backend.app.models.invitation import Invitation
from backend.app.models.session import UserSession
from backend.app.models.user import User
from backend.app.models.workspace import Workspace

GOOD_PW = "StrongPass1"


@pytest.fixture(autouse=True)
def _no_outbound_email(monkeypatch):
    """Force the email layer 'disabled' so invitation creation never hits the
    network (records email_status='SKIPPED')."""
    from backend.app.services.core import invitation_service
    monkeypatch.setattr(invitation_service.email_service, "is_enabled", lambda: False)


@pytest.fixture
def client():
    # One shared in-memory connection so every get_db() session sees the same DB.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (User, UserSession, Workspace, Invitation):
        model.__table__.create(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(invitations_router)
    app.dependency_overrides[security.get_db] = _override_get_db

    with TestClient(app) as c:
        yield c
    engine.dispose()


def _register(client, email="admin@example.com"):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": GOOD_PW, "display_name": "Admin User"},
    )


# ── Register / me / login ───────────────────────────────────────────────────

def test_register_returns_admin_with_workspace_and_tokens(client):
    r = _register(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["role"] == "ADMIN"
    assert body["user"]["workspace"]["name"]
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]


def test_register_duplicate_email_conflicts(client):
    _register(client)
    r = _register(client)
    assert r.status_code == 409


def test_register_weak_password_422(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "weak@example.com", "password": "weak", "display_name": "X"},
    )
    assert r.status_code == 422


def test_me_requires_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "UNAUTHORIZED"


def test_me_returns_current_user_with_token(client):
    tokens = _register(client).json()["tokens"]
    r = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "ADMIN"
    assert r.json()["workspace"]["name"]


def test_login_wrong_password_401(client):
    _register(client)
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "WrongPass1"},
    )
    assert r.status_code == 401


# ── Invitation flow over HTTP ───────────────────────────────────────────────

def _admin_token(client):
    return _register(client).json()["tokens"]["access_token"]


def test_invite_requires_admin_auth(client):
    # No token at all → 401.
    r = client.post("/api/invitations", json={"email": "eng@example.com"})
    assert r.status_code == 401


def test_full_invite_accept_journey(client):
    admin_token = _admin_token(client)
    auth = {"Authorization": f"Bearer {admin_token}"}

    # Admin creates an invitation.
    r = client.post(
        "/api/invitations",
        json={"email": "eng@example.com", "role": "DEVOPS_ENGINEER", "message": "welcome"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["status"] == "pending"
    token = inv["token"]

    # Admin lists invitations.
    r = client.get("/api/invitations", headers=auth)
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Public landing lookup (no auth).
    r = client.get(f"/api/invitations/{token}")
    assert r.status_code == 200
    landing = r.json()
    assert landing["email"] == "eng@example.com"
    assert landing["workspace_name"]
    assert landing["invited_by_email"] == "admin@example.com"

    # Public accept (no auth) → creates the engineer account.
    r = client.post(
        f"/api/invitations/{token}/accept",
        json={"password": GOOD_PW, "display_name": "Eng One"},
    )
    assert r.status_code == 201, r.text
    accepted = r.json()
    assert accepted["user"]["role"] == "DEVOPS_ENGINEER"
    assert accepted["user"]["workspace"]["name"] == landing["workspace_name"]

    # Engineer can now log in.
    r = client.post(
        "/api/auth/login",
        json={"email": "eng@example.com", "password": GOOD_PW},
    )
    assert r.status_code == 200
    eng_token = r.json()["tokens"]["access_token"]

    # Engineer is NOT an admin → cannot create invitations (403 FORBIDDEN).
    r = client.post(
        "/api/invitations",
        json={"email": "other@example.com"},
        headers={"Authorization": f"Bearer {eng_token}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "FORBIDDEN"

    # Re-accepting the now-accepted invitation → 409.
    r = client.post(
        f"/api/invitations/{token}/accept",
        json={"password": GOOD_PW},
    )
    assert r.status_code == 409


def test_landing_unknown_token_404(client):
    r = client.get("/api/invitations/does-not-exist")
    assert r.status_code == 404


# ── Temp-password login + forced password change (Phase 7) ──────────────────

def test_invited_engineer_temp_password_login_then_forced_change(client, monkeypatch):
    # Pin the generated temporary password so the test can log in with it.
    from backend.app.services.core import invitation_service
    temp_pw = "TempPass123!"
    monkeypatch.setattr(
        invitation_service, "generate_temporary_password", lambda *a, **k: temp_pw
    )

    admin_token = _admin_token(client)
    auth = {"Authorization": f"Bearer {admin_token}"}
    r = client.post(
        "/api/invitations",
        json={"email": "eng@example.com", "role": "DEVOPS_ENGINEER"},
        headers=auth,
    )
    assert r.status_code == 201, r.text

    # The engineer logs in with the emailed temporary password.
    r = client.post(
        "/api/auth/login",
        json={"email": "eng@example.com", "password": temp_pw},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["must_change_password"] == "true"
    eng_token = body["tokens"]["access_token"]
    eng_auth = {"Authorization": f"Bearer {eng_token}"}

    # /me reflects the forced-change requirement.
    r = client.get("/api/auth/me", headers=eng_auth)
    assert r.json()["must_change_password"] == "true"

    # Wrong current password → 400.
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "WrongOne1", "new_password": "BrandNew1"},
        headers=eng_auth,
    )
    assert r.status_code == 400

    # Correct change → flag cleared.
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": temp_pw, "new_password": "BrandNew1"},
        headers=eng_auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] == "false"

    # The temp password no longer works; the new one does.
    r = client.post("/api/auth/login", json={"email": "eng@example.com", "password": temp_pw})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "eng@example.com", "password": "BrandNew1"})
    assert r.status_code == 200

    # The admin's invitation is now marked accepted (forced-change path).
    r = client.get("/api/invitations", headers=auth)
    assert r.json()[0]["status"] == "accepted"


def test_change_password_requires_auth(client):
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "x", "new_password": "BrandNew1"},
    )
    assert r.status_code == 401
