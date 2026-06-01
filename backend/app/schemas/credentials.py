"""Pydantic schemas for the credentials API.

The response models DO NOT expose ``encrypted_payload`` or any decrypted
plaintext — only metadata + a masked preview. This is enforced at the
schema layer (not the handler) so a future careless edit to a route
cannot accidentally widen the response surface.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CredentialUpsertRequest(BaseModel):
    """Body for ``POST /api/projects/{project_id}/credentials``.

    ``plaintext`` is consumed by the service immediately, encrypted, and
    discarded. The schema does not echo it back in any response.
    """

    provider: str = Field(
        ...,
        min_length=1,
        max_length=64,
        examples=["github_pat", "aws_iam", "docker_registry"],
        description=(
            "Provider name. Free-form so new credential types can be added "
            "without a schema change; the consuming service validates the "
            "shape it expects."
        ),
    )
    plaintext: str = Field(
        ...,
        min_length=1,
        description=(
            "The secret value. Sent only on create/rotate; never echoed "
            "back. The server encrypts it before storing."
        ),
    )
    label: Optional[str] = Field(
        default=None,
        max_length=200,
        description=(
            "Human-readable description ('GH PAT for repo X'). Plain text. "
            "Operators must NOT put secrets here — only metadata."
        ),
    )

    @field_validator("provider")
    @classmethod
    def _normalize_provider(cls, v: str) -> str:
        return v.strip()


class CredentialResponse(BaseModel):
    """Masked metadata for a stored credential.

    NEVER includes the ciphertext or any decrypted form. ``masked_preview``
    is a hint for operators recognising which credential is which — it
    shows only the last 4 chars + bullets and is computed server-side
    after decryption.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    provider: str
    label: Optional[str]
    created_by: Optional[str]
    updated_by: Optional[str]
    created_at: datetime
    updated_at: datetime
    # Computed in the route layer, not via ORM — populated from the
    # decrypted plaintext at response-build time, then discarded.
    # Optional because list endpoints skip the decrypt step for perf.
    masked_preview: Optional[str] = None
