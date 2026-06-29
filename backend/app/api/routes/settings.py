"""User self-service settings API.

Endpoints
---------
GET  /api/settings/profile    the caller's profile (UserPublic envelope)
PUT  /api/settings/profile    update own display name / email
PUT  /api/settings/password   change own password

These are thin wrappers over ``auth_service`` — the domain rules (email
uniqueness, re-auth on email change, password policy) live there so this
router only translates HTTP to method calls and ``AuthError`` to status codes.
``role`` is never accepted here (see ``auth_service.update_profile``).

The password endpoint delegates to the SAME ``auth_service.change_password`` as
``POST /api/auth/change-password`` — it exists so the settings surface has a
cohesive ``/api/settings/*`` namespace without duplicating logic.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.security import get_current_user, get_db
from backend.app.models.user import User
from backend.app.schemas.auth import ChangePasswordRequest, UserPublic
from backend.app.schemas.settings import ProfileUpdateRequest
from backend.app.services.core import auth_service as _auth_service
from backend.app.services.core.auth_service import AuthError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["Settings"])


def _auth_error_status(message: str) -> int:
    """Map an AuthError message to the right HTTP status.

    409 for the uniqueness conflict (frontend branches on it), 400 for a bad
    current password, 422 for everything else (policy / format failures).
    """
    lowered = message.lower()
    if "already exists" in lowered:
        return status.HTTP_409_CONFLICT
    if "incorrect" in lowered:
        return status.HTTP_400_BAD_REQUEST
    return status.HTTP_422_UNPROCESSABLE_ENTITY


@router.get("/profile", response_model=UserPublic, summary="Get own profile")
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _auth_service.serialize_user(db, current_user)


@router.put("/profile", response_model=UserPublic, summary="Update own profile (name/email)")
def update_profile(
    payload: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the caller's display name and/or email.

    ``role`` is intentionally not accepted. Changing the email requires the
    correct ``current_password`` and is rejected on a uniqueness conflict.
    """
    try:
        user = _auth_service.update_profile(
            db,
            user=current_user,
            display_name=payload.display_name,
            email=payload.email,
            current_password=payload.current_password,
        )
    except AuthError as exc:
        message = str(exc)
        raise HTTPException(status_code=_auth_error_status(message), detail=message)
    return _auth_service.serialize_user(db, user)


@router.put("/password", response_model=UserPublic, summary="Change own password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Change the caller's password — delegates to the shared auth service."""
    try:
        user = _auth_service.change_password(
            db,
            user=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except AuthError as exc:
        message = str(exc)
        code = (
            status.HTTP_400_BAD_REQUEST
            if "incorrect" in message.lower()
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=message)
    return _auth_service.serialize_user(db, user)
