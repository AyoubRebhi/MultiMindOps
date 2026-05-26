"""Authentication dependency layer.

``get_current_user`` is now a real JWT-validating dependency:

1. Read ``Authorization: Bearer <token>`` (or, in dev fallback mode,
   accept missing header and use the seeded dev user).
2. Decode the token, enforcing ``type == "access"``.
3. Load the user row and reject inactive / disabled / locked accounts.

A "dev fallback" path is preserved behind ``AUTH_ALLOW_DEV_FALLBACK``
so the existing test suite — which constructs requests without a token
header — keeps passing while still exercising the real code path when
a token IS supplied. Production deployments leave the flag at
``False`` so every request must present a real token.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from backend.app.core.auth_errors import unauthorized
from backend.app.core.config import settings
from backend.app.core.jwt import (
    TokenError,
    TokenExpiredError,
    decode_token,
)
from backend.app.database.session import SessionLocal
from backend.app.models.user import User

logger = logging.getLogger(__name__)


DEV_USER_EMAIL = "dev@devsecops-ai.local"
DEV_USER_NAME = "Local Dev"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_dev_user(db: Session) -> User:
    """Create-on-demand the seeded dev user.

    Only used by the AUTH_ALLOW_DEV_FALLBACK path. Real users are
    created through ``/auth/register``.
    """
    user = db.query(User).filter(User.email == DEV_USER_EMAIL).first()
    if user is None:
        user = User(
            email=DEV_USER_EMAIL,
            display_name=DEV_USER_NAME,
            is_active="true",
            auth_provider="dev",
            account_status="active",
            email_verified="true",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """Pull the raw token out of an ``Authorization: Bearer ...`` header.

    Returns None if the header is absent or malformed; the caller
    decides how to react (401 vs dev fallback).
    """
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, token = parts[0].strip(), parts[1].strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _ensure_account_usable(user: User) -> None:
    """Reject inactive / disabled / locked accounts at the dependency layer.

    A 401 (not 403) is used on purpose: the credential they presented
    is valid in shape, but the identity is no longer authenticated as
    far as the system is concerned. Mirrors how OAuth providers reject
    revoked tokens.
    """
    if not user.is_active_bool:
        raise unauthorized("Account is inactive")
    status_value = (user.account_status or "active").strip().lower()
    if status_value in ("disabled", "locked", "pending"):
        raise unauthorized(f"Account is {status_value}")


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency that returns the authenticated user.

    Raises 401 if the token is missing, invalid, or expired, unless
    ``AUTH_ALLOW_DEV_FALLBACK`` is True — in which case a missing token
    falls back to the seeded dev user. A *present but invalid* token
    is always a 401, even in dev mode, so token bugs surface during
    development instead of being silently masked.
    """
    raw_token = _extract_bearer(authorization)

    if raw_token is None:
        if settings.AUTH_ALLOW_DEV_FALLBACK:
            return _ensure_dev_user(db)
        raise unauthorized("Authentication required")

    try:
        payload = decode_token(raw_token, expected_type="access")
    except TokenExpiredError:
        raise unauthorized("Token has expired")
    except TokenError as exc:
        logger.info("[auth] rejected access token: %s", exc)
        raise unauthorized("Invalid authentication token")

    user_id = payload.get("sub")
    if not user_id:
        raise unauthorized("Invalid authentication token")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        # Token signed for a user that no longer exists — treat as 401,
        # not 404, so the caller knows to re-authenticate.
        raise unauthorized("Account no longer exists")

    _ensure_account_usable(user)
    return user


def get_current_user_optional(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Like ``get_current_user`` but returns None instead of raising.

    Useful for routes that adjust behaviour for authenticated callers
    but do not REQUIRE auth — e.g. a future public landing-page count.
    Not used by any route today, exposed for forward use.
    """
    if not _extract_bearer(authorization):
        return None
    try:
        return get_current_user(authorization=authorization, db=db)
    except Exception:
        return None
