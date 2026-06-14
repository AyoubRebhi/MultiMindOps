import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from backend.app.database.base import Base


class User(Base):
    """Application user.

    Auth columns added in the auth-foundation phase. Legacy rows (created
    under the dev-stub auth) have ``password_hash IS NULL`` and a non-null
    ``auth_provider`` of ``'dev'`` — they cannot log in via the password
    flow until a password is set, but they remain referenceable from
    ProjectMember / Project ownership.
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=True)
    is_active = Column(String, nullable=False, default="true")

    # ── Auth columns ────────────────────────────────────────────────────────
    # NULL for dev-seeded or SSO-only accounts; set when the user registers
    # via the password flow. Always a bcrypt hash; never a plaintext.
    password_hash = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    # 'local' (password) | 'dev' (legacy stub) | 'google' | 'github' | ...
    auth_provider = Column(String, nullable=False, default="local")
    # Stored as string for portability with the existing ``is_active`` style.
    email_verified = Column(String, nullable=False, default="false")
    # 'active' | 'disabled' | 'locked' | 'pending'
    account_status = Column(String, nullable=False, default="active")
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0)

    # ── Workspace / global role ─────────────────────────────────────────────
    # Global (workspace-level) role driving the frontend experience and the
    # admin-only API gates. 'ADMIN' owns the workspace (self-registered);
    # 'DEVOPS_ENGINEER' joins via an invitation. This is distinct from the
    # project-scoped ProjectMember.role used by the workflow authorization
    # layer — see backend/app/core/authorization.py.
    role = Column(String, nullable=False, default="DEVOPS_ENGINEER")
    # Soft pointer to the owning Workspace (no FK constraint to avoid a
    # circular users<->workspaces dependency at create_all() time; the
    # relationship is resolved by id in the service layer).
    workspace_id = Column(String, nullable=True, index=True)
    # Set 'true' when the account was provisioned with a system-generated
    # temporary password (invited engineers). The frontend forces a password
    # change on first sign-in and the change-password flow clears this flag.
    # Stored as a string for consistency with is_active / email_verified.
    must_change_password = Column(String, nullable=False, default="false")

    # Audit pointers — nullable because the first user, the dev seed, and
    # background-created users have no actor.
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

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def is_active_bool(self) -> bool:
        """Truthy view of ``is_active`` regardless of how it was stored."""
        val = (self.is_active or "").strip().lower()
        return val in ("true", "1", "yes", "active")

    @property
    def must_change_password_bool(self) -> bool:
        """Truthy view of ``must_change_password`` (string-stored boolean)."""
        val = (self.must_change_password or "").strip().lower()
        return val in ("true", "1", "yes")
