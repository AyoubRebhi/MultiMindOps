"""Invitation routes.

    POST   /api/invitations              — admin: invite an email (mint token)
    GET    /api/invitations              — admin: list workspace invitations
    POST   /api/invitations/{id}/resend  — admin: refresh a pending invite
    DELETE /api/invitations/{id}         — admin: revoke a pending invite

    GET    /api/invitations/{token}        — PUBLIC: landing-page lookup
    POST   /api/invitations/{token}/accept — PUBLIC: complete registration

Admin routes are gated by ``require_admin`` (global role) and scoped to the
caller's workspace. The two public routes are token-scoped and require no
auth — the token IS the capability. Routes stay thin; all rules live in
``invitation_service``.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.core.authorization import require_admin
from backend.app.core.security import get_db
from backend.app.models.user import User
from backend.app.schemas.invitation import (
    InvitationAccept,
    InvitationAdminView,
    InvitationCreate,
    InvitationLanding,
)
from backend.app.services.core import invitation_service as _svc
from backend.app.services.core.invitation_service import (
    InvitationConflict,
    InvitationError,
    InvitationNotFound,
)

router = APIRouter(prefix="/api/invitations", tags=["Invitations"])


def _client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_agent(request: Request) -> Optional[str]:
    ua = request.headers.get("user-agent")
    return ua[:255] if ua else None


def _require_workspace(current_user: User) -> str:
    ws = getattr(current_user, "workspace_id", None)
    if not ws:
        # An admin with no workspace is a data-integrity edge; surface a clear
        # 409 instead of a 500 deeper in the service.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your account is not attached to a workspace.",
        )
    return ws


# ── Admin (workspace-scoped) ────────────────────────────────────────────────


@router.post("", response_model=InvitationAdminView, status_code=status.HTTP_201_CREATED)
def create_invitation(
    payload: InvitationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    workspace_id = _require_workspace(current_user)
    try:
        inv = _svc.create_invitation(
            db,
            workspace_id=workspace_id,
            invited_by=current_user.id,
            email=payload.email,
            role=payload.role,
            message=payload.message,
        )
    except InvitationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvitationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return _svc.to_admin_view(db, inv)


@router.get("", response_model=List[InvitationAdminView])
def list_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    workspace_id = _require_workspace(current_user)
    return [_svc.to_admin_view(db, inv) for inv in _svc.list_invitations(db, workspace_id=workspace_id)]


@router.post("/{invitation_id}/resend", response_model=InvitationAdminView)
def resend_invitation(
    invitation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    workspace_id = _require_workspace(current_user)
    try:
        inv = _svc.resend_invitation(db, invitation_id=invitation_id, workspace_id=workspace_id)
    except InvitationNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvitationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _svc.to_admin_view(db, inv)


@router.delete("/{invitation_id}", response_model=InvitationAdminView)
def revoke_invitation(
    invitation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    workspace_id = _require_workspace(current_user)
    try:
        inv = _svc.revoke_invitation(db, invitation_id=invitation_id, workspace_id=workspace_id)
    except InvitationNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvitationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return _svc.to_admin_view(db, inv)


# ── Public (token-scoped, no auth) ──────────────────────────────────────────
# NOTE: declared AFTER the admin routes so the literal "" path and the
# "/{invitation_id}/..." admin paths are matched first. The token routes use a
# distinct ``{token}`` segment so there is no real collision, but ordering keeps
# the table unambiguous.


@router.get("/{token}", response_model=InvitationLanding)
def get_invitation_landing(token: str, db: Session = Depends(get_db)):
    try:
        return _svc.get_landing(db, token=token)
    except InvitationNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{token}/accept", status_code=status.HTTP_201_CREATED)
def accept_invitation(
    token: str,
    payload: InvitationAccept,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user, access, refresh, expires_in = _svc.accept_invitation(
            db,
            token=token,
            password=payload.password,
            display_name=payload.display_name,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvitationNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvitationConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except InvitationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return {
        "user": _svc_serialize(db, user),
        "tokens": {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in": expires_in,
        },
    }


def _svc_serialize(db: Session, user: User) -> dict:
    # Reuse the auth serializer so the accept response matches login/register.
    from backend.app.services.core.auth_service import serialize_user
    return serialize_user(db, user)
