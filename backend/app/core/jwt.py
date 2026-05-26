"""JWT issuance and validation.

Two token types share the same signing key and algorithm but are
distinguished by the ``type`` claim:

* ``access``  — short-lived (~30m); used as a Bearer token on every
                request. Decoded on every protected endpoint.
* ``refresh`` — longer-lived (~14d); only ever sent to ``/auth/refresh``
                and ``/auth/logout``. Bound to a server-side Session row
                via the ``sid`` claim so the server can revoke it without
                rotating the signing key.

A token whose ``type`` does not match what the caller expected is
rejected — passing a refresh token where an access token is required
(or vice versa) is a hard error, not a silent acceptance.

PyJWT is the only dependency. We DO NOT use ``jose`` because passlib +
PyJWT is the minimal stack and PyJWT's ``decode`` already enforces
``exp``/``iat`` plus issuer matching.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Base class for token decode/verify failures.

    The auth dependency translates these into HTTP 401s with the
    normalized envelope. Subclasses exist so future logic (e.g. silently
    rotate access token on near-expiry) can branch on the cause.
    """


class TokenExpiredError(TokenError):
    """The token's ``exp`` claim is in the past."""


class TokenInvalidError(TokenError):
    """Signature mismatch, malformed payload, wrong type, or wrong issuer."""


def _now() -> datetime:
    # Centralized so tests can monkeypatch a single function instead of
    # juggling datetime.now everywhere.
    return datetime.now(timezone.utc)


def _encode(
    *,
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Encode a JWT and return (token, jti, expires_at).

    ``jti`` is returned separately so callers (the session row writer)
    can persist a hash of it without having to re-decode the token.
    """
    now = _now()
    expires_at = now + expires_delta
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub":  subject,
        "type": token_type,
        "iat":  int(now.timestamp()),
        "exp":  int(expires_at.timestamp()),
        "iss":  settings.JWT_ISSUER,
        "jti":  jti,
    }
    if extra_claims:
        # Reserved claims above always win — extras cannot override sub/type/exp.
        for k, v in extra_claims.items():
            if k not in payload:
                payload[k] = v

    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    # PyJWT < 2 returned bytes; modern versions return str. Normalize to str
    # so callers never have to special-case decode.
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token, jti, expires_at


def create_access_token(
    *,
    user_id: str,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Mint a short-lived access token.

    Returned tuple: ``(token, jti, expires_at)``.
    """
    return _encode(
        subject=user_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims=extra_claims,
    )


def create_refresh_token(
    *,
    user_id: str,
    session_id: str,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Mint a longer-lived refresh token bound to a session row.

    ``session_id`` is embedded as the ``sid`` claim and matched against
    the live session row on every refresh — revoking the row revokes
    the token without rotating the signing key.
    """
    claims = dict(extra_claims or {})
    claims["sid"] = session_id
    return _encode(
        subject=user_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        extra_claims=claims,
    )


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    """Decode & verify a token, enforcing ``type == expected_type``.

    Raises :class:`TokenExpiredError` for an expired token and
    :class:`TokenInvalidError` for everything else (bad signature,
    wrong issuer, wrong type, malformed payload).
    """
    if not token or not isinstance(token, str):
        raise TokenInvalidError("Token is missing or not a string")
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "type"]},
        )
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except InvalidTokenError as exc:
        raise TokenInvalidError(f"Invalid token: {exc}") from exc

    actual_type = payload.get("type")
    if actual_type != expected_type:
        # This is the path that catches "refresh token used as access".
        raise TokenInvalidError(
            f"Token type mismatch: expected '{expected_type}', got '{actual_type}'"
        )
    return payload
