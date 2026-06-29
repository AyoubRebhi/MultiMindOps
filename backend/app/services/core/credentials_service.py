"""CredentialsService — encrypted secret storage scoped to a project.

Contract
--------
* :func:`set_credential` writes a NEW ciphertext for ``(project, provider)``
  or rotates the existing one. Plaintext enters; ciphertext leaves; the
  plaintext is never logged, never echoed back, never persisted alongside
  the ciphertext.
* :func:`get_credential` returns the plaintext IN MEMORY for a single
  caller. The handler is responsible for not leaking it further — pass
  it into the subprocess env and let it go out of scope.
* :func:`list_credentials` returns masked metadata only — never plaintext.
* :func:`delete_credential` revokes by row deletion.

Why these are static methods (not a class with state)
-----------------------------------------------------
The DB session is passed in. The cipher is process-wide and module-level
in ``encryption``. There's no per-instance state to hide. A class wrapper
exists only for API symmetry with the other services in this directory.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.app.core import encryption
from backend.app.models.credentials import ProjectCredential

logger = logging.getLogger(__name__)


# Canonical provider keys. The two DevOps credential types the platform manages
# per-project. Kept as constants so the typed routes + the project-settings
# aggregator never disagree on the spelling.
GITHUB_PROVIDER = "github_pat"
AWS_PROVIDER = "aws_iam"

# Provider names recognised by the platform today. The service accepts any
# string, but tracking the known set in one place lets API validation refuse
# obvious typos at the route layer.
KNOWN_PROVIDERS = {
    GITHUB_PROVIDER,    # GitHub personal access token (clone, push)
    AWS_PROVIDER,       # AWS access-key-id + secret-access-key bundle (JSON)
    "docker_registry",  # Registry username/password bundle (JSON)
}


class CredentialError(Exception):
    """Service-level failure. Routes translate to 4xx."""


class CredentialsService:
    """Encrypted credential storage. Stateless — all methods are static."""

    # ── Mutations ──────────────────────────────────────────────────────────

    @staticmethod
    def set_credential(
        db: Session,
        *,
        project_id: str,
        provider: str,
        plaintext: str,
        created_by: Optional[str],
        label: Optional[str] = None,
    ) -> ProjectCredential:
        """Create or rotate a credential for ``(project, provider)``.

        Idempotent on the (project, provider) pair: a second call with a
        new plaintext rotates the row rather than inserting a duplicate.
        The plaintext is encrypted IN PROCESS and only the ciphertext
        ever touches the DB.

        Raises
        ------
        CredentialError
            ``plaintext`` is empty, or ``provider`` is blank. We refuse
            an empty credential here so a UX bug (form not sending the
            value) cannot wipe an existing one.
        """
        provider_norm = (provider or "").strip()
        if not provider_norm:
            raise CredentialError("Provider must not be empty")
        if not plaintext:
            raise CredentialError(
                "Credential plaintext must not be empty — to remove a "
                "credential, call delete_credential() explicitly."
            )

        ciphertext = encryption.encrypt_string(plaintext)

        row = (
            db.query(ProjectCredential)
            .filter(
                ProjectCredential.project_id == project_id,
                ProjectCredential.provider == provider_norm,
            )
            .first()
        )

        if row is None:
            row = ProjectCredential(
                project_id=project_id,
                provider=provider_norm,
                encrypted_payload=ciphertext,
                label=label,
                created_by=created_by,
                updated_by=created_by,
            )
            db.add(row)
            logger.info(
                "[Credentials] CREATED project=%s provider=%s by=%s",
                project_id, provider_norm, created_by,
            )
        else:
            row.encrypted_payload = ciphertext
            # Don't overwrite label on rotation unless the caller passed
            # one explicitly — None means "keep whatever was there".
            if label is not None:
                row.label = label
            row.updated_by = created_by
            logger.info(
                "[Credentials] ROTATED project=%s provider=%s by=%s",
                project_id, provider_norm, created_by,
            )

        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def delete_credential(
        db: Session,
        *,
        project_id: str,
        provider: str,
    ) -> bool:
        """Remove a credential row. Returns True iff a row was deleted.

        Idempotent: deleting a non-existent credential is a 200 from the
        caller's perspective, not a 404. The audit signal lives in the
        log line, not the HTTP status.
        """
        row = (
            db.query(ProjectCredential)
            .filter(
                ProjectCredential.project_id == project_id,
                ProjectCredential.provider == provider,
            )
            .first()
        )
        if row is None:
            return False
        db.delete(row)
        db.commit()
        logger.info(
            "[Credentials] DELETED project=%s provider=%s",
            project_id, provider,
        )
        return True

    # ── Reads ──────────────────────────────────────────────────────────────

    @staticmethod
    def get_credential(
        db: Session,
        *,
        project_id: str,
        provider: str,
    ) -> Optional[str]:
        """Return the decrypted plaintext, or None if no credential is set.

        SHOULD ONLY BE CALLED at the moment the plaintext is needed —
        e.g. just before invoking a subprocess that requires it. The
        returned string lives in Python's heap; ensure it goes out of
        scope promptly. Never store it on ``self`` of a long-lived
        object, never put it into ``workflow_state``, never log it.
        """
        row = (
            db.query(ProjectCredential)
            .filter(
                ProjectCredential.project_id == project_id,
                ProjectCredential.provider == provider,
            )
            .first()
        )
        if row is None:
            return None
        # Decryption is the only place we touch plaintext. Surface
        # failures as DecryptionError; the route translates that to a
        # 503 (operational issue, not a user input bug).
        return encryption.decrypt_string(row.encrypted_payload)

    @staticmethod
    def list_credentials(
        db: Session,
        *,
        project_id: str,
    ) -> List[ProjectCredential]:
        """Return rows for masked-metadata display.

        The returned ORM rows still carry the encrypted ciphertext. The
        route layer maps them to a masked response schema BEFORE returning
        to the client — see ``schemas/credentials.py``.
        """
        return (
            db.query(ProjectCredential)
            .filter(ProjectCredential.project_id == project_id)
            .order_by(ProjectCredential.provider.asc())
            .all()
        )

    @staticmethod
    def has_credential(
        db: Session,
        *,
        project_id: str,
        provider: str,
    ) -> bool:
        """Existence probe — does NOT decrypt.

        Used by the workflow flow to decide whether to fetch a credential
        before invoking a subprocess that might need it. Cheap (single
        index lookup) so callers can sprinkle it wherever it helps.
        """
        return (
            db.query(ProjectCredential.id)
            .filter(
                ProjectCredential.project_id == project_id,
                ProjectCredential.provider == provider,
            )
            .first()
            is not None
        )

    # ── AWS bundle helpers ───────────────────────────────────────────────────
    #
    # AWS needs four fields but only two are secret. We keep the SECRETS
    # (access_key_id + secret_access_key) encrypted in ``encrypted_payload`` as
    # a JSON bundle, and the NON-SECRET display metadata (region, account_name,
    # and the access-key-id last-4 recognisability hint) in ``label`` as JSON.
    # That lets ``get_aws_status`` render "configured + region/account/last-4"
    # WITHOUT a decrypt, while the secret access key never leaves the cipher.

    @staticmethod
    def set_aws_credential(
        db: Session,
        *,
        project_id: str,
        access_key_id: str,
        secret_access_key: str,
        region: str,
        account_name: Optional[str],
        created_by: Optional[str],
    ) -> ProjectCredential:
        """Create or rotate the project's AWS credential bundle.

        The secret access key is encrypted; region/account/last-4 are stored as
        non-secret label metadata for cheap, decrypt-free status reads.
        """
        secret_bundle = json.dumps(
            {"access_key_id": access_key_id, "secret_access_key": secret_access_key}
        )
        label_meta = json.dumps(
            {
                "region": region,
                "account_name": account_name,
                # last-4 of the access-key-id is an identifier hint, not a
                # secret — safe to store in the clear for the "is this the
                # right account" UI affordance.
                "access_key_id_last4": access_key_id[-4:],
            }
        )
        return CredentialsService.set_credential(
            db,
            project_id=project_id,
            provider=AWS_PROVIDER,
            plaintext=secret_bundle,
            created_by=created_by,
            label=label_meta,
        )

    @staticmethod
    def get_aws_status(db: Session, *, project_id: str) -> Optional[dict]:
        """Return NON-SECRET AWS display metadata, or None if not configured.

        Reads only ``label`` — never decrypts the secret bundle. Shape:
        ``{"region", "account_name", "access_key_id_last4"}``.
        """
        row = (
            db.query(ProjectCredential)
            .filter(
                ProjectCredential.project_id == project_id,
                ProjectCredential.provider == AWS_PROVIDER,
            )
            .first()
        )
        if row is None:
            return None
        try:
            meta = json.loads(row.label or "{}")
        except (ValueError, TypeError):
            meta = {}
        return {
            "region": meta.get("region"),
            "account_name": meta.get("account_name"),
            "access_key_id_last4": meta.get("access_key_id_last4"),
        }

    # ── Runtime state hydration ──────────────────────────────────────────────

    @staticmethod
    def hydrate_state(db: Session, state: dict, *, project_id: str) -> dict:
        """Inject runtime-only credentials into an in-memory workflow state.

        Phase 4 — secret values like ``github_token`` are never persisted
        into ``Task.workflow_state`` (the scrub in
        :func:`backend.app.services.core.task_service._sanitize_for_json`
        drops them on every save). To make them available to the agents
        that need them, callers re-hydrate from the encrypted store at
        request time via this helper.

        The returned dict is a shallow copy so the caller may mutate it;
        the next ``save_workflow_state`` scrubs the injected keys back out
        before they touch the DB, so they live only for the request.

        Decryption failures are non-fatal — we log the failure *class*
        (never the value) and return the state without the token, letting
        the phase degrade to "try without auth" rather than crash.
        """
        if not project_id:
            return state
        new_state = dict(state)
        try:
            gh = CredentialsService.get_credential(
                db, project_id=project_id, provider="github_pat",
            )
        except Exception as exc:
            logger.warning(
                "[Credentials] github_pat hydrate failed for project=%s — "
                "phase will run without a token: %s",
                project_id, exc.__class__.__name__,
            )
            gh = None
        if gh:
            new_state["github_token"] = gh
        return new_state
