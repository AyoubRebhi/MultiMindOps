import uuid

from sqlalchemy import Column, DateTime, String
from sqlalchemy.sql import func

from backend.app.database.base import Base


class User(Base):
    """Application user.

    Auth is stubbed in Phase 1: there is no password/JWT yet. The schema is
    kept compatible with a future real auth provider — only ``hashed_password``
    is missing. ``get_current_user`` returns a seeded dev user so ownership
    and membership can be modelled correctly today.
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=True)
    is_active = Column(String, nullable=False, default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
