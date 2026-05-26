"""JWT issuance + decoding tests.

We exercise the public surface of ``backend.app.core.jwt``:
* round-trip an access token,
* round-trip a refresh token,
* reject type-mismatch (refresh-as-access),
* reject expired tokens,
* reject signature-tampered tokens,
* reject wrong-issuer tokens.
"""

from __future__ import annotations

from datetime import timedelta

import jwt as pyjwt
import pytest

from backend.app.core import jwt as jwt_module
from backend.app.core.config import settings
from backend.app.core.jwt import (
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    create_refresh_token,
    decode_token,
)


def test_access_token_round_trip():
    token, jti, _ = create_access_token(user_id="u-123")
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "u-123"
    assert payload["type"] == "access"
    assert payload["jti"] == jti
    assert payload["iss"] == settings.JWT_ISSUER


def test_refresh_token_round_trip():
    token, jti, _ = create_refresh_token(user_id="u-1", session_id="sess-1")
    payload = decode_token(token, expected_type="refresh")
    assert payload["sid"] == "sess-1"
    assert payload["type"] == "refresh"
    assert payload["jti"] == jti


def test_token_type_mismatch_is_rejected():
    """A refresh token must not be accepted where an access token is expected.

    This is the single most common application-level mistake JWT auth makes,
    so we test it explicitly.
    """
    refresh, _, _ = create_refresh_token(user_id="u-1", session_id="s-1")
    with pytest.raises(TokenInvalidError):
        decode_token(refresh, expected_type="access")


def test_expired_token_raises_expired_error(monkeypatch):
    # Negative expiry → token is already expired the moment it's issued.
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    token, _, _ = create_access_token(user_id="u-1")
    with pytest.raises(TokenExpiredError):
        decode_token(token, expected_type="access")


def test_tampered_signature_is_rejected():
    token, _, _ = create_access_token(user_id="u-1")
    # Flip a character in the signature segment.
    head, payload, sig = token.split(".")
    bad_sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    bad_token = f"{head}.{payload}.{bad_sig}"
    with pytest.raises(TokenInvalidError):
        decode_token(bad_token, expected_type="access")


def test_wrong_issuer_is_rejected():
    """A token signed for a different ``iss`` must not be accepted."""
    payload = {
        "sub":  "u-1",
        "type": "access",
        "iat":  0,
        "exp":  2_000_000_000,  # far future
        "iss":  "not-our-issuer",
        "jti":  "x",
    }
    foreign = pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    if isinstance(foreign, bytes):
        foreign = foreign.decode("utf-8")
    with pytest.raises(TokenInvalidError):
        decode_token(foreign, expected_type="access")


def test_empty_token_is_rejected():
    with pytest.raises(TokenInvalidError):
        decode_token("", expected_type="access")
    with pytest.raises(TokenInvalidError):
        decode_token(None, expected_type="access")  # type: ignore[arg-type]
