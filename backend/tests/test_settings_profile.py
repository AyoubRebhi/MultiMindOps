"""HTTP tests for the user self-service settings router.

Boots a minimal FastAPI app with ONLY the settings router over in-memory
SQLite and impersonates a user via a dependency override. Covers the profile
update rules (display name, email re-auth + uniqueness, role is NOT editable)
and the password change delegation, plus a real 401 on a bad token.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.routes.settings import router as settings_router
from backend.app.core import security
from backend.app.core.passwords import hash_password
from backend.app.models.user import User


def _make_engine_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    User.__table__.create(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    db.add_all([
        User(
            id="u1", email="alice@x.io", display_name="Alice",
            role="DEVOPS_ENGINEER", password_hash=hash_password("CurrentPass1"),
            auth_provider="local", is_active="true", account_status="active",
            email_verified="true",
        ),
        User(
            id="u2", email="taken@x.io", display_name="Bob",
            role="ADMIN", password_hash=hash_password("OtherPass1"),
            auth_provider="local", is_active="true", account_status="active",
        ),
    ])
    db.commit()
    db.close()
    return engine, Session


@pytest.fixture
def env():
    engine, Session = _make_engine_session()
    # ONE shared session for the request lifecycle so get_current_user and the
    # handler operate on the same identity map — mirrors production, where
    # get_current_user depends on get_db. (Separate sessions would detach the
    # user object and break db.refresh on mutation.)
    db = Session()

    def _override_get_db():
        yield db  # shared; closed at fixture teardown, not per-request

    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[security.get_db] = _override_get_db

    state = {"user_id": "u1"}

    def _override_user():
        return db.query(User).filter(User.id == state["user_id"]).first()

    app.dependency_overrides[security.get_current_user] = _override_user

    client = TestClient(app)
    try:
        yield client, state, Session
    finally:
        client.close()
        db.close()
        engine.dispose()


# ── Profile read/update ───────────────────────────────────────────────────


def test_get_profile_returns_identity(env):
    client, _, _ = env
    r = client.get("/api/settings/profile")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alice@x.io"
    assert body["display_name"] == "Alice"
    assert body["role"] == "DEVOPS_ENGINEER"


def test_update_display_name_only(env):
    client, _, Session = env
    r = client.put("/api/settings/profile", json={"display_name": "Alice Cooper"})
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Alice Cooper"
    # Email untouched.
    assert r.json()["email"] == "alice@x.io"


def test_email_change_requires_current_password(env):
    client, _, _ = env
    r = client.put("/api/settings/profile", json={"email": "alice2@x.io"})
    assert r.status_code == 400, r.text
    assert "incorrect" in r.json()["detail"].lower()


def test_email_change_with_correct_password_succeeds_and_unverifies(env):
    client, _, Session = env
    r = client.put(
        "/api/settings/profile",
        json={"email": "alice2@x.io", "current_password": "CurrentPass1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alice2@x.io"
    # A changed email must drop verification so a future flow can re-confirm.
    assert body["email_verified"] == "false"


def test_email_change_to_existing_email_conflicts(env):
    client, _, _ = env
    r = client.put(
        "/api/settings/profile",
        json={"email": "taken@x.io", "current_password": "CurrentPass1"},
    )
    assert r.status_code == 409, r.text


def test_role_is_never_editable_via_profile(env):
    """Sending `role` in the body must be ignored (anti privilege-escalation)."""
    client, _, Session = env
    r = client.put(
        "/api/settings/profile",
        json={"display_name": "Alice", "role": "ADMIN"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "DEVOPS_ENGINEER"
    # Confirm at the DB layer too.
    s = Session()
    try:
        assert s.query(User).filter(User.id == "u1").first().role == "DEVOPS_ENGINEER"
    finally:
        s.close()


# ── Password change ─────────────────────────────────────────────────────────


def test_change_password_success(env):
    client, _, _ = env
    r = client.put(
        "/api/settings/password",
        json={"current_password": "CurrentPass1", "new_password": "BrandNew2Pass"},
    )
    assert r.status_code == 200, r.text


def test_change_password_wrong_current_is_400(env):
    client, _, _ = env
    r = client.put(
        "/api/settings/password",
        json={"current_password": "WrongPass9", "new_password": "BrandNew2Pass"},
    )
    assert r.status_code == 400, r.text


def test_change_password_weak_new_is_422(env):
    client, _, _ = env
    # Fails min-length / complexity (no uppercase, too short).
    r = client.put(
        "/api/settings/password",
        json={"current_password": "CurrentPass1", "new_password": "weak"},
    )
    assert r.status_code == 422, r.text


# ── Authentication gate ───────────────────────────────────────────────────


def test_invalid_token_is_401():
    """A present-but-invalid bearer token must 401 (real get_current_user)."""
    engine, Session = _make_engine_session()

    def _override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[security.get_db] = _override_get_db  # only DB; real auth
    client = TestClient(app)
    try:
        r = client.get(
            "/api/settings/profile",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert r.status_code == 401, r.text
    finally:
        client.close()
        engine.dispose()
