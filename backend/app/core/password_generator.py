"""Cryptographically secure temporary-password generator.

Used when an ADMIN invites a DEVOPS_ENGINEER: the platform mints a strong
one-time password, emails it once, and stores only its bcrypt hash (the
plaintext is never persisted — see invitation_service). The invited user is
forced to change it on first use (``User.must_change_password``).

Guarantees on the returned password:
  * length >= ``min_length`` (default 16, never below 12)
  * at least one lowercase, one uppercase, one digit and one special char
  * drawn from ``secrets`` (CSPRNG) — never ``random``
  * passes ``validate_password_policy`` (the platform's register/login policy)

The character pool intentionally excludes visually ambiguous characters
(``O/0``, ``l/1/I``) so a human can read the temporary password out of an
email without transcription errors.
"""

from __future__ import annotations

import secrets

# Ambiguous glyphs removed so the temp password is easy to read/type from email.
_LOWER = "abcdefghijkmnpqrstuvwxyz"      # no l
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"      # no I, O
_DIGITS = "23456789"                     # no 0, 1
# A conservative special-char set: unambiguous, shell/URL-safe enough for email,
# and accepted by the password policy (which only checks the lower/upper/digit
# classes, so any of these is fine).
_SPECIAL = "!@#$%*?-_+="

_ALL = _LOWER + _UPPER + _DIGITS + _SPECIAL

MIN_TEMP_PASSWORD_LENGTH = 12
DEFAULT_TEMP_PASSWORD_LENGTH = 16


def generate_temporary_password(length: int = DEFAULT_TEMP_PASSWORD_LENGTH) -> str:
    """Return a strong random password satisfying every character-class rule.

    ``length`` is clamped up to ``MIN_TEMP_PASSWORD_LENGTH`` so callers can
    never accidentally request a weak length.
    """
    if length < MIN_TEMP_PASSWORD_LENGTH:
        length = MIN_TEMP_PASSWORD_LENGTH

    # Seed one guaranteed char from each required class, then fill the rest from
    # the full pool. A final shuffle removes the positional bias of the seeds.
    chars = [
        secrets.choice(_LOWER),
        secrets.choice(_UPPER),
        secrets.choice(_DIGITS),
        secrets.choice(_SPECIAL),
    ]
    chars += [secrets.choice(_ALL) for _ in range(length - len(chars))]

    # secrets-backed Fisher-Yates shuffle (random.shuffle is NOT CSPRNG-safe).
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]

    return "".join(chars)
