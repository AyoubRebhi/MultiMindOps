"""Invitation service.

Pure-logic layer between the invitation API and the DB. Mirrors the thin-route
pattern used by ``auth_service``. Handles the full lifecycle:

    create  → admin invites an email into their workspace. The engineer's
              account is provisioned immediately with a system-generated
              temporary password (``must_change_password=true``), a single-use
              token is minted, and the credentials + acceptance link are emailed.
    landing → public lookup by token (what the invitee sees)
    accept  → invitee opens the link and sets their own password: the
              provisioned account is activated (force-change flag cleared) and
              the invitation is marked accepted
    resend  → regenerate the temporary password + refresh the window + re-send
    revoke  → cancel a pending invite

Email delivery goes through ``email_service`` (never raw SMTP here). Delivery
never blocks invitation creation: a send failure is recorded on the invitation
(``email_status='FAILED'`` + ``email_error``) and surfaced to the admin so they
can resend, while the invitation row itself is still created.

Architecture:  InvitationService → EmailService → Gmail SMTP
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.password_generator import generate_temporary_password
from backend.app.core.passwords import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
)
from backend.app.models.invitation import Invitation
from backend.app.models.user import User
from backend.app.models.workspace import Workspace
from backend.app.services.core.auth_service import AuthError, _issue_token_pair
from backend.app.services.core.email_service import EmailError, email_service

logger = logging.getLogger(__name__)

INVITATION_TTL_DAYS = 7


class InvitationError(Exception):
    """Invitation-service-level failure. Routes map this to an HTTP status."""


class InvitationNotFound(InvitationError):
    """No invitation matched the supplied token/id."""


class InvitationConflict(InvitationError):
    """The invitation cannot be acted on (already accepted/revoked/expired,
    or the email already belongs to an account)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a possibly-naive datetime (SQLite) to UTC for comparison."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def effective_status(inv: Invitation) -> str:
    """Status with on-the-fly expiry applied (a pending row past its window
    reads as 'expired' without a background sweep)."""
    if inv.status == "pending":
        exp = _aware(inv.expires_at)
        if exp is not None and exp <= _now():
            return "expired"
    return inv.status


def _inviter_identity(db: Session, invited_by: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return (display_name_or_email, email) of the inviter, or (None, None)."""
    if not invited_by:
        return None, None
    inviter = db.query(User).filter(User.id == invited_by).first()
    if inviter is None:
        return None, None
    name = (inviter.display_name or "").strip() or inviter.email
    return name, inviter.email


def build_accept_url(token: str) -> str:
    """Public acceptance link carried in the invitation email/CTA button."""
    base = (settings.FRONTEND_URL or "http://localhost:5173").rstrip("/")
    return f"{base}/invite/{token}"


# ── Account provisioning + email delivery (internal) ─────────────────────────


def _provision_invited_user(
    db: Session,
    *,
    email: str,
    role: str,
    workspace_id: str,
    temp_password: str,
    existing: Optional[User],
) -> User:
    """Create (or refresh) the invited engineer's account with a temp password.

    The plaintext ``temp_password`` is hashed immediately and never stored. The
    account is created in the ``must_change_password`` state so the engineer is
    forced to set their own password (via the link, or on first login).
    """
    password_hash = hash_password(temp_password)
    if existing is not None:
        existing.password_hash = password_hash
        existing.must_change_password = "true"
        existing.role = role
        existing.workspace_id = workspace_id
        existing.is_active = "true"
        existing.account_status = "active"
        existing.email_verified = "true"
        existing.failed_login_attempts = 0
        db.commit()
        db.refresh(existing)
        return existing

    user = User(
        email=email,
        password_hash=password_hash,
        auth_provider="local",
        is_active="true",
        account_status="active",
        email_verified="true",  # the invite proves email control
        failed_login_attempts=0,
        role=role,
        workspace_id=workspace_id,
        must_change_password="true",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _send_invitation_email(db: Session, inv: Invitation, temp_password: str) -> str:
    """Send the invitation email and record the delivery outcome on ``inv``.

    Never raises — a delivery failure is captured on the row so invitation
    creation stays successful and the admin can retry via resend. Returns the
    resulting ``email_status``.
    """
    if not email_service.is_enabled():
        inv.email_status = "SKIPPED"
        inv.email_error = None
        db.commit()
        logger.info(
            "[invite] email delivery disabled/unconfigured — skipped send to %s",
            inv.email,
        )
        return inv.email_status

    workspace = db.query(Workspace).filter(Workspace.id == inv.workspace_id).first()
    inviter_name, inviter_email = _inviter_identity(db, inv.invited_by)
    try:
        email_service.send_invitation_email(
            to_email=inv.email,
            workspace_name=workspace.name if workspace else "Workspace",
            role=inv.role,
            temp_password=temp_password,
            accept_url=build_accept_url(inv.token),
            invited_by=inviter_name or inviter_email,
            message=inv.message,
        )
        inv.email_status = "SENT"
        inv.email_error = None
        inv.email_sent_at = _now()
    except EmailError as exc:
        inv.email_status = "FAILED"
        inv.email_error = str(exc)[:1000]
        logger.warning("[invite] email delivery FAILED to %s: %s", inv.email, exc)
    db.commit()
    return inv.email_status


# ── Public service API ───────────────────────────────────────────────────────


def create_invitation(
    db: Session,
    *,
    workspace_id: str,
    invited_by: str,
    email: str,
    role: str = "DEVOPS_ENGINEER",
    message: Optional[str] = None,
) -> Invitation:
    """Create (or refresh) a pending invitation for ``email`` and email it.

    Provisions the engineer's account with a generated temporary password and
    dispatches the invitation email. Re-inviting an email that still has a
    pending invitation in the same workspace refreshes it (regenerates the temp
    password + re-sends) instead of duplicating the row.
    """
    email_norm = (email or "").strip().lower()
    now = _now()

    existing_user = db.query(User).filter(User.email == email_norm).first()
    existing_pending = (
        db.query(Invitation)
        .filter(
            Invitation.workspace_id == workspace_id,
            Invitation.email == email_norm,
            Invitation.status == "pending",
        )
        .first()
    )

    # Resend semantics: a still-pending invitation for this email already exists
    # → regenerate the temp password on the provisioned account, refresh the
    # window and re-send. Avoids duplicate rows and stale temp passwords.
    if existing_pending is not None:
        temp_password = generate_temporary_password()
        _provision_invited_user(
            db,
            email=email_norm,
            role=role,
            workspace_id=workspace_id,
            temp_password=temp_password,
            existing=existing_user,
        )
        existing_pending.role = role
        existing_pending.message = message
        existing_pending.invited_by = invited_by
        existing_pending.expires_at = now + timedelta(days=INVITATION_TTL_DAYS)
        existing_pending.email_status = "PENDING"
        existing_pending.email_error = None
        db.commit()
        db.refresh(existing_pending)
        _send_invitation_email(db, existing_pending, temp_password)
        return existing_pending

    # No pending invitation. If an account already exists for this email it can
    # only be re-invited when it is still an un-activated invite stub (i.e. the
    # invitee never set their own password — ``must_change_password`` is still
    # true). A fully-activated account — the workspace admin, or an engineer who
    # completed registration — is a real user and cannot be re-invited.
    if existing_user is not None and not existing_user.must_change_password_bool:
        raise InvitationConflict("A user with this email already exists")

    temp_password = generate_temporary_password()
    _provision_invited_user(
        db,
        email=email_norm,
        role=role,
        workspace_id=workspace_id,
        temp_password=temp_password,
        existing=existing_user,  # refresh the leftover stub, or create fresh
    )

    invitation = Invitation(
        workspace_id=workspace_id,
        email=email_norm,
        role=role,
        status="pending",
        token=secrets.token_urlsafe(32),
        invited_by=invited_by,
        message=message,
        expires_at=now + timedelta(days=INVITATION_TTL_DAYS),
        email_status="PENDING",
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    _send_invitation_email(db, invitation, temp_password)
    return invitation


def list_invitations(db: Session, *, workspace_id: str) -> list[Invitation]:
    """All invitations for a workspace, newest first."""
    return (
        db.query(Invitation)
        .filter(Invitation.workspace_id == workspace_id)
        .order_by(Invitation.created_at.desc())
        .all()
    )


def get_landing(db: Session, *, token: str) -> dict:
    """Public token lookup. Raises InvitationNotFound if no row matches."""
    inv = db.query(Invitation).filter(Invitation.token == token).first()
    if inv is None:
        raise InvitationNotFound("Invitation not found")

    workspace = db.query(Workspace).filter(Workspace.id == inv.workspace_id).first()
    inviter_name, inviter_email = _inviter_identity(db, inv.invited_by)
    return {
        "token": inv.token,
        "email": inv.email,
        "role": inv.role,
        "status": effective_status(inv),
        "workspace_name": workspace.name if workspace else "Workspace",
        "invited_by": inviter_name,
        "invited_by_email": inviter_email,
        "message": inv.message,
        "expires_at": inv.expires_at,
    }


def accept_invitation(
    db: Session,
    *,
    token: str,
    password: str,
    display_name: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> tuple[User, str, str, int]:
    """Activate the invitee's account with their chosen password.

    The account was provisioned at invite time with a temporary password; here
    the invitee replaces it with their own, the ``must_change_password`` flag is
    cleared, and the invitation is marked accepted. (A legacy invitation with no
    provisioned account falls back to creating the user.)

    Returns the same ``(user, access, refresh, expires_in)`` tuple as the auth
    service so the caller could auto-login; the frontend instead redirects to
    sign-in per the product journey.
    """
    inv = db.query(Invitation).filter(Invitation.token == token).first()
    if inv is None:
        raise InvitationNotFound("Invitation not found")

    status = effective_status(inv)
    if status != "pending":
        raise InvitationConflict(f"This invitation is {status}")

    try:
        validate_password_policy(password)
    except PasswordPolicyError as exc:
        raise InvitationError(str(exc)) from exc

    user = db.query(User).filter(User.email == inv.email).first()
    if user is not None:
        # Activate the account provisioned at invite time.
        user.password_hash = hash_password(password)
        user.must_change_password = "false"
        if (display_name or "").strip():
            user.display_name = display_name.strip()
        user.role = inv.role
        user.workspace_id = inv.workspace_id
        user.is_active = "true"
        user.account_status = "active"
        user.email_verified = "true"
        user.failed_login_attempts = 0
    else:
        # Backward-compat: legacy invitation created before account-at-invite.
        user = User(
            email=inv.email,
            display_name=(display_name or "").strip() or None,
            password_hash=hash_password(password),
            auth_provider="local",
            is_active="true",
            account_status="active",
            email_verified="true",
            failed_login_attempts=0,
            role=inv.role,
            workspace_id=inv.workspace_id,
            must_change_password="false",
        )
        db.add(user)

    inv.status = "accepted"
    inv.accepted_at = _now()
    db.commit()
    db.refresh(user)

    access_token, refresh_token, expires_in = _issue_token_pair(
        db, user, ip_address=ip_address, user_agent=user_agent,
    )
    user.last_login_at = _now()
    db.commit()
    return user, access_token, refresh_token, expires_in


def mark_invitation_accepted_for_user(db: Session, user: User) -> int:
    """Mark any pending invitation(s) for this user's email as accepted.

    Used when an invited engineer activates by signing in with the temporary
    password and completing the forced password change, rather than via the
    acceptance link — keeps the admin's Invitations list accurate. Returns the
    number of invitations updated.
    """
    if user is None or not user.email:
        return 0
    pending = (
        db.query(Invitation)
        .filter(Invitation.email == user.email, Invitation.status == "pending")
        .all()
    )
    now = _now()
    for inv in pending:
        inv.status = "accepted"
        inv.accepted_at = now
    if pending:
        db.commit()
    return len(pending)


def _get_owned(db: Session, *, invitation_id: str, workspace_id: str) -> Invitation:
    inv = (
        db.query(Invitation)
        .filter(
            Invitation.id == invitation_id,
            Invitation.workspace_id == workspace_id,
        )
        .first()
    )
    if inv is None:
        raise InvitationNotFound("Invitation not found")
    return inv


def resend_invitation(db: Session, *, invitation_id: str, workspace_id: str) -> Invitation:
    """Refresh a pending invitation: regenerate the temp password + re-send."""
    inv = _get_owned(db, invitation_id=invitation_id, workspace_id=workspace_id)
    if inv.status not in ("pending", "expired"):
        raise InvitationConflict(f"Cannot resend a {inv.status} invitation")

    inv.status = "pending"
    inv.expires_at = _now() + timedelta(days=INVITATION_TTL_DAYS)
    temp_password = generate_temporary_password()
    existing_user = db.query(User).filter(User.email == inv.email).first()
    _provision_invited_user(
        db,
        email=inv.email,
        role=inv.role,
        workspace_id=workspace_id,
        temp_password=temp_password,
        existing=existing_user,
    )
    inv.email_status = "PENDING"
    inv.email_error = None
    db.commit()
    db.refresh(inv)
    _send_invitation_email(db, inv, temp_password)
    return inv


def revoke_invitation(db: Session, *, invitation_id: str, workspace_id: str) -> Invitation:
    """Cancel a pending invitation."""
    inv = _get_owned(db, invitation_id=invitation_id, workspace_id=workspace_id)
    if inv.status == "accepted":
        raise InvitationConflict("Cannot revoke an accepted invitation")
    inv.status = "revoked"
    db.commit()
    db.refresh(inv)
    return inv


def to_admin_view(db: Session, inv: Invitation) -> dict:
    """Map an Invitation row to the admin list shape."""
    inviter_name, _ = _inviter_identity(db, inv.invited_by)
    return {
        "id": inv.id,
        "email": inv.email,
        "role": inv.role,
        "status": effective_status(inv),
        "invited_by": inviter_name,
        "message": inv.message,
        "token": inv.token,
        "email_status": inv.email_status or "PENDING",
        "email_error": inv.email_error,
        "email_sent_at": inv.email_sent_at,
        "sent_at": inv.created_at,
        "expires_at": inv.expires_at,
        "accepted_at": inv.accepted_at,
    }
