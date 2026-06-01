"""Project-scoped encrypted credentials API.

Endpoints
---------
POST   /api/projects/{project_id}/credentials              upsert (create or rotate)
GET    /api/projects/{project_id}/credentials              list (masked metadata)
DELETE /api/projects/{project_id}/credentials/{provider}   revoke

Authorization
-------------
* Writes require CLOUD_ARCHITECT (or OWNER/ADMIN via the ALWAYS_ALLOWED
  set). Credentials grant access to other systems, so the role tier is
  raised one notch above plain DEVELOPER.
* Reads (list) require DEVELOPER+ — enough to know which credentials
  exist for the project, never plaintext.

Plaintext exposure
------------------
None of these endpoints return decrypted plaintext. The masked_preview
field gives operators a "is this the right key" hint without leaking the
secret. The only way to extract a credential is to consume it inside the
backend (subprocess env, GitHub clone) where it never crosses the API
boundary.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.authorization import (
    require_project_approver,
    require_project_contributor,
)
from backend.app.core.encryption import (
    DecryptionError,
    MissingMasterKeyError,
    mask_secret,
)
from backend.app.core.security import get_current_user, get_db
from backend.app.models.project import ProjectMember
from backend.app.models.user import User
from backend.app.schemas.credentials import (
    CredentialResponse,
    CredentialUpsertRequest,
)
from backend.app.services.core.credentials_service import (
    CredentialError,
    CredentialsService,
)
from backend.app.services.core.project_service import ProjectService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/projects/{project_id}/credentials",
    tags=["Credentials"],
)


def _to_response(row, *, masked_preview: str | None = None) -> CredentialResponse:
    """Map an ORM row into the masked response shape.

    We map by hand (rather than ``from_attributes`` alone) so the
    ``masked_preview`` field can be set from a value computed outside
    the row. The schema's ``model_config = ConfigDict(from_attributes=True)``
    still drives the attribute-name mapping for the rest of the fields.
    """
    base = CredentialResponse.model_validate(row).model_dump()
    base["masked_preview"] = masked_preview
    return CredentialResponse.model_validate(base)


def _ensure_project_or_404(db: Session, project_id: str, user: User) -> None:
    """Membership-aware existence check.

    The route dependency already validated role on this project, but it
    accepts the path parameter without verifying the project actually
    exists (factory pattern). Belt-and-braces: confirm the project row
    exists, hide existence from non-members via 404.
    """
    project = ProjectService.get_project_for_user(db, project_id, user)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.post(
    "",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or rotate a project credential (CLOUD_ARCHITECT+)",
)
def upsert_credential(
    project_id: str,
    payload: CredentialUpsertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_approver),
):
    """Encrypt ``payload.plaintext`` and store as the project's credential
    for ``payload.provider``. Replaces any existing row for that provider
    on the same project (rotation).

    Returns the row with a masked preview of the just-stored value so
    operators can confirm what was uploaded without it being echoed back
    in full.
    """
    _ensure_project_or_404(db, project_id, current_user)
    try:
        row = CredentialsService.set_credential(
            db,
            project_id=project_id,
            provider=payload.provider,
            plaintext=payload.plaintext,
            created_by=current_user.id,
            label=payload.label,
        )
    except CredentialError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except MissingMasterKeyError as exc:
        # APP_SECRET_KEY is not set — operational issue. 503 because the
        # service is intentionally refusing to accept secrets it cannot
        # safely store. The detail says how to fix it without leaking
        # whether any credentials already exist.
        logger.error("[Credentials] master key missing — refusing write")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Credential storage is not configured on this deployment. "
                "Operator must set APP_SECRET_KEY before credentials can "
                "be stored."
            ),
        ) from exc

    # Mask using the plaintext we just received so the response shows a
    # preview without re-decrypting (which would log a decrypt path
    # unnecessarily).
    return _to_response(row, masked_preview=mask_secret(payload.plaintext))


@router.get(
    "",
    response_model=list[CredentialResponse],
    summary="List project credentials (masked metadata only, DEVELOPER+)",
)
def list_credentials(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),
):
    """Return one row per (project, provider).

    Never includes plaintext or ciphertext. ``masked_preview`` is omitted
    here — populating it would require N decrypt operations per request,
    each of which is a small but non-zero leak surface (timing, key
    activity). Operators who want a preview should re-upload and view
    the create response.
    """
    _ensure_project_or_404(db, project_id, current_user)
    rows = CredentialsService.list_credentials(db, project_id=project_id)
    return [_to_response(r) for r in rows]


@router.delete(
    "/{provider}",
    status_code=status.HTTP_200_OK,
    summary="Revoke a project credential (CLOUD_ARCHITECT+)",
)
def delete_credential(
    project_id: str,
    provider: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_approver),
):
    """Delete the row for ``(project, provider)``.

    Idempotent — calling twice is a 200 either way. The audit lives in
    the application log line emitted by the service, not the HTTP code.
    """
    _ensure_project_or_404(db, project_id, current_user)
    removed = CredentialsService.delete_credential(
        db, project_id=project_id, provider=provider,
    )
    return {"deleted": removed, "provider": provider}


# Optional diagnostic: tells the caller whether the encryption layer is
# ready without revealing key material. Used by the frontend to render a
# "credentials disabled — operator setup required" banner instead of a
# 503 splash when the user hits the credentials tab.
@router.get(
    "/_status",
    summary="Check whether the encryption layer is configured",
)
def credentials_status(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _member: ProjectMember = Depends(require_project_contributor),
):
    """Returns ``{"configured": bool}``.

    ``configured: false`` means ``APP_SECRET_KEY`` is unset — credentials
    cannot be stored until an operator sets it. We do not surface any
    detail about which keys are loaded.
    """
    from backend.app.core.encryption import is_configured
    _ensure_project_or_404(db, project_id, current_user)
    return {"configured": is_configured()}
