"""User self-service settings schemas.

The profile-update body is intentionally narrow: only ``display_name`` and
``email`` are accepted. ``role`` is NOT here on purpose — it is the global
workspace role and self-editing it would be a privilege escalation, so it is
read-only from the user's perspective (changed only via admin member
management). Email changes carry the current password for re-auth.

The response shape reuses ``UserPublic`` from the auth schemas so ``/me`` and
``/settings/profile`` always agree on the user envelope.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ProfileUpdateRequest(BaseModel):
    """Body for ``PUT /api/settings/profile``.

    Partial update: only fields that are present are changed. ``current_password``
    is required by the service ONLY when ``email`` actually changes; it is
    ignored otherwise and never stored.
    """

    display_name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = Field(default=None, max_length=320)
    current_password: Optional[str] = Field(default=None, max_length=128, repr=False)
