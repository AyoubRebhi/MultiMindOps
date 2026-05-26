"""Password policy + hashing tests.

These are pure unit tests — no DB, no HTTP. We don't validate bcrypt's
own cryptographic claims, only that our wrapper enforces the policy
and round-trips a hash correctly.
"""

from __future__ import annotations

import pytest

from backend.app.core.passwords import (
    PasswordPolicyError,
    hash_password,
    validate_password_policy,
    verify_password,
)


# ── Policy ─────────────────────────────────────────────────────────────────

def test_policy_accepts_strong_password():
    # Single-line policy spec: 8+ chars, lower + upper + digit.
    validate_password_policy("StrongPass1")


@pytest.mark.parametrize(
    "bad",
    [
        "short1A",                # too short
        "alllowercase1",          # missing uppercase
        "ALLUPPERCASE1",          # missing lowercase
        "NoDigitHere",            # missing digit
        "",                       # empty
    ],
)
def test_policy_rejects_weak_passwords(bad):
    with pytest.raises(PasswordPolicyError):
        validate_password_policy(bad)


def test_policy_rejects_oversized_password():
    # bcrypt silently truncates above 72 bytes — we surface a policy error.
    too_long = "A1" + ("a" * 80)
    with pytest.raises(PasswordPolicyError):
        validate_password_policy(too_long)


# ── Hash + verify ──────────────────────────────────────────────────────────

def test_hash_password_returns_distinct_hash_each_time():
    """Bcrypt salts each hash — two hashes of the same password differ."""
    h1 = hash_password("StrongPass1")
    h2 = hash_password("StrongPass1")
    assert h1 != h2


def test_verify_password_round_trip():
    h = hash_password("StrongPass1")
    assert verify_password("StrongPass1", h) is True
    assert verify_password("WrongPass1", h) is False


def test_verify_password_handles_none_and_empty_hash():
    """The 'no hash on file' path returns False, never raises."""
    assert verify_password("StrongPass1", None) is False
    assert verify_password("StrongPass1", "") is False
    assert verify_password("", "anyhash") is False


def test_verify_password_does_not_raise_on_malformed_hash():
    """A corrupted hash should be treated as a failed verify, not an exception."""
    assert verify_password("StrongPass1", "not-a-bcrypt-hash") is False
