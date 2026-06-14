"""Workspace invitation.

An Admin invites an engineer by email; a single-use ``token`` is minted and
embedded in the invitation link. The invitee opens the link (public lookup by
token), sets a password, and an account is created in the inviting workspace
with the invitation's role. Lifecycle: pending → accepted | revoked | expired.

The token is stored in the clear here (unlike refresh-token jti hashing) because
an invitation grants no access on its own — accepting it still requires the
invitee to choose a password, and the token is short-lived + single-use.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.sql import func

from backend.app.database.base import Base


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(
        String,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = Column(String, nullable=False, index=True)
    # Global role granted on acceptance. Mirrors User.role values.
    role = Column(String, nullable=False, default="DEVOPS_ENGINEER")
    # pending | accepted | revoked | expired
    status = Column(String, nullable=False, default="pending")
    # Single-use opaque token carried in the invitation link.
    token = Column(String, nullable=False, unique=True, index=True)
    # Who sent it (nullable so a deleted admin doesn't cascade-delete history).
    invited_by = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    message = Column(Text, nullable=True)

    # ── Email delivery tracking (Phase 8) ────────────────────────────────────
    # Lifecycle of the invitation email: PENDING (not yet attempted) | SENT |
    # FAILED | SKIPPED (email disabled). ``email_error`` holds the last failure
    # reason so the admin UI can show why delivery did not succeed.
    email_status = Column(String, nullable=False, default="PENDING")
    email_error = Column(Text, nullable=True)
    email_sent_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
