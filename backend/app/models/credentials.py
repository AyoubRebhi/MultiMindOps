"""Encrypted per-project credentials.

One row per (project, provider) pair. The plaintext credential never
touches this layer — the caller passes ciphertext that's already been
through :mod:`backend.app.core.encryption`. ORM-level operations are
otherwise indistinguishable from any other model.

Why a separate table instead of stashing in Project.metadata
------------------------------------------------------------
* Project.metadata is JSONB — any operator with read access to the
  ``projects`` table also reads metadata. Credentials need finer-grained
  access control AND encryption-at-rest.
* Credential lifecycle (rotation, revocation, audit) doesn't match the
  project lifecycle. Splitting tables lets us delete-on-rotate without
  touching the project row.
* The audit trail belongs here: ``created_by`` records who set the
  secret, ``updated_by`` records who last rotated it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from backend.app.database.base import Base


class ProjectCredential(Base):
    """Encrypted secret scoped to a single project + provider.

    ``provider`` is a free-form string (``"github_pat"``, ``"aws_iam"``,
    etc.) so introducing a new credential type is a data change, not a
    migration. The provider value drives WHICH service consumes the
    decrypted plaintext at runtime — see
    :class:`backend.app.services.core.credentials_service.CredentialsService`.
    """

    __tablename__ = "project_credentials"
    __table_args__ = (
        # Exactly one credential per (project, provider). Rotation is
        # an UPDATE on the existing row, not an INSERT.
        UniqueConstraint(
            "project_id", "provider",
            name="uq_project_credentials_project_provider",
        ),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(
        String,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Provider name, e.g. "github_pat", "aws_iam", "docker_registry".
    # Free-form so adding a new credential type does not require a
    # migration; the consuming services validate the value they expect.
    provider = Column(String, nullable=False, index=True)

    # Ciphertext from ``encryption.encrypt_string``. Stored as TEXT to
    # keep the url-safe-base64 representation; do NOT swap to bytea
    # without also updating the encryption module's output shape.
    #
    # Why TEXT and not BYTEA: Fernet emits ASCII-safe base64; a TEXT
    # column round-trips through JSON, psql dumps, and SQLAlchemy
    # without any binary-quoting concerns. The downside (slight space
    # overhead) is negligible for the ~100-byte payloads we store.
    encrypted_payload = Column(Text, nullable=False)

    # Human-readable hint shown in the UI ("github.com/octocat key for
    # private repos"). Plain text — operators must not put secrets here.
    label = Column(String, nullable=True)

    # Audit pointers. NULLABLE because (a) older rows predate the column
    # and (b) ``ON DELETE SET NULL`` keeps the credential alive when the
    # creating user is removed — same pattern as the rest of the model.
    created_by = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # No back-ref on Project — credentials are accessed via the service,
    # never iterated from ``project.credentials`` in handler code. Keeping
    # the relationship off avoids accidentally serialising every
    # ciphertext into a JSON response for the Project detail view.
