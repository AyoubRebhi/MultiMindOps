"""Invitation API schemas.

Three public shapes:

* ``InvitationCreate`` / ``InvitationAccept`` — request bodies.
* ``InvitationAdminView`` — the admin's management list (Invitations page).
* ``InvitationLanding`` — the public, token-scoped view the invitee sees
  before accepting (never leaks anything sensitive — just who invited them,
  the workspace name, role and status).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# Reuse the pragmatic email regex shape used by the auth schemas.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Roles an admin may grant via an invitation. ADMIN is intentionally excluded —
# a workspace has exactly one owner-admin (the registrant); invites create
# engineers. Tighten/loosen here in one place.
_INVITABLE_ROLES = {"DEVOPS_ENGINEER"}


def _normalize_email(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if not _EMAIL_RE.match(cleaned):
        raise ValueError("Invalid email address")
    return cleaned


class InvitationCreate(BaseModel):
    email: str
    role: str = "DEVOPS_ENGINEER"
    message: Optional[str] = Field(default=None, max_length=500)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        role = (v or "DEVOPS_ENGINEER").strip().upper()
        if role not in _INVITABLE_ROLES:
            raise ValueError("Role must be one of: " + ", ".join(sorted(_INVITABLE_ROLES)))
        return role


class InvitationAccept(BaseModel):
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(default=None, max_length=120)


class InvitationAdminView(BaseModel):
    """What the admin's Invitations page lists. Includes the token (so the admin
    can copy the invite link as a fallback) and the email-delivery status so the
    UI can show whether the invitation email actually went out."""

    id: str
    email: str
    role: str
    status: str
    invited_by: Optional[str] = None  # display name / email of the inviter
    message: Optional[str] = None
    token: str
    # Email delivery (Phase 8): PENDING | SENT | FAILED | SKIPPED.
    email_status: str = "PENDING"
    email_error: Optional[str] = None
    email_sent_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None


class InvitationLanding(BaseModel):
    """Public, token-scoped view the invitee sees on the landing page."""

    token: str
    email: str
    role: str
    status: str  # pending | accepted | revoked | expired
    workspace_name: str
    invited_by: Optional[str] = None
    invited_by_email: Optional[str] = None
    message: Optional[str] = None
    expires_at: Optional[datetime] = None
