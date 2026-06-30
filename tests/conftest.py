"""Shared pytest fixtures for the platform test-suite.

Terraform generation now REQUIRES a real S3 remote-state backend — it refuses
to emit a placeholder when the ``TF_STATE_*`` environment variables are unset
(see ``backend_injector``). The autouse fixture below stands in for an operator
who has provisioned the management S3 bucket + DynamoDB lock table, so renderer
tests exercise the real backend path. Tests that want to assert the
"backend unavailable" failure simply ``monkeypatch.delenv`` these inside the
test body.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _terraform_backend_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide the management-account backend config for the whole suite."""
    monkeypatch.setenv("TF_STATE_BUCKET", "multimindops-tf-state")
    monkeypatch.setenv("TF_STATE_REGION", "us-east-1")
    monkeypatch.setenv("TF_STATE_LOCK_TABLE", "multimindops-tf-locks")
