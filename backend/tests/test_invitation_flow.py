"""End-to-end tests for the workspace/role + invitation layer.

Service-layer tests against in-memory SQLite (same approach as
test_auth_flow.py — only the tables these flows touch are created, since
sibling models use Postgres-only JSONB types).

Covered:
* register → ADMIN role + auto-provisioned workspace + serialize_user shape
* create invitation → pending row scoped to the admin's workspace
* duplicate-email invite → conflict
* landing lookup → public view with workspace + inviter
* accept → DEVOPS_ENGINEER account in the same workspace; invite marked accepted
* accept twice → conflict
* expired invite → cannot be accepted
* revoke → status flips, cannot be accepted
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models.invitation import Invitation
from backend.app.models.session import UserSession
from backend.app.models.user import User
from backend.app.models.workspace import Workspace
from backend.app.services.core import auth_service
from backend.app.services.core import invitation_service as inv_svc


@pytest.fixture(autouse=True)
def _no_outbound_email(monkeypatch):
    """Never hit the network in unit tests: force the email layer 'disabled' so
    invitation creation records email_status='SKIPPED' instead of sending."""
    from backend.app.services.core import invitation_service
    monkeypatch.setattr(invitation_service.email_service, "is_enabled", lambda: False)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    User.__table__.create(engine)
    UserSession.__table__.create(engine)
    Workspace.__table__.create(engine)
    Invitation.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _register_admin(db, email="admin@example.com"):
    user, *_ = auth_service.register_user(
        db, email=email, password="StrongPass1", display_name="Admin User",
    )
    return user


# ── Register → admin + workspace ────────────────────────────────────────────

def test_register_makes_admin_with_workspace(db_session):
    user = _register_admin(db_session)
    assert user.role == "ADMIN"
    assert user.workspace_id
    ws = db_session.query(Workspace).filter_by(id=user.workspace_id).first()
    assert ws is not None
    assert ws.owner_id == user.id
    assert "Admin User" in ws.name


def test_serialize_user_includes_role_and_workspace(db_session):
    user = _register_admin(db_session, email="ser@example.com")
    data = auth_service.serialize_user(db_session, user)
    assert data["role"] == "ADMIN"
    assert data["workspace"]["id"] == user.workspace_id
    assert data["workspace"]["name"]


# ── Invitation create / landing ─────────────────────────────────────────────

def test_create_invitation_pending_in_workspace(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com", role="DEVOPS_ENGINEER", message="welcome",
    )
    assert inv.status == "pending"
    assert inv.workspace_id == admin.workspace_id
    assert inv.token


def test_create_invitation_rejects_existing_user(db_session):
    admin = _register_admin(db_session)
    with pytest.raises(inv_svc.InvitationConflict):
        inv_svc.create_invitation(
            db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
            email=admin.email,
        )


def test_create_invitation_reuses_pending_row(db_session):
    admin = _register_admin(db_session)
    a = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    b = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com", message="again",
    )
    assert a.id == b.id  # same row refreshed, not duplicated
    rows = db_session.query(Invitation).filter_by(email="eng@example.com").count()
    assert rows == 1


def test_landing_exposes_public_view(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    landing = inv_svc.get_landing(db_session, token=inv.token)
    assert landing["email"] == "eng@example.com"
    assert landing["status"] == "pending"
    assert landing["workspace_name"]
    assert landing["invited_by_email"] == admin.email


def test_landing_unknown_token_raises(db_session):
    with pytest.raises(inv_svc.InvitationNotFound):
        inv_svc.get_landing(db_session, token="nope")


# ── Accept ──────────────────────────────────────────────────────────────────

def test_accept_creates_engineer_in_same_workspace(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    user, access, refresh, expires_in = inv_svc.accept_invitation(
        db_session, token=inv.token, password="StrongPass1", display_name="Eng",
    )
    assert user.role == "DEVOPS_ENGINEER"
    assert user.workspace_id == admin.workspace_id
    assert access and refresh and expires_in > 0
    refreshed = db_session.query(Invitation).filter_by(id=inv.id).first()
    assert refreshed.status == "accepted"
    assert refreshed.accepted_at is not None
    # The new engineer can now authenticate with the chosen password.
    authed, *_ = auth_service.authenticate_user(
        db_session, email="eng@example.com", password="StrongPass1",
    )
    assert authed.id == user.id


def test_accept_twice_conflicts(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    inv_svc.accept_invitation(db_session, token=inv.token, password="StrongPass1")
    with pytest.raises(inv_svc.InvitationConflict):
        inv_svc.accept_invitation(db_session, token=inv.token, password="StrongPass1")


def test_accept_expired_conflicts(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    # Force expiry into the past.
    inv.expires_at = inv.expires_at - timedelta(days=30)
    db_session.commit()
    assert inv_svc.effective_status(inv) == "expired"
    with pytest.raises(inv_svc.InvitationConflict):
        inv_svc.accept_invitation(db_session, token=inv.token, password="StrongPass1")


def test_accept_weak_password_rejected(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    with pytest.raises(inv_svc.InvitationError):
        inv_svc.accept_invitation(db_session, token=inv.token, password="weak")


# ── Revoke / resend ─────────────────────────────────────────────────────────

def test_revoke_blocks_accept(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    inv_svc.revoke_invitation(db_session, invitation_id=inv.id, workspace_id=admin.workspace_id)
    refreshed = db_session.query(Invitation).filter_by(id=inv.id).first()
    assert refreshed.status == "revoked"
    with pytest.raises(inv_svc.InvitationConflict):
        inv_svc.accept_invitation(db_session, token=inv.token, password="StrongPass1")


def test_resend_refreshes_window(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    inv.expires_at = inv.expires_at - timedelta(days=30)
    db_session.commit()
    inv_svc.resend_invitation(db_session, invitation_id=inv.id, workspace_id=admin.workspace_id)
    refreshed = db_session.query(Invitation).filter_by(id=inv.id).first()
    assert inv_svc.effective_status(refreshed) == "pending"


# ── Account-at-invite (temp password + must_change_password) ─────────────────

def test_create_provisions_stub_user_with_temp_password(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    # Email is force-disabled in tests → recorded as SKIPPED, not FAILED.
    assert inv.email_status == "SKIPPED"
    # A stub account exists immediately, in the must-change-password state.
    stub = db_session.query(User).filter_by(email="eng@example.com").first()
    assert stub is not None
    assert stub.role == "DEVOPS_ENGINEER"
    assert stub.workspace_id == admin.workspace_id
    assert stub.must_change_password_bool is True
    assert stub.password_hash  # a temp password was hashed + stored


def test_accept_clears_force_change_flag(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    user, *_ = inv_svc.accept_invitation(
        db_session, token=inv.token, password="StrongPass1", display_name="Eng",
    )
    assert user.must_change_password_bool is False


def test_change_password_clears_flag_and_accepts_invitation(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    stub = db_session.query(User).filter_by(email="eng@example.com").first()
    # Simulate the temp-password login path: the engineer changes their password
    # with the (known, since we monkeypatch nothing) temp hash — use the service
    # directly by setting a known temp password first.
    stub.password_hash = auth_service.hash_password("TempPass123!")
    db_session.commit()

    updated = auth_service.change_password(
        db_session, user=stub,
        current_password="TempPass123!", new_password="BrandNew1",
    )
    assert updated.must_change_password_bool is False
    refreshed_inv = db_session.query(Invitation).filter_by(id=inv.id).first()
    assert refreshed_inv.status == "accepted"  # forced change marks it accepted


def test_reinvite_after_revoke_succeeds(db_session):
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    inv_svc.revoke_invitation(db_session, invitation_id=inv.id, workspace_id=admin.workspace_id)
    # The leftover stub is still un-activated → re-inviting must succeed (a new
    # pending invitation), not raise "user already exists".
    inv2 = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    assert inv2.status == "pending"
    assert inv2.id != inv.id
