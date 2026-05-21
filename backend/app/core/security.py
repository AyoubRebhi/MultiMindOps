"""Phase 1 stub authentication.

There is no real auth provider yet. ``get_current_user`` always returns
(creating on first call) the seeded development user. The signature already
matches what a real implementation will look like — a FastAPI dependency
that returns a ``User`` and accepts a ``Session`` — so future swap-in is a
single-file change.

Why this approach: Phase 1 needs Project ownership and role membership to
be real (foreign keys, cascading deletes) without committing to JWT / OAuth
plumbing that is a separate concern.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from backend.app.database.session import SessionLocal
from backend.app.models.user import User


DEV_USER_EMAIL = "dev@devsecops-ai.local"
DEV_USER_NAME = "Local Dev"


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_dev_user(db: Session) -> User:
    user = db.query(User).filter(User.email == DEV_USER_EMAIL).first()
    if user is None:
        user = User(email=DEV_USER_EMAIL, display_name=DEV_USER_NAME, is_active="true")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_current_user(db: Session = Depends(get_db)) -> User:
    """FastAPI dependency that returns the current user.

    Phase 1: always the seeded dev user. Phase 2 will decode a JWT here and
    fall back to the dev user only when ``settings.AUTH_MODE == "dev"``.
    """
    return _ensure_dev_user(db)
