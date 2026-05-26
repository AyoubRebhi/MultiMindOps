"""Direct tests for the get_current_user dependency.

We call it as a plain function (not through FastAPI) so we can assert
on the failure shape. Each test patches the DB call and toggles
``AUTH_ALLOW_DEV_FALLBACK`` as needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.app.core import security
from backend.app.core.config import settings
from backend.app.core.jwt import create_access_token, create_refresh_token


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *_, **__):
        return self

    def first(self):
        return self._result


class _FakeDB:
    def __init__(self, user):
        self._user = user

    def query(self, _model):
        return _FakeQuery(self._user)


def _make_user(*, user_id="u-1", account_status="active", is_active="true"):
    user = MagicMock()
    user.id = user_id
    user.account_status = account_status
    user.is_active = is_active
    # Mirror the real model's property.
    user.is_active_bool = is_active.lower() in ("true", "1", "yes", "active")
    return user


def test_get_current_user_missing_header_raises_401(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOW_DEV_FALLBACK", False)
    db = _FakeDB(user=None)
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(authorization=None, db=db)
    assert exc.value.status_code == 401
    # Normalized envelope shape
    assert exc.value.detail["code"] == "UNAUTHORIZED"


def test_get_current_user_with_valid_token_returns_user(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOW_DEV_FALLBACK", False)
    user = _make_user(user_id="u-42")
    db = _FakeDB(user=user)
    token, _, _ = create_access_token(user_id="u-42")
    result = security.get_current_user(authorization=f"Bearer {token}", db=db)
    assert result is user


def test_get_current_user_with_refresh_token_is_rejected(monkeypatch):
    """Refresh tokens must never be accepted on the access-token path."""
    monkeypatch.setattr(settings, "AUTH_ALLOW_DEV_FALLBACK", False)
    db = _FakeDB(user=_make_user())
    refresh, _, _ = create_refresh_token(user_id="u-1", session_id="s-1")
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(authorization=f"Bearer {refresh}", db=db)
    assert exc.value.status_code == 401


def test_get_current_user_with_disabled_account_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOW_DEV_FALLBACK", False)
    user = _make_user(account_status="disabled")
    db = _FakeDB(user=user)
    token, _, _ = create_access_token(user_id="u-1")
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(authorization=f"Bearer {token}", db=db)
    assert exc.value.status_code == 401


def test_get_current_user_with_inactive_account_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOW_DEV_FALLBACK", False)
    user = _make_user(is_active="false")
    db = _FakeDB(user=user)
    token, _, _ = create_access_token(user_id="u-1")
    with pytest.raises(HTTPException) as exc:
        security.get_current_user(authorization=f"Bearer {token}", db=db)
    assert exc.value.status_code == 401


def test_malformed_authorization_header_is_treated_as_missing(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOW_DEV_FALLBACK", False)
    db = _FakeDB(user=None)
    with pytest.raises(HTTPException):
        security.get_current_user(authorization="NotBearer something", db=db)
    with pytest.raises(HTTPException):
        security.get_current_user(authorization="Bearer", db=db)
