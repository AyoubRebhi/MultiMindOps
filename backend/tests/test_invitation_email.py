"""Tests for the invitation email layer.

Covers, with NO real network access:
* the secure temporary-password generator
* EmailService config resolution (the Gmail "username is a label" case) and the
  smtplib → EmailDeliveryError error mapping (auth / timeout / unavailable)
* the invitation email template rendering + HTML escaping
* invitation_service recording email_status SENT / FAILED / SKIPPED
"""

from __future__ import annotations

import smtplib
import socket
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.password_generator import generate_temporary_password
from backend.app.core.passwords import validate_password_policy
from backend.app.models.invitation import Invitation
from backend.app.models.session import UserSession
from backend.app.models.user import User
from backend.app.models.workspace import Workspace
from backend.app.services.core import email_service as email_mod
from backend.app.services.core import invitation_service as inv_svc
from backend.app.services.core.email_service import (
    EmailConfigError,
    EmailDeliveryError,
    EmailMessageSpec,
    EmailService,
)
from backend.app.services.core.email_templates import render_invitation_email


# ── Password generator ───────────────────────────────────────────────────────

def test_temp_password_is_strong_and_policy_compliant():
    for _ in range(50):
        pw = generate_temporary_password()
        assert len(pw) >= 12
        assert any(c.islower() for c in pw)
        assert any(c.isupper() for c in pw)
        assert any(c.isdigit() for c in pw)
        assert any(not c.isalnum() for c in pw)  # a special character
        # Must satisfy the platform password policy (lower/upper/digit/length).
        validate_password_policy(pw)


def test_temp_password_length_is_clamped_up():
    assert len(generate_temporary_password(4)) >= 12


# ── EmailService config resolution ───────────────────────────────────────────

def _cfg(**over):
    base = dict(
        SMTP_HOST="smtp.gmail.com",
        SMTP_PORT=587,
        SMTP_PASSWORD="app-password",
        SMTP_TIMEOUT_SECONDS=15.0,
        EMAIL_ENABLED=True,
        SMTP_USERNAME="MultiMindOps App",
        EMAIL_FROM="sender@gmail.com",
        EMAIL_FROM_NAME="",
        APP_NAME="DevSecOps AI Platform",
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_login_falls_back_to_email_from_when_username_is_a_label():
    svc = EmailService(_cfg())
    # The Gmail AUTH login must be the address, not the friendly label.
    assert svc._login_username == "sender@gmail.com"
    assert svc.from_address == "sender@gmail.com"
    assert svc._from_name == "MultiMindOps App"  # label used as display name
    assert svc.is_enabled() is True


def test_login_uses_username_when_it_is_an_email():
    svc = EmailService(_cfg(SMTP_USERNAME="real@gmail.com"))
    assert svc._login_username == "real@gmail.com"


def test_disabled_when_incomplete():
    svc = EmailService(_cfg(SMTP_HOST=""))
    assert svc.is_enabled() is False
    assert any("SMTP_HOST" in p for p in svc.config_problems())
    with pytest.raises(EmailConfigError):
        svc.send(EmailMessageSpec(to="x@y.com", subject="s", text_body="t"))


def test_disabled_when_flag_off():
    svc = EmailService(_cfg(EMAIL_ENABLED=False))
    assert svc.is_enabled() is False


# ── EmailService SMTP error mapping (fake smtplib) ───────────────────────────

class _FakeSMTP:
    """Minimal smtplib.SMTP stand-in usable as a context manager."""

    last = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.sent = []
        self.login_args = None
        _FakeSMTP.last = self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        self.sent.append(msg)


def test_send_success(monkeypatch):
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)
    svc = EmailService(_cfg())
    svc.send(EmailMessageSpec(to="dest@example.com", subject="Hi", text_body="hello", html_body="<b>hi</b>"))
    assert _FakeSMTP.last.login_args == ("sender@gmail.com", "app-password")
    assert len(_FakeSMTP.last.sent) == 1


def test_send_maps_auth_error(monkeypatch):
    class _AuthFail(_FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad creds")

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _AuthFail)
    svc = EmailService(_cfg())
    with pytest.raises(EmailDeliveryError) as ei:
        svc.send(EmailMessageSpec(to="dest@example.com", subject="Hi", text_body="x"))
    assert "authentication failed" in str(ei.value).lower()


def test_send_maps_timeout(monkeypatch):
    def _raise_timeout(*a, **k):
        raise socket.timeout("timed out")

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _raise_timeout)
    svc = EmailService(_cfg())
    with pytest.raises(EmailDeliveryError) as ei:
        svc.send(EmailMessageSpec(to="dest@example.com", subject="Hi", text_body="x"))
    assert "timed out" in str(ei.value).lower()


def test_send_maps_connection_error(monkeypatch):
    def _raise_conn(*a, **k):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _raise_conn)
    svc = EmailService(_cfg())
    with pytest.raises(EmailDeliveryError) as ei:
        svc.send(EmailMessageSpec(to="dest@example.com", subject="Hi", text_body="x"))
    assert "could not reach" in str(ei.value).lower()


def test_send_rejects_bad_recipient(monkeypatch):
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)
    svc = EmailService(_cfg())
    with pytest.raises(EmailDeliveryError):
        svc.send(EmailMessageSpec(to="not-an-email", subject="Hi", text_body="x"))


# ── Template rendering ───────────────────────────────────────────────────────

def test_render_invitation_email_contains_all_fields():
    subject, html, text = render_invitation_email(
        workspace_name="Acme DevOps",
        role="DEVOPS_ENGINEER",
        login_email="eng@example.com",
        temp_password="Tmp#Pass99",
        accept_url="http://localhost:5173/invite/abc123",
        invited_by="Admin User",
        message="welcome aboard",
        app_name="DevSecOps AI Platform",
    )
    assert "Acme DevOps" in subject
    for needle in ("Acme DevOps", "DevOps Engineer", "eng@example.com",
                   "Tmp#Pass99", "http://localhost:5173/invite/abc123", "welcome aboard"):
        assert needle in html
        assert needle in text


def test_render_invitation_email_escapes_html():
    _, html, _ = render_invitation_email(
        workspace_name="<script>alert(1)</script>",
        role="DEVOPS_ENGINEER",
        login_email="e@e.com",
        temp_password="Tmp#Pass99",
        accept_url="http://x/invite/t",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ── invitation_service email status tracking ─────────────────────────────────

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    for model in (User, UserSession, Workspace, Invitation):
        model.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _register_admin(db):
    from backend.app.services.core import auth_service
    user, *_ = auth_service.register_user(
        db, email="admin@example.com", password="StrongPass1", display_name="Admin",
    )
    return user


def test_create_invitation_records_sent(db_session, monkeypatch):
    monkeypatch.setattr(inv_svc.email_service, "is_enabled", lambda: True)
    calls = {}

    def _fake_send(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(inv_svc.email_service, "send_invitation_email", _fake_send)
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    assert inv.email_status == "SENT"
    assert inv.email_sent_at is not None
    # The service passed real values (incl. a temp password + accept link).
    assert calls["to_email"] == "eng@example.com"
    assert calls["accept_url"].endswith(f"/invite/{inv.token}")
    assert calls["temp_password"]


def test_create_invitation_records_failed(db_session, monkeypatch):
    monkeypatch.setattr(inv_svc.email_service, "is_enabled", lambda: True)

    def _boom(**kwargs):
        raise EmailDeliveryError("SMTP authentication failed")

    monkeypatch.setattr(inv_svc.email_service, "send_invitation_email", _boom)
    admin = _register_admin(db_session)
    inv = inv_svc.create_invitation(
        db_session, workspace_id=admin.workspace_id, invited_by=admin.id,
        email="eng@example.com",
    )
    # Delivery failed but the invitation + stub account were still created.
    assert inv.email_status == "FAILED"
    assert "authentication failed" in (inv.email_error or "")
    assert inv.status == "pending"
    assert db_session.query(User).filter_by(email="eng@example.com").first() is not None
