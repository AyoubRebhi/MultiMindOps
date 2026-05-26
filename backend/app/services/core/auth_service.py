"""Authentication service.

Pure-logic layer between the auth API and the DB. Routes stay thin —
they translate HTTP into method calls and method results back into
HTTP responses.

All session state lives on ``UserSession`` rows. Logout = set
``revoked_at``. Refresh = look up the row by hashed jti, verify it's
neither revoked nor expired, mint a new access token (and rotate the
refresh row if rotation is on).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.core.auth_errors import unauthorized
from backend.app.core.config import settings
from backend.app.core.jwt import (
    TokenError,
    TokenExpiredError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from backend.app.core.passwords import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
    verify_password,
)
from backend.app.models.session import UserSession, hash_jti
from backend.app.models.user import User

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Auth-service-level failure. Routes map this to HTTP 400/401."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _issue_token_pair(
    db: Session,
    user: User,
    *,
    ip_address: Optional[str],
    user_agent: Optional[str],
) -> tuple[str, str, int]:
    """Mint an access+refresh pair, persist the refresh session row.

    Returns ``(access_token, refresh_token, access_expires_in_seconds)``.
    The refresh-token jti is hashed before being stored — see
    ``models/session.py`` for the why.
    """
    # Create session row first so we can embed its id into the refresh JWT.
    session = UserSession(
        user_id=user.id,
        # Placeholder — overwritten right after we have the jti.
        refresh_token_hash="",
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=_now(),  # overwritten below; placeholder so NOT NULL holds
    )
    db.add(session)
    db.flush()  # populate session.id without committing

    refresh_token, refresh_jti, refresh_exp = create_refresh_token(
        user_id=user.id,
        session_id=session.id,
    )
    session.refresh_token_hash = hash_jti(refresh_jti)
    session.expires_at = refresh_exp
    db.commit()

    access_token, _, access_exp = create_access_token(user_id=user.id)
    expires_in = max(int((access_exp - _now()).total_seconds()), 0)
    return access_token, refresh_token, expires_in


def register_user(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: Optional[str],
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> tuple[User, str, str, int]:
    """Create a user and return an authenticated token pair in one step.

    Email uniqueness is enforced both here (cheap pre-check for a
    friendlier 409) and at the DB level (race-proof).
    """
    try:
        validate_password_policy(password)
    except PasswordPolicyError as exc:
        raise AuthError(str(exc)) from exc

    email_norm = email.strip().lower()
    existing = db.query(User).filter(User.email == email_norm).first()
    if existing is not None:
        raise AuthError("An account with this email already exists")

    user = User(
        email=email_norm,
        display_name=(display_name or "").strip() or None,
        password_hash=hash_password(password),
        auth_provider="local",
        is_active="true",
        account_status="active",
        email_verified="false",
        failed_login_attempts=0,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token, refresh_token, expires_in = _issue_token_pair(
        db, user, ip_address=ip_address, user_agent=user_agent,
    )

    # Record successful first-login timestamp.
    user.last_login_at = _now()
    db.commit()

    return user, access_token, refresh_token, expires_in


def authenticate_user(
    db: Session,
    *,
    email: str,
    password: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> tuple[User, str, str, int]:
    """Verify credentials, increment lockout counter on failure, issue tokens on success.

    Always raises the same error message regardless of whether the
    email was wrong or the password was wrong — leaking that distinction
    enables account enumeration.
    """
    email_norm = (email or "").strip().lower()
    user = db.query(User).filter(User.email == email_norm).first()

    # Constant-shape failure path: even when the user is missing, do a
    # dummy verify so the timing matches the wrong-password path.
    if user is None:
        verify_password(password, "$2b$12$abcdefghijklmnopqrstuv")  # noqa: S106
        raise AuthError("Invalid email or password")

    # Reject locked / disabled accounts BEFORE checking the password so
    # a brute-forcer can't tell the password is correct on a locked acct.
    account_status = (user.account_status or "active").strip().lower()
    if account_status in ("disabled", "locked"):
        raise AuthError(f"Account is {account_status}")
    if not user.is_active_bool:
        raise AuthError("Account is inactive")

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        max_attempts = settings.AUTH_MAX_FAILED_LOGIN_ATTEMPTS
        if max_attempts and user.failed_login_attempts >= max_attempts:
            user.account_status = "locked"
            logger.warning(
                "[auth] Locking account %s after %d failed attempts",
                user.id, user.failed_login_attempts,
            )
        db.commit()
        raise AuthError("Invalid email or password")

    # Success — reset lockout counter, record login.
    user.failed_login_attempts = 0
    user.last_login_at = _now()
    db.commit()

    access_token, refresh_token, expires_in = _issue_token_pair(
        db, user, ip_address=ip_address, user_agent=user_agent,
    )
    return user, access_token, refresh_token, expires_in


def refresh_session(
    db: Session,
    *,
    refresh_token: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> tuple[User, str, str, int]:
    """Validate a refresh token and rotate it for a new pair.

    Rotation means: the old session row is revoked and a new one is
    created. Reusing a refresh token after rotation fails — which is
    the defence against refresh-token replay.
    """
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except TokenExpiredError as exc:
        raise AuthError("Refresh token has expired") from exc
    except TokenError as exc:
        raise AuthError("Invalid refresh token") from exc

    session_id = payload.get("sid")
    user_id = payload.get("sub")
    jti = payload.get("jti")
    if not session_id or not user_id or not jti:
        raise AuthError("Refresh token is malformed")

    session = (
        db.query(UserSession)
        .filter(UserSession.id == session_id, UserSession.user_id == user_id)
        .first()
    )
    if session is None:
        raise AuthError("Session not found")
    if session.revoked_at is not None:
        raise AuthError("Session has been revoked")
    # SQLite returns naive datetimes; Postgres returns tz-aware. Coerce
    # both sides to UTC so the comparison is consistent in either backend.
    now_utc = _now()
    exp = session.expires_at
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp <= now_utc:
        raise AuthError("Session has expired")
    if session.refresh_token_hash != hash_jti(jti):
        # Token jti does not match what we issued for this session —
        # treat as a replay of a rotated token.
        raise AuthError("Refresh token does not match session")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active_bool:
        raise AuthError("Account is not available")
    if (user.account_status or "active").strip().lower() in ("disabled", "locked"):
        raise AuthError(f"Account is {user.account_status}")

    # Rotate — revoke current row, mint a fresh pair on a new session.
    session.revoked_at = _now()
    db.commit()

    access_token, new_refresh, expires_in = _issue_token_pair(
        db, user, ip_address=ip_address, user_agent=user_agent,
    )
    return user, access_token, new_refresh, expires_in


def revoke_session(db: Session, *, user: User, refresh_token: Optional[str]) -> int:
    """Revoke one session (if a refresh token is supplied) or ALL of the
    user's sessions otherwise.

    Returns the number of rows revoked. Idempotent — already-revoked
    rows are not double-counted.
    """
    now = _now()
    if refresh_token:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except TokenError:
            # An invalid refresh token on logout is not an error — we
            # treat logout as best-effort. Anyone presenting a junk
            # token gets the same "you are logged out" response.
            return 0
        sid = payload.get("sid")
        if not sid:
            return 0
        session = (
            db.query(UserSession)
            .filter(UserSession.id == sid, UserSession.user_id == user.id)
            .first()
        )
        if session is None or session.revoked_at is not None:
            return 0
        session.revoked_at = now
        db.commit()
        return 1

    # No refresh token supplied — revoke every live session for the user.
    rows = (
        db.query(UserSession)
        .filter(
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        )
        .all()
    )
    for row in rows:
        row.revoked_at = now
    if rows:
        db.commit()
    return len(rows)
