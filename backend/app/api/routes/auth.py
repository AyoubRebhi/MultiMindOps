"""Authentication routes.

    POST /auth/register   — create a user, return token pair
    POST /auth/login      — verify credentials, return token pair
    POST /auth/refresh    — rotate a refresh token into a new pair
    POST /auth/logout     — revoke the current session (or all sessions)
    GET  /auth/me         — return the caller's user record

Routes are deliberately thin — every domain rule lives in
``AuthService``. Routes only translate HTTP into method calls and
errors back into HTTP envelopes.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.core.auth_errors import unauthorized
from backend.app.core.security import get_current_user, get_db
from backend.app.models.user import User
from backend.app.schemas.auth import (
    AuthSuccessResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
    UserPublic,
)
from backend.app.services.core import auth_service as _auth_service
from backend.app.services.core.auth_service import AuthError

router = APIRouter(prefix="/api/auth", tags=["Auth"])


def _client_ip(request: Request) -> Optional[str]:
    """Best-effort client IP for the session-row audit fields.

    Trusts ``X-Forwarded-For`` because the deployment will sit behind
    nginx / a load balancer. In a non-proxied dev run this falls back
    to ``request.client.host``.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_agent(request: Request) -> Optional[str]:
    ua = request.headers.get("user-agent")
    if not ua:
        return None
    return ua[:255]  # cap to avoid storing absurd payloads


def _success(user: User, access: str, refresh: str, expires_in: int) -> dict:
    return {
        "user": UserPublic.model_validate(user).model_dump(mode="json"),
        "tokens": TokenPairResponse(
            access_token=access,
            refresh_token=refresh,
            expires_in=expires_in,
        ).model_dump(),
    }


@router.post(
    "/register",
    response_model=AuthSuccessResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user, access, refresh, expires_in = _auth_service.register_user(
            db,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except AuthError as exc:
        # 409 for the "email already exists" case so the frontend can
        # branch; everything else is 422 (policy failure).
        message = str(exc)
        code = (
            status.HTTP_409_CONFLICT
            if "already exists" in message.lower()
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(status_code=code, detail=message)
    return _success(user, access, refresh, expires_in)


@router.post("/login", response_model=AuthSuccessResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user, access, refresh, expires_in = _auth_service.authenticate_user(
            db,
            email=payload.email,
            password=payload.password,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except AuthError as exc:
        raise unauthorized(str(exc))
    return _success(user, access, refresh, expires_in)


@router.post("/refresh", response_model=AuthSuccessResponse)
def refresh(
    payload: RefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user, access, refresh_token, expires_in = _auth_service.refresh_session(
            db,
            refresh_token=payload.refresh_token,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except AuthError as exc:
        raise unauthorized(str(exc))
    return _success(user, access, refresh_token, expires_in)


@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(
    payload: Optional[LogoutRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Revoke one or all sessions for the authenticated caller.

    Idempotent: calling logout twice (or with a junk refresh token) is
    a 200 — the caller is logged out regardless.
    """
    refresh_token = payload.refresh_token if payload else None
    revoked = _auth_service.revoke_session(
        db, user=current_user, refresh_token=refresh_token,
    )
    return {"revoked_sessions": revoked}


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)):
    return current_user
