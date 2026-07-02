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

Per-project state isolation (the destroy fix)
---------------------------------------------
The state object is keyed by ``project_id``::

    projects/<project-id>/terraform.tfstate

This is the single most important property of this module:

* It is **stable across runs**. Every GitHub Actions run for a project — the
  bootstrap that creates infrastructure and the destroy that tears it down —
  points at the SAME remote state object. ``terraform destroy`` therefore sees
  exactly what ``terraform apply`` created, instead of starting from empty
  local state on a throwaway runner (which is why destroy used to remove 0
  resources and bootstrap re-runs hit "AlreadyExists").
* It is **isolated per project**. Two projects can never share or corrupt each
  other's state, and DynamoDB locking on the shared table serialises concurrent
  operations on the same key.

Two modes (remote state is OPTIONAL)
------------------------------------
* **Default / MVP** — ``TF_STATE_*`` env vars are NOT set. ``backend.tf`` declares
  a **local** backend. Generation always succeeds; the project works with plain
  ``terraform init`` / ``terraform apply`` and needs no platform-managed infra.
* **Enterprise** — all three of ``TF_STATE_BUCKET`` / ``TF_STATE_REGION`` /
  ``TF_STATE_LOCK_TABLE`` are set. ``backend.tf`` declares the per-project S3
  backend with DynamoDB locking (the logic below — unchanged).

``backend_config_from_env`` still raises ``BackendConfigurationError`` when the
S3 backend is requested but mis-/under-configured — but it is only called once the
caller has confirmed (via :func:`remote_backend_configured`) that enterprise mode
is in effect, so missing env vars no longer block generation; they select the
local backend instead.

Pre-launch setup for ENTERPRISE mode (operator responsibility)
--------------------------------------------------------------
1. Create a single management AWS account.
2. ``aws s3api create-bucket --bucket <state-bucket>`` with versioning + SSE-KMS.
3. ``aws dynamodb create-table`` for the lock table (PK = LockID, on-demand).
4. Block public access on the bucket.
5. Set ``TF_STATE_BUCKET``, ``TF_STATE_REGION``, ``TF_STATE_LOCK_TABLE`` env vars.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional


_BUCKET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")
_AWS_REGION_RE = re.compile(r"^[a-z]{2}-[a-z]+-\d+$")
_DYNAMO_TABLE_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,255}$")
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")

# The three env vars that switch on enterprise (remote S3) state.
_REMOTE_STATE_ENV_VARS = ("TF_STATE_BUCKET", "TF_STATE_REGION", "TF_STATE_LOCK_TABLE")

# Local backend.tf — the default/MVP mode. A real, functional local backend (not
# a placeholder): `terraform init` + `terraform apply` work with zero
# platform-managed infrastructure. No `required_version` here so it never
# conflicts with the one already declared in providers.tf.
_LOCAL_BACKEND_TF = """# AUTO-GENERATED — DO NOT EDIT.
# No remote backend configured — using LOCAL Terraform state. `terraform init`
# and `terraform apply` work without any platform-managed infrastructure. Set
# TF_STATE_BUCKET / TF_STATE_REGION / TF_STATE_LOCK_TABLE to enable the S3 backend.

terraform {
  backend "local" {}
}
"""


def remote_backend_configured() -> bool:
    """True when ALL ``TF_STATE_*`` env vars are set (enterprise mode is active).

    This is the switch between the two modes: when it returns False the platform
    emits a local backend and generation continues; it never raises.
    """
    return all(os.getenv(name) for name in _REMOTE_STATE_ENV_VARS)


def render_local_backend_tf() -> str:
    """Emit the local (default/MVP) ``backend.tf``. Pure, deterministic."""
    return _LOCAL_BACKEND_TF


class BackendConfigurationError(RuntimeError):
    """Raised when the remote-state backend cannot be configured.

    Subclasses ``RuntimeError`` so existing ``except RuntimeError`` sites keep
    working, while giving callers a precise type to catch. This is raised
    *instead of* ever emitting a placeholder backend — a missing or invalid
    backend is a hard, unrecoverable generation failure, not a development
    convenience.
    """


@dataclass(frozen=True)
class BackendConfig:
    """Typed inputs that flow into backend.tf. No defaults — every field required."""

    bucket: str
    region: str
    lock_table: str
    project_id: str
    kms_key_id: Optional[str] = None  # optional SSE-KMS override

    def __post_init__(self) -> None:
        if not _BUCKET_NAME_RE.match(self.bucket):
            raise BackendConfigurationError(f"Invalid S3 state bucket name: {self.bucket!r}")
        if not _AWS_REGION_RE.match(self.region):
            raise BackendConfigurationError(f"Invalid AWS region: {self.region!r}")
        if not _DYNAMO_TABLE_RE.match(self.lock_table):
            raise BackendConfigurationError(
                f"Invalid DynamoDB lock table name: {self.lock_table!r}"
            )
        if not _PROJECT_ID_RE.match(self.project_id):
            raise BackendConfigurationError(
                f"Invalid project_id (must match {_PROJECT_ID_RE.pattern}): {self.project_id!r}"
            )

    @property
    def state_key(self) -> str:
        """Per-project state key. Stable across runs (bootstrap + destroy share
        it) and isolated so two projects can never collide."""
        return f"projects/{self.project_id}/terraform.tfstate"


def backend_config_from_env(project_id: str) -> BackendConfig:
    """
    Build a BackendConfig from environment variables for ``project_id``.

    Raises ``BackendConfigurationError`` if the operator has not provisioned the
    management bucket/table yet — we deliberately refuse to fall back to a
    placeholder or LLM-generated backend, the unrecoverable failure modes this
    module exists to prevent.
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
        raise BackendConfigurationError(
            "Cannot emit backend.tf: missing environment variable(s): "
            + ", ".join(missing)
            + ". Provision the management S3 bucket + DynamoDB lock table "
            "(see backend_injector module docstring) and set TF_STATE_* env vars."
        )
    if not project_id:
        raise BackendConfigurationError(
            "Cannot emit backend.tf: project_id is required for per-project state "
            "isolation (state key = projects/<project-id>/terraform.tfstate)."
        )
    # Field-format validation (incl. project_id) happens in BackendConfig.__post_init__.
    return BackendConfig(
        bucket=bucket,  # type: ignore[arg-type]
        region=region,  # type: ignore[arg-type]
        lock_table=table,  # type: ignore[arg-type]
        project_id=project_id,
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
# State is keyed by project_id so every project has an isolated, PERSISTENT
# remote state. Re-running bootstrap or destroy reuses the SAME state object,
# which is what makes `terraform destroy` actually tear down what was created.

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
