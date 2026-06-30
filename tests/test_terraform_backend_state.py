"""
Backend remote-state contract (backend_injector).

These tests lock down the production-readiness guarantees of the Terraform
remote state:

* state is keyed by ``project_id`` (isolated + persistent across runs);
* the emitted HCL is a real S3 backend with DynamoDB locking + encryption;
* missing TF_STATE_* env vars are a HARD failure — never a placeholder.

The autouse ``_terraform_backend_env`` fixture (tests/conftest.py) supplies the
management-account env vars; individual tests override via ``monkeypatch``.
"""

from __future__ import annotations

import pytest

from backend.app.services.terraform_generation.backend_injector import (
    BackendConfig,
    BackendConfigurationError,
    backend_config_from_env,
    render_backend_tf,
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
