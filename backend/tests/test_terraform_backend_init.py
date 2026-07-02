"""Backend-aware ``terraform init`` selection (validate + plan executors).

The validate/plan executors must inspect the generated Terraform config and
choose the ``terraform init`` flavour automatically:

* no backend block  → keep the historical ``-backend=false`` init (never touch a
  real backend, need no credentials);
* any backend block → run a real (``-reconfigure``) init so the declared backend
  (``local`` OR ``s3``) is actually initialised.

These regression tests lock that selection down for all three required cases —
(1) no backend, (2) local backend, (3) S3 backend — without a terraform binary:
they exercise the pure detection + step-builder functions that both the blocking
``TerraformPipelineService`` and the streamed workflow handlers consume. The
local/S3 backend HCL is produced by the REAL ``backend_injector`` so the test is
tied to the actual generated output.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from backend.app.services.terraform_generation.backend_injector import (
    BackendConfig,
    render_backend_tf,
    render_local_backend_tf,
)
from backend.app.services.terraform_pipeline.pipeline_service import (
    build_plan_steps,
    build_validate_steps,
    config_declares_backend,
    directory_declares_backend,
    terraform_init_args,
)

# ── Representative .tf content ───────────────────────────────────────────────

# providers.tf declares a ``terraform {}`` block but NO backend — the classic
# "no backend" case where the executors must keep ``-backend=false``.
_PROVIDERS_TF = """terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}
"""

# Real generated backends (backend_injector is the single source of truth).
_LOCAL_BACKEND_TF = render_local_backend_tf()
_S3_BACKEND_TF = render_backend_tf(
    BackendConfig(
        bucket="multimindops-tf-state",
        region="us-east-1",
        lock_table="multimindops-tf-locks",
        project_id="proj-42",
    )
)


def _write(dirpath: Path, files: Dict[str, str]) -> Path:
    for name, content in files.items():
        (dirpath / name).write_text(content, encoding="utf-8")
    return dirpath


# (id, files-on-disk, expects a real backend-initialising init) ──────────────
_CASES = [
    ("no_backend", {"providers.tf": _PROVIDERS_TF}, False),
    ("local_backend", {"providers.tf": _PROVIDERS_TF, "backend.tf": _LOCAL_BACKEND_TF}, True),
    ("s3_backend", {"providers.tf": _PROVIDERS_TF, "backend.tf": _S3_BACKEND_TF}, True),
]
_CASE_IDS = [c[0] for c in _CASES]


# ── config_declares_backend (single-file detection) ──────────────────────────


def test_config_no_backend_is_false() -> None:
    assert config_declares_backend(_PROVIDERS_TF) is False
    assert config_declares_backend("") is False


def test_config_local_backend_is_true() -> None:
    # Sanity-check the fixture really is a local backend, then detect it.
    assert 'backend "local"' in _LOCAL_BACKEND_TF
    assert config_declares_backend(_LOCAL_BACKEND_TF) is True


def test_config_s3_backend_is_true() -> None:
    assert 'backend "s3"' in _S3_BACKEND_TF
    assert config_declares_backend(_S3_BACKEND_TF) is True


def test_commented_out_backend_does_not_count() -> None:
    """A commented-out backend must NOT trigger a real init."""
    hcl = """terraform {
  # backend "s3" {}
  // backend "local" {}
  /* backend "gcs" {
       bucket = "x"
     } */
}
"""
    assert config_declares_backend(hcl) is False


# ── terraform_init_args (flavour selection) ──────────────────────────────────


def test_init_args_no_backend_forces_backend_false() -> None:
    assert terraform_init_args(declares_backend=False) == [
        "init",
        "-backend=false",
        "-input=false",
        "-no-color",
    ]


def test_init_args_with_backend_runs_real_reconfigure_init() -> None:
    args = terraform_init_args(declares_backend=True)
    assert args == ["init", "-reconfigure", "-input=false", "-no-color"]
    assert "-backend=false" not in args


# ── directory_declares_backend (the three required cases) ────────────────────


@pytest.mark.parametrize("_id, files, real_init", _CASES, ids=_CASE_IDS)
def test_directory_detection(
    tmp_path: Path, _id: str, files: Dict[str, str], real_init: bool
) -> None:
    _write(tmp_path, files)
    assert directory_declares_backend(tmp_path) is real_init


def test_missing_directory_defaults_to_no_backend(tmp_path: Path) -> None:
    """A missing/empty artifact dir → treat as no backend (safe ``-backend=false``)."""
    missing = tmp_path / "does-not-exist"
    assert directory_declares_backend(missing) is False
    assert directory_declares_backend(tmp_path) is False  # empty dir


# ── build_validate_steps (validation executor) ───────────────────────────────


@pytest.mark.parametrize("_id, files, real_init", _CASES, ids=_CASE_IDS)
def test_validate_steps_init_flavour(
    tmp_path: Path, _id: str, files: Dict[str, str], real_init: bool
) -> None:
    _write(tmp_path, files)
    steps = build_validate_steps(tmp_path)

    assert [label for label, _ in steps] == ["init", "validate"]
    init_args = steps[0][1]
    if real_init:
        assert "-backend=false" not in init_args
        assert "-reconfigure" in init_args
    else:
        assert "-backend=false" in init_args
        assert "-reconfigure" not in init_args
    # The validate step itself is unchanged in every case.
    assert steps[1][1] == ["validate", "-no-color"]


# ── build_plan_steps (planning executor) ─────────────────────────────────────


@pytest.mark.parametrize("_id, files, real_init", _CASES, ids=_CASE_IDS)
def test_plan_steps_init_flavour(
    tmp_path: Path, _id: str, files: Dict[str, str], real_init: bool
) -> None:
    _write(tmp_path, files)
    steps = build_plan_steps(tmp_path)

    assert [label for label, _ in steps] == ["init", "plan"]
    init_args = steps[0][1]
    if real_init:
        assert "-backend=false" not in init_args
        assert "-reconfigure" in init_args
    else:
        assert "-backend=false" in init_args
        assert "-reconfigure" not in init_args
    # The plan step itself is unchanged in every case.
    assert steps[1][1] == ["plan", "-out=tfplan", "-input=false", "-no-color"]


def test_validate_and_plan_agree_on_init_flavour(tmp_path: Path) -> None:
    """Both executors must pick the SAME init flavour for the same artifact."""
    _write(tmp_path, {"providers.tf": _PROVIDERS_TF, "backend.tf": _S3_BACKEND_TF})
    assert build_validate_steps(tmp_path)[0][1] == build_plan_steps(tmp_path)[0][1]
