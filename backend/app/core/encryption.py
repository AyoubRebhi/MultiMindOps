"""Symmetric encryption for project credentials.

What this module does
---------------------
Wraps ``cryptography.fernet.Fernet`` (AES-128-CBC + HMAC-SHA256 + IV) into
a tiny, opinionated API the credentials layer uses to store secrets at
rest. Fernet was chosen over hand-rolled AES-GCM because:

* it bundles authenticated encryption, IV management, and rotation into
  one well-audited primitive;
* the ciphertext is URL-safe base64, so it fits inside a TEXT column
  without binary-encoding gymnastics;
* the key format is a single 32-byte url-safe-base64 string, simple
  enough to load from one env var and ship between environments without
  ambiguity.

Key bootstrap
-------------
The platform requires the operator to set ``APP_SECRET_KEY`` to a
Fernet-format key (44 chars of url-safe base64). Two helpers:

* :func:`generate_app_secret_key` — emit a fresh one (used by operators
  + the test suite). Never call this at runtime to "fix" a missing
  configuration — see ``get_cipher()`` below.

* :func:`get_cipher` — return the process-wide Fernet instance. Raises
  :class:`MissingMasterKeyError` if ``APP_SECRET_KEY`` is unset; refuses
  to silently fall back to a "dev" key, because a dev key in production
  leaks every credential the moment the source tree is published.

Rotation
--------
Multi-key Fernet (``MultiFernet``) is supported by passing a comma-
separated list in ``APP_SECRET_KEY``: ``newest,older1,older2``.
Encryption always uses the first key; decryption tries each in order.
That lets an operator rotate by prepending a fresh key, waiting for the
re-encrypt pass to migrate ciphertexts, then removing the old key.
"""

from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache
from typing import Tuple

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    """Base class for encryption-layer failures."""


class MissingMasterKeyError(EncryptionError):
    """``APP_SECRET_KEY`` is unset or malformed.

    Raised at first-use rather than at import time so the test suite —
    which deliberately runs without a key when exercising error paths —
    can stub the env var inside individual tests.
    """


class DecryptionError(EncryptionError):
    """Ciphertext failed to decrypt under every available key.

    This is the "wrong key / corrupted token / tampered ciphertext" path.
    The caller decides whether to treat as a recoverable user error
    (re-prompt for credentials) or a fatal one (alert ops). We do NOT
    leak the underlying ``InvalidToken`` detail because it carries no
    actionable signal beyond "couldn't decrypt".
    """


def generate_app_secret_key() -> str:
    """Emit a fresh Fernet key (44-char url-safe base64).

    Operator-facing helper, also called from the test suite. Never call
    this at runtime to substitute for a missing config — ``get_cipher``
    raises in that case on purpose so the failure is loud.
    """
    return Fernet.generate_key().decode("ascii")


def _load_keys_from_env() -> Tuple[str, ...]:
    """Return the configured key list in priority order.

    Comma-separated to support rotation. Trimmed/empty entries are
    dropped — a trailing comma in the env var is a configuration typo,
    not an intentional "no key here".

    Source precedence:
      1. ``os.environ["APP_SECRET_KEY"]`` — a real environment variable or
         a test monkeypatch. Checked first so tests and container env vars
         win deterministically.
      2. ``settings.APP_SECRET_KEY`` — loaded by pydantic-settings from the
         ``.env`` file. pydantic does NOT push ``.env`` values into
         ``os.environ``, so without this fallback an operator who puts the
         key in ``.env`` (like every other secret) would be ignored.
    """
    raw = (os.environ.get("APP_SECRET_KEY") or "").strip()
    if not raw:
        # Import lazily to avoid a config↔encryption import cycle at module
        # load time (config is imported very early in the boot sequence).
        try:
            from backend.app.core.config import settings
            raw = (settings.APP_SECRET_KEY or "").strip()
        except Exception:
            raw = ""
    if not raw:
        return ()
    keys = tuple(part.strip() for part in raw.split(",") if part.strip())
    return keys


@lru_cache(maxsize=1)
def get_cipher() -> MultiFernet:
    """Return the process-wide cipher, building it lazily on first use.

    Cached because :class:`Fernet` initialisation is cheap but happens
    on every encrypt/decrypt call without it; and because hot-swapping
    keys mid-process would be a serious correctness hazard — operators
    must restart to rotate.

    Raises
    ------
    MissingMasterKeyError
        ``APP_SECRET_KEY`` is unset. The boot path catches this and
        either fails fast (production) or warns + skips the credential
        subsystem (development with no credentials configured).
    EncryptionError
        ``APP_SECRET_KEY`` is malformed — wrong length or not base64.
    """
    keys = _load_keys_from_env()
    if not keys:
        raise MissingMasterKeyError(
            "APP_SECRET_KEY is not set. Generate one with "
            "`python -c \"from backend.app.core.encryption import "
            "generate_app_secret_key; print(generate_app_secret_key())\"` "
            "and set it in .env (or the deployment secret store)."
        )

    try:
        ciphers = [Fernet(k.encode("ascii")) for k in keys]
    except (ValueError, TypeError) as exc:
        # Fernet raises ValueError on bad base64 / wrong length.
        raise EncryptionError(
            f"APP_SECRET_KEY is malformed: {exc}. Expected a comma-separated "
            "list of 44-char url-safe base64 Fernet keys."
        ) from exc

    return MultiFernet(ciphers)


def encrypt_string(plaintext: str) -> str:
    """Encrypt a UTF-8 string and return a url-safe-base64 ciphertext.

    Round-trip with :func:`decrypt_string`. The output is ASCII-safe so
    it stores cleanly in TEXT columns and travels through JSON without
    base64-of-base64 gymnastics.
    """
    if plaintext is None:
        raise EncryptionError("Cannot encrypt None — pass an empty string instead")
    cipher = get_cipher()
    token = cipher.encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_string(ciphertext: str) -> str:
    """Decrypt a token produced by :func:`encrypt_string`.

    Raises :class:`DecryptionError` on any failure. The caller should
    NEVER include the original ciphertext in a user-facing error — it
    is server-side opaque data and may leak rotation history if echoed
    back.
    """
    if not ciphertext:
        raise DecryptionError("Cannot decrypt an empty ciphertext")
    cipher = get_cipher()
    try:
        return cipher.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "Ciphertext could not be decrypted under any configured key. "
            "Either the value was encrypted with a different APP_SECRET_KEY, "
            "or it is corrupted."
        ) from exc


# ── Diagnostic helpers ──────────────────────────────────────────────────────


def is_configured() -> bool:
    """Return True iff ``APP_SECRET_KEY`` is set and parseable.

    Boot uses this to decide whether to log a setup hint vs. crashing —
    the goal is "always fail loud in prod, never fail silent in dev".
    """
    try:
        get_cipher()
        return True
    except (MissingMasterKeyError, EncryptionError):
        return False


def mask_secret(value: str, *, visible_tail: int = 4) -> str:
    """Render a secret for human display without revealing it.

    ``"ghp_abc123xyz789"`` → ``"••••••••••••z789"``. Used by the
    credentials API to echo back a recognisable-but-useless preview so
    operators can identify which credential is which without ever seeing
    the plaintext after they set it.

    Empty input returns an empty string — leaking a fixed bullet string
    would falsely imply a credential exists.
    """
    if not value:
        return ""
    if len(value) <= visible_tail:
        # The value is too short to safely show any of it without
        # exposing the whole secret — return only bullets.
        return "•" * 8
    return "•" * 8 + value[-visible_tail:]


# Cryptographic equality helper — useful for tests that want to compare
# two ciphertexts of the same plaintext (which must NOT be equal because
# each call uses a fresh IV).
def _constant_time_eq(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
