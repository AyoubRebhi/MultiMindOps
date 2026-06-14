"""Workspace — the org-level tenant that owns members, invitations and projects.

A workspace is auto-provisioned when an Admin self-registers (see
``auth_service.register_user``). Invited engineers join the inviter's
workspace rather than creating their own. This is the minimal "organization"
concept the frontend needs (navbar workspace name, invitation scoping); it is
deliberately thin and does not replace the project-centric authorization model.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.sql import func

from backend.app.database.base import Base


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    # ``owner_id`` references the Admin who created the workspace. RESTRICT so a
    # workspace owner cannot be hard-deleted out from under live members.
    owner_id = Column(
        String,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Free-form plan label (presentation only). Defaults to the team tier.
    plan = Column(String, nullable=False, default="Team")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
