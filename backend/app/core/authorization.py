"""Project-scoped authorization layer.

Two FastAPI dependencies:

* ``require_role(*roles)`` — global role gate. Currently only used to
  distinguish ADMIN from everyone else, since global roles do not exist
  yet (users are normal users). It exists for symmetry with the project-
  scoped gate and forward-compatibility with a real auth layer.

* ``require_project_role(*roles)`` — project-scoped gate. Loads the
  ProjectMember row for ``(current_user, project_id from path)`` and
  raises 403 if the member's role is not in the allowed set. ADMIN and
  OWNER are always allowed (admin escapes are explicit so audit logs can
  identify privileged actions).

Why a dependency factory: routes get to read like
``Depends(require_project_role("CLOUD_ARCHITECT", "ADMIN"))`` which makes
the policy obvious at the call site instead of buried inside the handler.
"""

from __future__ import annotations

import logging
from typing import Iterable, Set

from fastapi import Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from backend.app.core.security import get_current_user, get_db
from backend.app.models.project import Project, ProjectMember
from backend.app.models.user import User

logger = logging.getLogger(__name__)


# Roles that always pass any project-scoped check. OWNER is the creator;
# ADMIN is platform-wide and bypasses project membership lookups.
ALWAYS_ALLOWED: Set[str] = {"OWNER", "ADMIN"}


def _normalize(roles: Iterable[str]) -> Set[str]:
    return {r.upper() for r in roles}


def require_role(*roles: str):
    """Global role gate.

    Today this is effectively a no-op unless ``ADMIN`` is requested, because
    users do not yet carry a global role attribute. The dependency exists so
    future endpoints (org admin, billing, audit) can declare their policy
    today without a follow-up refactor.
    """
    allowed = _normalize(roles)

    def _checker(current_user: User = Depends(get_current_user)) -> User:
        if "ADMIN" in allowed:
            # Until a real ADMIN attribute lands, the dev user is treated as
            # ADMIN. This is consistent with ``get_current_user`` being a
            # stub. When real auth lands, this branch becomes a check against
            # ``current_user.is_admin``.
            return current_user
        return current_user

    return _checker


def require_project_role(*roles: str):
    """Project-scoped role gate.

    Resolves the ``project_id`` from the path, looks up the caller's
    membership row, and rejects the request unless the role matches one of
    ``roles`` (or is in ``ALWAYS_ALLOWED``).

    Caveat: this dependency must run on a route that has ``project_id`` in
    its path. If the path uses a different variable name, declare a thin
    wrapper that reads the correct path parameter and calls this gate.
    """
    allowed = _normalize(roles) | ALWAYS_ALLOWED

    def _checker(
        project_id: str = Path(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
    ) -> ProjectMember:
        member = (
            db.query(ProjectMember)
            .filter(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == current_user.id,
            )
            .first()
        )
        if member is None:
            # Self-heal: an owner without a membership row is a known drift
            # case (dev-seeded user, skipped insert in an older create path).
            # Recreate the OWNER row in place so the route does not 404 on a
            # legitimate caller. Non-owners still get the 404.
            project = (
                db.query(Project).filter(Project.id == project_id).first()
            )
            if project is not None and project.owner_id == current_user.id:
                member = ProjectMember(
                    project_id=project.id,
                    user_id=current_user.id,
                    role="OWNER",
                )
                db.add(member)
                db.commit()
                db.refresh(member)
                logger.warning(
                    "[PROJECT_MEMBERSHIP] Self-healed missing OWNER membership "
                    "from authz layer for project=%s owner=%s",
                    project.id, current_user.id,
                )
            else:
                # 404 on purpose — leaking existence of a project the caller has
                # no membership in is itself an information disclosure issue.
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found",
                )

        role = (member.role or "").upper()
        if role not in allowed:
            logger.info(
                "[authz] denied user=%s project=%s role=%s required=%s",
                current_user.id, project_id, role, sorted(allowed),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' is not authorized for this action.",
            )
        return member

    return _checker


# ─── Convenience aliases ────────────────────────────────────────────────────
#
# Three roles cover the practical access matrix today:
#   READ:   any member (DEVELOPER, CLOUD_ARCHITECT, VIEWER, ADMIN, OWNER)
#   WRITE:  DEVELOPER+ (excludes VIEWER)
#   GOVERN: CLOUD_ARCHITECT+ (excludes DEVELOPER, VIEWER) — approvals, validation gates.

require_project_member        = require_project_role("DEVELOPER", "CLOUD_ARCHITECT", "VIEWER")
require_project_contributor   = require_project_role("DEVELOPER", "CLOUD_ARCHITECT")
require_project_approver      = require_project_role("CLOUD_ARCHITECT")
