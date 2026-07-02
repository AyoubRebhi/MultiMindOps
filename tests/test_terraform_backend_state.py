"""
Backend remote-state contract (backend_injector).

Remote S3 state is OPTIONAL. These tests lock down both modes:

* ENTERPRISE (TF_STATE_* set) — state keyed by ``project_id``; the emitted HCL is
  a real S3 backend with DynamoDB locking + encryption. ``backend_config_from_env``
  raises if the S3 backend is requested but mis-configured (logic unchanged).
* DEFAULT/MVP (TF_STATE_* unset) — ``remote_backend_configured()`` is False and
  ``render_local_backend_tf()`` emits a functional local backend.

The autouse ``_terraform_backend_env`` fixture (tests/conftest.py) supplies the
management-account env vars; individual tests override via ``monkeypatch``.
"""

from __future__ import annotations

import pytest

from backend.app.services.terraform_generation.backend_injector import (
    BackendConfig,
    BackendConfigurationError,
    backend_config_from_env,
    remote_backend_configured,
    render_backend_tf,
    render_local_backend_tf,
)


def test_state_key_embeds_project_id() -> None:
    cfg = BackendConfig(
        bucket="multimindops-tf-state",
        region="us-east-1",
        lock_table="multimindops-tf-locks",
        project_id="proj-42",
    )
    assert cfg.state_key == "projects/proj-42/terraform.tfstate"


def test_render_backend_tf_emits_s3_backend_with_locking() -> None:
    cfg = backend_config_from_env("proj-42")
    hcl = render_backend_tf(cfg)
    assert 'backend "s3"' in hcl
    assert 'bucket         = "multimindops-tf-state"' in hcl
    assert 'key            = "projects/proj-42/terraform.tfstate"' in hcl
    assert 'region         = "us-east-1"' in hcl
    assert 'dynamodb_table = "multimindops-tf-locks"' in hcl
    assert "encrypt        = true" in hcl


def test_two_projects_get_isolated_state_keys() -> None:
    a = render_backend_tf(backend_config_from_env("proj-a"))
    b = render_backend_tf(backend_config_from_env("proj-b"))
    assert "projects/proj-a/terraform.tfstate" in a
    assert "projects/proj-b/terraform.tfstate" in b
    assert a != b


@pytest.mark.parametrize(
    "missing", ["TF_STATE_BUCKET", "TF_STATE_REGION", "TF_STATE_LOCK_TABLE"]
)
def test_missing_env_var_raises(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(BackendConfigurationError) as exc:
        backend_config_from_env("proj-1")
    assert missing in str(exc.value)


def test_optional_kms_key_is_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TF_STATE_KMS_KEY_ID", "arn:aws:kms:us-east-1:1:key/abc")
    hcl = render_backend_tf(backend_config_from_env("proj-1"))
    assert "kms_key_id" in hcl


def test_invalid_bucket_name_rejected() -> None:
    with pytest.raises(BackendConfigurationError):
        BackendConfig(
            bucket="Invalid_Bucket_NAME",  # uppercase + underscores are illegal
            region="us-east-1",
            lock_table="locks",
            project_id="proj-1",
        )


# ── Optional remote state: mode detection + local backend (default/MVP) ──────


def test_remote_backend_configured_true_when_all_env_present() -> None:
    # The autouse fixture sets all three TF_STATE_* vars.
    assert remote_backend_configured() is True


@pytest.mark.parametrize(
    "missing", ["TF_STATE_BUCKET", "TF_STATE_REGION", "TF_STATE_LOCK_TABLE"]
)
def test_remote_backend_not_configured_when_any_env_missing(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing, raising=False)
    assert remote_backend_configured() is False


def test_local_backend_is_functional_not_placeholder() -> None:
    hcl = render_local_backend_tf()
    assert 'backend "local"' in hcl
    assert 'backend "s3"' not in hcl
    assert "placeholder" not in hcl.lower()
    # No required_version here (providers.tf already declares it) → no conflict.
    assert "required_version" not in hcl
