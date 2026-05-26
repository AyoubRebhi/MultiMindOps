"""Normalized auth error envelopes.

Every 401/403 raised by the auth/authorization layer is wrapped in the
same shape:

    {"code": "UNAUTHORIZED", "message": "Authentication required"}
    {"code": "FORBIDDEN",    "message": "Insufficient permissions"}

FastAPI's default ``HTTPException(detail=...)`` already serializes a
``detail`` field. We override the body via a small helper so the
``code`` discriminator lives at the top level — the frontend matches on
``code`` and shows a localized message, never the raw ``message``.
"""

from __future__ import annotations

from fastapi import HTTPException, status

UNAUTHORIZED_CODE = "UNAUTHORIZED"
FORBIDDEN_CODE = "FORBIDDEN"


def unauthorized(message: str = "Authentication required") -> HTTPException:
    """Return a 401 HTTPException with the canonical envelope.

    The WWW-Authenticate header is set so a compliant HTTP client
    surfaces the right "please log in" UX automatically — handy for any
    raw curl/HTTPie consumer.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": UNAUTHORIZED_CODE, "message": message},
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(message: str = "Insufficient permissions") -> HTTPException:
    """Return a 403 HTTPException with the canonical envelope."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": FORBIDDEN_CODE, "message": message},
    )
