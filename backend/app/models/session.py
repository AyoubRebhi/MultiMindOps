"""Refresh-token session row.

One row per refresh token issued. The token itself is never stored —
we store the SHA-256 of its ``jti`` and rely on the JWT signature plus
the row's ``revoked_at`` and ``expires_at`` for validation.

Why a separate table instead of a denylist:
* Logout is O(1): set ``revoked_at`` on the row.
* Concurrent sessions on different devices are first-class (each device
  gets its own row).
* Cleanup is a single ``DELETE WHERE expires_at < now()`` cron.
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.sql import func

from backend.app.database.base import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Hash of the refresh-token ``jti`` claim. Storing a hash (not the jti
    # itself) means a DB leak doesn't hand the attacker live refresh-token
    # IDs that could be replayed against the signing key.
    refresh_token_hash = Column(String, nullable=False, index=True)

    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        # Single-column expires_at index — drives the cleanup sweep.
        Index("ix_user_sessions_expires_at", "expires_at"),
    )


def hash_jti(jti: str) -> str:
    """Return the canonical hash used in ``refresh_token_hash``.

    Centralized so the auth route, the refresh endpoint, and any future
    revoke-all-sessions admin tool all derive the value identically.
    """
    return hashlib.sha256(jti.encode("utf-8")).hexdigest()
