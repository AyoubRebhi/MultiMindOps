"""Password hashing & verification.

Bcrypt via passlib. The CryptContext is module-level so the bcrypt round
work-factor lookup happens once per process. ``verify_password`` is
constant-time at the crypto layer (bcrypt's ``checkpw`` does its own
constant-time compare), so timing attacks on the hash compare are not a
practical concern here.

Why centralized: every place that touches a password (register, login,
admin reset) must go through these two functions so the policy lives in
exactly one file. A password longer than 72 bytes is truncated by bcrypt
silently — we reject those at policy-check time instead of accepting a
hash that ignores half the input.
"""

from __future__ import annotations

import re

from passlib.context import CryptContext

# Bcrypt is the only scheme. ``deprecated="auto"`` lets us add a second
# scheme later (argon2) and have passlib upgrade hashes on next login
# without a manual rehash pass.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Policy ──────────────────────────────────────────────────────────────────
# Conservative defaults — strong enough for a multi-user dev/staging system
# without being so strict that legitimate users hit it accidentally. Tunable
# from one place if requirements tighten.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 72  # bcrypt's hard input limit
_REQUIRED_CLASSES = (
    re.compile(r"[a-z]"),  # at least one lowercase
    re.compile(r"[A-Z]"),  # at least one uppercase
    re.compile(r"[0-9]"),  # at least one digit
)


class PasswordPolicyError(ValueError):
    """Raised when a candidate password fails the policy check.

    Kept as a ValueError subclass so existing 400/422 handling around
    Pydantic validation picks it up without a new handler.
    """


def validate_password_policy(password: str) -> None:
    """Reject passwords that do not meet the platform policy.

    Caller (the register endpoint) translates the error into an HTTP 422.
    """
    if password is None or not isinstance(password, str):
        raise PasswordPolicyError("Password is required")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
        )
    # bcrypt silently truncates above 72 bytes — surfaced as a policy error.
    if len(password.encode("utf-8")) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} bytes long"
        )
    for pattern in _REQUIRED_CLASSES:
        if not pattern.search(password):
            raise PasswordPolicyError(
                "Password must contain at least one lowercase letter, "
                "one uppercase letter, and one digit"
            )


def hash_password(password: str) -> str:
    """Return a bcrypt hash for ``password``.

    Does NOT enforce policy — call ``validate_password_policy`` first when
    accepting user input. The split exists so admin-reset / migration paths
    can hash whatever they were given without a re-validation round-trip.
    """
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time verify of ``password`` against ``password_hash``.

    Returns False (never raises) if the stored hash is None/empty/invalid,
    so the calling login flow can treat all "this account cannot password-
    auth" cases the same way and avoid leaking which accounts have a
    password set.
    """
    if not password or not password_hash:
        return False
    try:
        return _pwd_context.verify(password, password_hash)
    except (ValueError, TypeError):
        return False
