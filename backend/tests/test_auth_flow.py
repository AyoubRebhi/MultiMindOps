"""End-to-end auth service tests against an in-memory SQLite database.

We test the AuthService at the service layer (not the HTTP layer) so the
test does not depend on the rest of the FastAPI app booting cleanly. The
HTTP routes are thin translators over these methods.

Covered flows:
* register → returns user + token pair
* login OK / bad password / unknown email
* lockout after N failed attempts
* refresh rotates the token and revokes the old session
* refresh rejects a replayed (already-rotated) token
* logout revokes a specific session, then prevents reuse
* logout with no token revokes ALL sessions
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import settings
from backend.app.core.jwt import decode_token
from backend.app.models.session import UserSession, hash_jti
from backend.app.models.user import User
from backend.app.models.workspace import Workspace
from backend.app.services.core import auth_service


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    """Fresh in-memory SQLite per test — User + UserSession tables only.

    We DO NOT call ``Base.metadata.create_all`` because some sibling
    models use Postgres-only types (JSONB) that SQLite cannot render.
    The auth flow touches users, user_sessions and (since the workspace
    layer) workspaces — register auto-provisions a Workspace — so we create
    just those.
    """
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    UserSession.__table__.create(engine)
    Workspace.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


# ── Register / login ────────────────────────────────────────────────────────

def test_register_creates_user_and_issues_tokens(db_session):
    user, access, refresh, expires_in = auth_service.register_user(
        db_session,
        email="alice@example.com",
        password="StrongPass1",
        display_name="Alice",
    )
    assert user.email == "alice@example.com"
    assert user.password_hash and user.password_hash != "StrongPass1"
    assert access and refresh
    assert expires_in > 0
    # One live session was created for the new user
    rows = db_session.query(UserSession).filter_by(user_id=user.id).all()
    assert len(rows) == 1
    assert rows[0].revoked_at is None


def test_register_rejects_duplicate_email(db_session):
    auth_service.register_user(
        db_session,
        email="dup@example.com",
        password="StrongPass1",
        display_name=None,
    )
    with pytest.raises(auth_service.AuthError):
        auth_service.register_user(
            db_session,
            email="dup@example.com",
            password="StrongPass1",
            display_name=None,
        )


def test_register_rejects_weak_password(db_session):
    with pytest.raises(auth_service.AuthError):
        auth_service.register_user(
            db_session,
            email="weak@example.com",
            password="short",
            display_name=None,
        )


def test_login_with_correct_credentials_returns_pair(db_session):
    auth_service.register_user(
        db_session, email="bob@example.com",
        password="StrongPass1", display_name=None,
    )
    user, access, refresh, expires_in = auth_service.authenticate_user(
        db_session, email="bob@example.com", password="StrongPass1",
    )
    assert user.email == "bob@example.com"
    # access token should decode + match user
    payload = decode_token(access, expected_type="access")
    assert payload["sub"] == user.id


def test_login_with_wrong_password_fails(db_session):
    auth_service.register_user(
        db_session, email="c@example.com",
        password="StrongPass1", display_name=None,
    )
    with pytest.raises(auth_service.AuthError):
        auth_service.authenticate_user(
            db_session, email="c@example.com", password="WrongPass1",
        )


def test_login_with_unknown_email_fails(db_session):
    with pytest.raises(auth_service.AuthError):
        auth_service.authenticate_user(
            db_session, email="ghost@example.com", password="StrongPass1",
        )


def test_failed_logins_lock_account_after_threshold(db_session, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_MAX_FAILED_LOGIN_ATTEMPTS", 3)
    auth_service.register_user(
        db_session, email="d@example.com",
        password="StrongPass1", display_name=None,
    )
    for _ in range(3):
        with pytest.raises(auth_service.AuthError):
            auth_service.authenticate_user(
                db_session, email="d@example.com", password="WrongPass1",
            )
    # Now the account is locked — correct password still fails.
    user = db_session.query(User).filter_by(email="d@example.com").first()
    assert user.account_status == "locked"
    with pytest.raises(auth_service.AuthError):
        auth_service.authenticate_user(
            db_session, email="d@example.com", password="StrongPass1",
        )


# ── Refresh flow ────────────────────────────────────────────────────────────

def test_refresh_rotates_token_and_revokes_previous(db_session):
    user, _, refresh1, _ = auth_service.register_user(
        db_session, email="r@example.com",
        password="StrongPass1", display_name=None,
    )
    user2, access2, refresh2, _ = auth_service.refresh_session(
        db_session, refresh_token=refresh1,
    )
    assert user2.id == user.id
    assert refresh2 != refresh1

    # Two session rows: old one revoked, new one live.
    rows = db_session.query(UserSession).filter_by(user_id=user.id).order_by(UserSession.created_at).all()
    assert len(rows) == 2
    assert rows[0].revoked_at is not None  # old session revoked
    assert rows[1].revoked_at is None      # new session live

    # Replaying the OLD refresh token must fail.
    with pytest.raises(auth_service.AuthError):
        auth_service.refresh_session(db_session, refresh_token=refresh1)


def test_refresh_rejects_invalid_token(db_session):
    with pytest.raises(auth_service.AuthError):
        auth_service.refresh_session(db_session, refresh_token="not.a.jwt")


# ── Logout ──────────────────────────────────────────────────────────────────

def test_logout_revokes_specific_session(db_session):
    user, _, refresh1, _ = auth_service.register_user(
        db_session, email="l@example.com",
        password="StrongPass1", display_name=None,
    )
    revoked = auth_service.revoke_session(
        db_session, user=user, refresh_token=refresh1,
    )
    assert revoked == 1
    # Refresh must now fail for the revoked session.
    with pytest.raises(auth_service.AuthError):
        auth_service.refresh_session(db_session, refresh_token=refresh1)


def test_logout_without_token_revokes_all_user_sessions(db_session):
    # Two logins → two live sessions for the same user.
    auth_service.register_user(
        db_session, email="m@example.com",
        password="StrongPass1", display_name=None,
    )
    auth_service.authenticate_user(
        db_session, email="m@example.com", password="StrongPass1",
    )
    user = db_session.query(User).filter_by(email="m@example.com").first()
    live = (
        db_session.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .count()
    )
    assert live == 2
    revoked = auth_service.revoke_session(db_session, user=user, refresh_token=None)
    assert revoked == 2
    still_live = (
        db_session.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .count()
    )
    assert still_live == 0


def test_logout_with_junk_token_is_idempotent(db_session):
    user, _, _, _ = auth_service.register_user(
        db_session, email="j@example.com",
        password="StrongPass1", display_name=None,
    )
    # A junk refresh token must not raise — logout is best-effort.
    revoked = auth_service.revoke_session(
        db_session, user=user, refresh_token="garbage.token.value",
    )
    assert revoked == 0
