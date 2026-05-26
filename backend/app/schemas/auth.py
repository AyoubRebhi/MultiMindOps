"""Auth API schemas.

We use ``str`` for email instead of ``pydantic.EmailStr`` so the
backend does not pull in the ``email-validator`` package as a hard
dependency. Format validation happens via a simple regex below — the
real validation gate is the unique-index constraint on ``users.email``.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Pragmatic email regex — RFC-5322 is intentionally not enforced. Anything
# obviously malformed is rejected at the edge; anything that gets past is
# still subject to the unique-email constraint.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _normalize_email(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if not _EMAIL_RE.match(cleaned):
        raise ValueError("Invalid email address")
    return cleaned


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class LogoutRequest(BaseModel):
    # Logout MAY supply the refresh token to revoke the specific session.
    # If omitted, every session for the caller is revoked (whole-account
    # logout). Splitting the two intents into one parameter keeps the API
    # surface tiny.
    refresh_token: Optional[str] = None


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access_token expires


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    auth_provider: str
    email_verified: str
    account_status: str
    last_login_at: Optional[datetime] = None


class AuthSuccessResponse(BaseModel):
    user: UserPublic
    tokens: TokenPairResponse
