"""Phase 4 — encrypted credentials + state scrub + log redaction tests.

Three blocks:

1. Encryption module — round-trip, missing-key failure, rotation.
2. CredentialsService — set/get/list/delete against an in-memory SQLite
   ``project_credentials`` table.
3. State + log redaction — secret keys are stripped from
   ``Task.workflow_state`` writes; the log filter masks recognisable
   secret shapes.

We do NOT exercise the HTTP routes here. Route-layer behaviour is
covered indirectly by the schema_guard + the project authz tests; the
behaviour worth pinning is the encryption invariant and the scrub.
"""

from __future__ import annotations

import logging
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core import encryption, log_redaction
from backend.app.models.credentials import ProjectCredential
from backend.app.services.core.credentials_service import (
    CredentialError,
    CredentialsService,
)
from backend.app.services.core.task_service import _sanitize_for_json


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def app_secret_key(monkeypatch):
    """Set APP_SECRET_KEY for the test, then clear the cached cipher.

    The encryption module caches the cipher with ``@lru_cache`` so the
    first call wins for the rest of the process. Tests that mutate the
    env var have to invalidate the cache, otherwise a later test sees
    the older key.

    We set BOTH the real env var (which ``_load_keys_from_env`` checks
    first) so the test is independent of whatever the developer happens
    to have in their local ``.env``.
    """
    key = encryption.generate_app_secret_key()
    monkeypatch.setenv("APP_SECRET_KEY", key)
    encryption.get_cipher.cache_clear()
    yield key
    encryption.get_cipher.cache_clear()


@pytest.fixture
def no_app_secret_key(monkeypatch):
    """Ensure APP_SECRET_KEY is unset for tests of the failure path.

    Clears the env var AND neutralises ``settings.APP_SECRET_KEY`` so a
    developer who has a key in their local ``.env`` (which pydantic loads
    into the settings singleton) doesn't accidentally make the
    missing-key test pass for the wrong reason.
    """
    from backend.app.core.config import settings
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    monkeypatch.setattr(settings, "APP_SECRET_KEY", "", raising=False)
    encryption.get_cipher.cache_clear()
    yield
    encryption.get_cipher.cache_clear()


@pytest.fixture
def db_session():
    """In-memory SQLite with the credentials table only.

    We deliberately do NOT call ``Base.metadata.create_all`` because the
    Project / User / Task models pull in JSONB which SQLite can't render.
    The credentials service only touches project_credentials, so creating
    that one table is sufficient.
    """
    engine = create_engine("sqlite:///:memory:")
    ProjectCredential.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


# ── Encryption module ──────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrips_the_plaintext(app_secret_key):
    ciphertext = encryption.encrypt_string("ghp_abcdef12345")
    assert ciphertext != "ghp_abcdef12345"
    assert encryption.decrypt_string(ciphertext) == "ghp_abcdef12345"


def test_two_encrypts_of_same_plaintext_produce_different_ciphertexts(app_secret_key):
    """Fernet includes a random IV per encrypt call — same input must
    produce different outputs so an attacker can't tell which rows hold
    the same secret by comparing ciphertexts."""
    a = encryption.encrypt_string("same-secret")
    b = encryption.encrypt_string("same-secret")
    assert a != b
    assert encryption.decrypt_string(a) == "same-secret"
    assert encryption.decrypt_string(b) == "same-secret"


def test_missing_master_key_raises(no_app_secret_key):
    """Without APP_SECRET_KEY the module refuses to fall back to a dev
    default. The route layer translates the raise into a 503."""
    with pytest.raises(encryption.MissingMasterKeyError):
        encryption.encrypt_string("x")


def test_malformed_master_key_raises(monkeypatch):
    """A malformed key fails loud at first use, not silently."""
    monkeypatch.setenv("APP_SECRET_KEY", "not-a-fernet-key")
    encryption.get_cipher.cache_clear()
    try:
        with pytest.raises(encryption.EncryptionError):
            encryption.encrypt_string("x")
    finally:
        encryption.get_cipher.cache_clear()


def test_decrypt_with_wrong_key_raises(monkeypatch):
    """A ciphertext from one key cannot be decrypted with another —
    catches the 'silently lost credentials after rotation' bug."""
    k1 = encryption.generate_app_secret_key()
    monkeypatch.setenv("APP_SECRET_KEY", k1)
    encryption.get_cipher.cache_clear()
    ct = encryption.encrypt_string("secret-A")
    # Rotate to a brand-new key (no overlap with k1)
    k2 = encryption.generate_app_secret_key()
    monkeypatch.setenv("APP_SECRET_KEY", k2)
    encryption.get_cipher.cache_clear()
    try:
        with pytest.raises(encryption.DecryptionError):
            encryption.decrypt_string(ct)
    finally:
        encryption.get_cipher.cache_clear()


def test_multikey_rotation_decrypts_with_either_key(monkeypatch):
    """Rotation contract: prepend the new key, the old one still decrypts
    historical ciphertexts. ``MultiFernet`` does this transparently."""
    k_old = encryption.generate_app_secret_key()
    k_new = encryption.generate_app_secret_key()

    monkeypatch.setenv("APP_SECRET_KEY", k_old)
    encryption.get_cipher.cache_clear()
    ct_old = encryption.encrypt_string("legacy-secret")

    monkeypatch.setenv("APP_SECRET_KEY", f"{k_new},{k_old}")
    encryption.get_cipher.cache_clear()
    try:
        # The old ciphertext still decrypts (key 2 in the list)
        assert encryption.decrypt_string(ct_old) == "legacy-secret"
        # A new encrypt uses k_new — drop k_old and the new ciphertext
        # must still decrypt (it was encrypted with k_new).
        ct_new = encryption.encrypt_string("post-rotation")
        monkeypatch.setenv("APP_SECRET_KEY", k_new)
        encryption.get_cipher.cache_clear()
        assert encryption.decrypt_string(ct_new) == "post-rotation"
    finally:
        encryption.get_cipher.cache_clear()


def test_mask_secret_keeps_only_tail():
    assert encryption.mask_secret("ghp_abcdef123456") == "••••••••3456"
    assert encryption.mask_secret("") == ""  # empty stays empty
    # Short inputs become all-bullets (don't leak the only thing we have)
    assert encryption.mask_secret("abc") == "••••••••"


# ── CredentialsService ─────────────────────────────────────────────────────


def test_set_credential_inserts_ciphertext_only(db_session, app_secret_key):
    row = CredentialsService.set_credential(
        db_session,
        project_id="p1",
        provider="github_pat",
        plaintext="ghp_top-secret-value",
        created_by="u1",
        label="repo X",
    )
    assert row.project_id == "p1"
    assert row.provider == "github_pat"
    # The plaintext MUST NOT appear in the stored payload
    assert "top-secret-value" not in row.encrypted_payload
    # The encrypted payload MUST round-trip
    assert encryption.decrypt_string(row.encrypted_payload) == "ghp_top-secret-value"


def test_set_credential_rotates_existing_row(db_session, app_secret_key):
    """Second set() with the same (project, provider) rotates the
    ciphertext in place — there must only ever be one row per pair."""
    CredentialsService.set_credential(
        db_session, project_id="p1", provider="github_pat",
        plaintext="old", created_by="u1",
    )
    CredentialsService.set_credential(
        db_session, project_id="p1", provider="github_pat",
        plaintext="new", created_by="u2",
    )
    rows = db_session.query(ProjectCredential).all()
    assert len(rows) == 1
    assert encryption.decrypt_string(rows[0].encrypted_payload) == "new"
    assert rows[0].updated_by == "u2"


def test_set_credential_rejects_empty_plaintext(db_session, app_secret_key):
    """A UX bug that submits an empty form value must NOT wipe an
    existing credential silently."""
    with pytest.raises(CredentialError):
        CredentialsService.set_credential(
            db_session, project_id="p1", provider="github_pat",
            plaintext="", created_by="u1",
        )


def test_get_credential_returns_decrypted_plaintext(db_session, app_secret_key):
    CredentialsService.set_credential(
        db_session, project_id="p1", provider="github_pat",
        plaintext="ghp_decrypt-me", created_by="u1",
    )
    assert CredentialsService.get_credential(
        db_session, project_id="p1", provider="github_pat",
    ) == "ghp_decrypt-me"


def test_get_credential_returns_none_when_missing(db_session, app_secret_key):
    assert CredentialsService.get_credential(
        db_session, project_id="p_none", provider="github_pat",
    ) is None


def test_delete_credential_removes_row(db_session, app_secret_key):
    CredentialsService.set_credential(
        db_session, project_id="p1", provider="github_pat",
        plaintext="to-be-deleted", created_by="u1",
    )
    removed = CredentialsService.delete_credential(
        db_session, project_id="p1", provider="github_pat",
    )
    assert removed is True
    assert db_session.query(ProjectCredential).count() == 0


def test_delete_credential_is_idempotent(db_session, app_secret_key):
    """Deleting a non-existent credential returns False, never raises."""
    assert CredentialsService.delete_credential(
        db_session, project_id="p_none", provider="github_pat",
    ) is False


def test_has_credential_does_not_decrypt(db_session, app_secret_key, monkeypatch):
    """``has_credential`` is a cheap existence probe — must not call the
    decryption layer."""
    CredentialsService.set_credential(
        db_session, project_id="p1", provider="github_pat",
        plaintext="x", created_by="u1",
    )

    # Trap any decrypt call to prove has_credential doesn't trigger it.
    called = {"decrypt": 0}
    original_decrypt = encryption.decrypt_string

    def _spy(ct):
        called["decrypt"] += 1
        return original_decrypt(ct)

    monkeypatch.setattr(encryption, "decrypt_string", _spy)

    assert CredentialsService.has_credential(
        db_session, project_id="p1", provider="github_pat",
    )
    assert called["decrypt"] == 0


# ── State scrub (TaskService._sanitize_for_json) ───────────────────────────


def test_sanitize_strips_top_level_github_token():
    """The canonical case from the audit — a github_token at the top
    level of state must NOT survive the JSON sanitize pass."""
    raw = {"github_token": "ghp_xxx", "current_phase": "planning"}
    cleaned = _sanitize_for_json(raw)
    assert "github_token" not in cleaned
    assert cleaned["current_phase"] == "planning"


def test_sanitize_strips_nested_github_token():
    """Defence in depth: a secret nested under any key, at any depth,
    must also be stripped."""
    raw = {
        "auth": {"github_token": "ghp_xxx", "username": "alice"},
        "deep": {"nested": {"github_token": "ghp_yyy"}},
    }
    cleaned = _sanitize_for_json(raw)
    assert "github_token" not in cleaned["auth"]
    assert cleaned["auth"]["username"] == "alice"
    assert "github_token" not in cleaned["deep"]["nested"]


def test_sanitize_strips_aws_keys():
    """AWS access keys MUST never reach workflow_state — same scrub as
    GitHub PATs."""
    raw = {
        "aws_access_key_id": "AKIATEST123",
        "aws_secret_access_key": "secret",
        "aws_session_token": "session",
        "harmless": "value",
    }
    cleaned = _sanitize_for_json(raw)
    assert "aws_access_key_id" not in cleaned
    assert "aws_secret_access_key" not in cleaned
    assert "aws_session_token" not in cleaned
    assert cleaned["harmless"] == "value"


def test_sanitize_is_case_insensitive():
    """A contributor typing ``Github_Token`` must not be able to bypass
    the scrub — the keyset is compared case-insensitively."""
    raw = {"Github_Token": "ghp_xxx", "PASSWORD": "p"}
    cleaned = _sanitize_for_json(raw)
    assert "Github_Token" not in cleaned
    assert "PASSWORD" not in cleaned


def test_sanitize_preserves_lists():
    """Lists are preserved (and recursively scrubbed) — a regression
    here would silently drop logs entries."""
    raw = {
        "logs": [
            {"step": "x", "message": "ok"},
            {"step": "y", "github_token": "ghp_x"},  # scrubbed
        ],
    }
    cleaned = _sanitize_for_json(raw)
    assert cleaned["logs"][0] == {"step": "x", "message": "ok"}
    assert cleaned["logs"][1] == {"step": "y"}


# ── Log redaction ──────────────────────────────────────────────────────────


def test_redact_masks_github_classic_pat():
    line = "cloning with token=ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
    redacted = log_redaction.redact(line)
    assert "ghp_aBcDeFgHi" not in redacted
    assert "REDACTED" in redacted


def test_redact_masks_aws_access_key_id():
    redacted = log_redaction.redact("AWS key AKIAIOSFODNN7EXAMPLE used")
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "REDACTED" in redacted


def test_redact_masks_jwt():
    jwt_like = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.signature_part_here"
    redacted = log_redaction.redact(f"Authorization is {jwt_like}")
    assert jwt_like not in redacted


def test_redact_masks_bearer_header():
    redacted = log_redaction.redact("Authorization: Bearer ghp_secret123abc")
    assert "ghp_secret123abc" not in redacted
    # The header LABEL is preserved so log readers still see the shape
    assert "Authorization" in redacted
    assert "Bearer" in redacted


def test_redact_is_idempotent_on_already_masked_text():
    once = log_redaction.redact("AKIAIOSFODNN7EXAMPLE")
    twice = log_redaction.redact(once)
    assert once == twice


def test_filter_rewrites_logrecord_msg(caplog):
    """End-to-end: a logger.info(token) call must NOT emit the token."""
    log_redaction.reset_for_tests()
    log_redaction.install_secret_redactor()
    try:
        logger = logging.getLogger("test_phase4")
        with caplog.at_level(logging.INFO, logger="test_phase4"):
            logger.info("AWS key AKIAIOSFODNN7EXAMPLE was used")
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "AKIAIOSFODNN7EXAMPLE" not in joined
        assert "REDACTED" in joined
    finally:
        log_redaction.reset_for_tests()


def test_filter_does_not_crash_on_non_string_args(caplog):
    """A defensive: args containing ints / objects must not break
    redaction. The filter is best-effort — failing closed would drop logs
    during an incident, which is worse than emitting raw."""
    log_redaction.reset_for_tests()
    log_redaction.install_secret_redactor()
    try:
        logger = logging.getLogger("test_phase4_args")
        with caplog.at_level(logging.INFO, logger="test_phase4_args"):
            logger.info("answer is %d for %s", 42, "alice")
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "42" in joined
    finally:
        log_redaction.reset_for_tests()


def test_install_redactor_is_idempotent():
    """Calling install twice must not stack duplicate filters on root.

    Stacking would redact each message N times — harmless for output but
    wastes CPU and makes debugging the filter tedious."""
    log_redaction.reset_for_tests()
    log_redaction.install_secret_redactor()
    log_redaction.install_secret_redactor()
    log_redaction.install_secret_redactor()
    try:
        root = logging.getLogger()
        filters = [f for f in root.filters if isinstance(f, log_redaction.SecretRedactingFilter)]
        assert len(filters) == 1
    finally:
        log_redaction.reset_for_tests()
