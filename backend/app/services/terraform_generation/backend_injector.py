"""
Deterministic backend.tf generator.

Why this exists
---------------
TerraformAgent previously asked the LLM to produce ``backend.tf`` along with
the rest of the project. That produces hallucinated S3 bucket names and lock
table names — ``terraform init`` then fails before the user can even read
the diff. State-bucket misconfiguration is also the #1 cause of state
corruption in production: two concurrent task runs pointed at the same key
will race.

This module emits backend.tf from a typed, machine-controlled config. The
LLM is no longer involved.

Pre-launch setup (operator responsibility, outside the platform repo)
---------------------------------------------------------------------
1. Create a single management AWS account.
2. ``aws s3api create-bucket --bucket <state-bucket>`` with versioning + SSE-KMS.
3. ``aws dynamodb create-table`` for the lock table (PK = LockID, on-demand).
4. Block public access on the bucket.
5. Set ``TF_STATE_BUCKET``, ``TF_STATE_REGION``, ``TF_STATE_LOCK_TABLE`` env vars.

Until those env vars are present, ``render_backend_tf`` raises so we never
silently fall back to "use the LLM's guess".
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional


_BUCKET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")
_AWS_REGION_RE = re.compile(r"^[a-z]{2}-[a-z]+-\d+$")
_DYNAMO_TABLE_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,255}$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


@dataclass(frozen=True)
class BackendConfig:
    """Typed inputs that flow into backend.tf. No defaults — every field required."""

    bucket: str
    region: str
    lock_table: str
    task_id: str
    kms_key_id: Optional[str] = None  # optional SSE-KMS override

    def __post_init__(self) -> None:
        if not _BUCKET_NAME_RE.match(self.bucket):
            raise ValueError(f"Invalid S3 bucket name: {self.bucket!r}")
        if not _AWS_REGION_RE.match(self.region):
            raise ValueError(f"Invalid AWS region: {self.region!r}")
        if not _DYNAMO_TABLE_RE.match(self.lock_table):
            raise ValueError(f"Invalid DynamoDB table name: {self.lock_table!r}")
        if not _TASK_ID_RE.match(self.task_id):
            raise ValueError(
                f"Invalid task_id (must match {_TASK_ID_RE.pattern}): {self.task_id!r}"
            )

    @property
    def state_key(self) -> str:
        """Per-task state key. Two concurrent workflows can never collide."""
        return f"tasks/{self.task_id}/terraform.tfstate"


def backend_config_from_env(task_id: str) -> BackendConfig:
    """
    Build a BackendConfig from environment variables.

    Raises ``RuntimeError`` if the operator has not provisioned the management
    bucket/table yet — we deliberately refuse to fall back to LLM-generated
    backend.tf, which is the unrecoverable failure mode this module exists
    to prevent.
    """
    bucket = os.getenv("TF_STATE_BUCKET")
    region = os.getenv("TF_STATE_REGION")
    table = os.getenv("TF_STATE_LOCK_TABLE")
    kms = os.getenv("TF_STATE_KMS_KEY_ID") or None
    missing = [
        name
        for name, value in (
            ("TF_STATE_BUCKET", bucket),
            ("TF_STATE_REGION", region),
            ("TF_STATE_LOCK_TABLE", table),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Cannot emit backend.tf: missing environment variable(s): "
            + ", ".join(missing)
            + ". Provision the management S3 bucket + DynamoDB lock table "
            "(see backend_injector module docstring) and set TF_STATE_* env vars."
        )
    return BackendConfig(
        bucket=bucket,  # type: ignore[arg-type]
        region=region,  # type: ignore[arg-type]
        lock_table=table,  # type: ignore[arg-type]
        task_id=task_id,
        kms_key_id=kms,
    )


def render_backend_tf(config: BackendConfig) -> str:
    """
    Emit the HCL string for backend.tf. Pure function — same config in,
    same output. No template engine, no LLM. Safe to call from anywhere.
    """
    kms_line = f'\n    kms_key_id     = "{config.kms_key_id}"' if config.kms_key_id else ""
    return f"""# AUTO-GENERATED — DO NOT EDIT.
# Emitted by backend_injector.py. The LLM is forbidden from touching this file.
# State key is keyed by task_id so concurrent workflows never share state.

terraform {{
  backend "s3" {{
    bucket         = "{config.bucket}"
    key            = "{config.state_key}"
    region         = "{config.region}"
    dynamodb_table = "{config.lock_table}"
    encrypt        = true{kms_line}
  }}
}}
"""
