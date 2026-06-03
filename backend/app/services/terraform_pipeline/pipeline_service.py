"""
TerraformPipelineService — minimal end-to-end generator + validator.

Scope (intentionally narrow)
----------------------------
* Three supported (architecture, tier) combinations:
    - monolith       / balanced
    - microservices  / balanced
    - serverless     / balanced
* Generation = template rendering via ``TerraformTemplateRenderer``.
* Persistence = filesystem under ``<storage_root>/<artifact_id>/`` —
  one directory per generated artifact, ``manifest.json`` + ``.tf`` files.
* Validation = ``terraform init`` + ``terraform validate`` via ``subprocess``.

Standardized output shape
-------------------------
Both ``generate`` and ``load`` return::

    {
        "id":        "<artifact_id>",
        "files":     {"main.tf": "...", "variables.tf": "...", "outputs.tf": "...", ...},
        "metadata":  {"architecture": "monolith", "tier": "balanced", ...},
    }
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.schemas.blueprint import parse_blueprint
from backend.app.services.terraform_generation.renderers.template_renderer import (
    TerraformTemplateRenderer,
)

logger = logging.getLogger(__name__)


# ── Errors ───────────────────────────────────────────────────────────────────


class UnsupportedArchitectureError(ValueError):
    """Raised when the requested (architecture, tier) combination is not in scope."""


class ArtifactNotFoundError(LookupError):
    """Raised when an artifact id cannot be located on disk."""


# ── Result types ─────────────────────────────────────────────────────────────


@dataclass
class GenerationResult:
    id: str
    files: Dict[str, str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "files": self.files, "metadata": self.metadata}


@dataclass
class ValidationResult:
    id: str
    init_ok: bool
    validate_ok: bool
    init_stdout: str
    init_stderr: str
    validate_stdout: str
    validate_stderr: str
    duration_ms: int

    @property
    def is_valid(self) -> bool:
        return self.init_ok and self.validate_ok

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "valid": self.is_valid,
            "init": {
                "ok": self.init_ok,
                "stdout": self.init_stdout,
                "stderr": self.init_stderr,
            },
            "validate": {
                "ok": self.validate_ok,
                "stdout": self.validate_stdout,
                "stderr": self.validate_stderr,
            },
            "duration_ms": self.duration_ms,
        }


@dataclass
class PlanResult:
    id: str
    init_ok: bool
    plan_ok: bool
    init_stdout: str
    init_stderr: str
    plan_stdout: str
    plan_stderr: str
    plan_file: Optional[str]
    duration_ms: int

    @property
    def is_planned(self) -> bool:
        return self.init_ok and self.plan_ok

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "planned": self.is_planned,
            "init": {
                "ok": self.init_ok,
                "stdout": self.init_stdout,
                "stderr": self.init_stderr,
            },
            "plan": {
                "ok": self.plan_ok,
                "stdout": self.plan_stdout,
                "stderr": self.plan_stderr,
            },
            "plan_file": self.plan_file,
            "duration_ms": self.duration_ms,
        }


# ── Terraform command-step sequences ─────────────────────────────────────────
#
# Single source of truth for the terraform invocations. Both the blocking API
# methods below and the streaming workflow handlers
# (``terraform_pipeline.streaming``) consume these, so flags can never drift
# between the synchronous ``/terraform/*`` path and the streamed workflow
# phases.
#
# ``plan`` reuses ``-backend=false`` so it never tries to configure the S3
# remote backend declared in backend.tf (which would need credentials). The
# AWS provider may still demand credentials/region at plan time; that failure
# is surfaced through the result rather than swallowed.

VALIDATE_STEPS: List[tuple] = [
    ("init",     ["init", "-backend=false", "-input=false", "-no-color"]),
    ("validate", ["validate", "-no-color"]),
]

PLAN_STEPS: List[tuple] = [
    ("init", ["init", "-backend=false", "-input=false", "-no-color"]),
    ("plan", ["plan", "-out=tfplan", "-input=false", "-no-color"]),
]

PLAN_OUTPUT_FILE = "tfplan"


# ── Terraform subprocess environment ─────────────────────────────────────────


def terraform_subprocess_env() -> Dict[str, str]:
    """Build the environment for terraform subprocesses.

    Starts from the inherited ``os.environ`` (so a developer relying on the AWS
    shared credentials file ``~/.aws/credentials`` is unaffected), then overlays
    any AWS credentials configured via ``.env`` / settings. Empty settings are
    NOT exported — so the precedence is:

        explicit .env credentials  >  inherited shell env / ~/.aws

    Region is exported under both ``AWS_DEFAULT_REGION`` and ``AWS_REGION`` since
    the AWS provider honours either.
    """
    from backend.app.core.config import settings

    env = dict(os.environ)

    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        value = str(getattr(settings, name, "") or "").strip()
        if value:
            env[name] = value

    region = str(getattr(settings, "AWS_DEFAULT_REGION", "") or "").strip()
    if region:
        env["AWS_DEFAULT_REGION"] = region
        env["AWS_REGION"] = region

    return env


# ── Minimal blueprint factories ──────────────────────────────────────────────
#
# Each factory returns a dict that satisfies ``InfrastructureBlueprint``.
# Only the balanced tier is in scope; the renderer enforces the rest.

_SUPPORTED_TIERS = {"balanced"}


def _blueprint_for(architecture: str, tier: str) -> Dict[str, Any]:
    if tier not in _SUPPORTED_TIERS:
        raise UnsupportedArchitectureError(
            f"Only 'balanced' tier is supported in the minimal pipeline (got '{tier}')."
        )

    base = {
        "aws_region": "us-east-1",
        "strategy_tier": tier,
        "networking": {"vpc": True, "multi_az": True, "load_balancer": "ALB"},
        "scaling": {"strategy": "vertical+horizontal", "auto_scaling": True},
        "storage": {"object_storage": "S3"},
    }

    if architecture == "monolith":
        base.update({
            "architecture_style": "monolith",
            "compute": {"type": "ECS", "instance_type": "t3.medium"},
            "database": {
                "engine": "postgres",
                "deployment": "RDS Multi-AZ",
                "read_replicas": False,
            },
        })
        return base

    if architecture == "microservices":
        base.update({
            "architecture_style": "microservices",
            "compute": {
                "type": "EKS",
                "node_type": "t3.medium",
                "min_nodes": 2,
                "max_nodes": 3,
            },
            "database": {
                "engine": "postgres",
                "deployment": "RDS Multi-AZ",
                "read_replicas": False,
            },
        })
        return base

    if architecture == "serverless":
        base.update({
            "architecture_style": "serverless",
            "compute": {"type": "Lambda", "runtime": "python3.11"},
            "networking": {"vpc": True, "multi_az": True, "load_balancer": "API Gateway"},
            "scaling": {"strategy": "fully_managed", "auto_scaling": True},
        })
        return base

    raise UnsupportedArchitectureError(
        f"Unsupported architecture '{architecture}'. "
        "Supported: monolith | microservices | serverless."
    )


# ── Mapping orchestrator artifact-keys → filenames on disk ───────────────────
#
# Mirrors the renderer's internal mapping but is duplicated here so this
# service does not reach into renderer internals.

_ARTIFACT_KEY_TO_FILENAME: Dict[str, str] = {
    "terraform_providers":  "providers.tf",
    "terraform_main":       "main.tf",
    "terraform_variables":  "variables.tf",
    "terraform_tfvars":     "terraform.tfvars",
    "terraform_outputs":    "outputs.tf",
    "terraform_backend":    "backend.tf",
}


# ── Service ──────────────────────────────────────────────────────────────────


class TerraformPipelineService:
    """
    Single-process service: generate → persist → validate.

    Parameters
    ----------
    storage_root :
        Directory where artifacts are persisted. Defaults to
        ``./generated_terraform`` relative to the process cwd, overridable
        via the ``TF_PIPELINE_STORAGE_ROOT`` env var.
    terraform_timeout :
        Per-subprocess hard timeout for terraform init / validate.
    """

    def __init__(
        self,
        storage_root: Optional[Path] = None,
        terraform_timeout: int = 120,
    ) -> None:
        root = storage_root or Path(
            os.getenv("TF_PIPELINE_STORAGE_ROOT", "generated_terraform")
        )
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        self._storage_root = root
        self._renderer = TerraformTemplateRenderer()
        self._timeout = terraform_timeout

    # ── Public API ────────────────────────────────────────────────────────

    def generate(
        self,
        architecture: str,
        tier: str = "balanced",
        project_name: Optional[str] = None,
    ) -> GenerationResult:
        """
        Render the template set for ``(architecture, tier)`` and persist it
        as a new artifact on disk.
        """
        architecture = architecture.lower().strip()
        tier = tier.lower().strip()

        blueprint_dict = _blueprint_for(architecture, tier)
        blueprint = parse_blueprint(blueprint_dict)

        artifact_id = uuid.uuid4().hex[:12]
        render = self._renderer.render(
            blueprint=blueprint,
            task_id=artifact_id,
            project_name=project_name or f"app-{artifact_id}",
        )

        # Convert {artifact_key: hcl} → {filename: hcl}
        files: Dict[str, str] = {}
        for key, content in render.artifacts.items():
            filename = _ARTIFACT_KEY_TO_FILENAME.get(key)
            if not filename:
                continue
            files[filename] = content

        metadata: Dict[str, Any] = {
            "architecture": architecture,
            "tier": tier,
            "aws_region": blueprint.aws_region,
            "compute_type": blueprint.compute.type,
            "generated_by": "TerraformPipelineService",
            "generated_at": time.time(),
            **render.metadata,
        }

        self._persist(artifact_id, files, metadata)

        logger.info(
            "[TerraformPipelineService] Generated %s/%s artifact id=%s (%d files)",
            architecture, tier, artifact_id, len(files),
        )
        return GenerationResult(id=artifact_id, files=files, metadata=metadata)

    def load(self, artifact_id: str) -> GenerationResult:
        """Load a previously generated artifact from disk."""
        artifact_dir = self._artifact_dir(artifact_id)
        manifest_path = artifact_dir / "manifest.json"
        if not manifest_path.exists():
            raise ArtifactNotFoundError(f"No artifact with id '{artifact_id}'")

        metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
        files: Dict[str, str] = {}
        for entry in artifact_dir.iterdir():
            if entry.is_file() and entry.suffix in (".tf", ".tfvars"):
                files[entry.name] = entry.read_text(encoding="utf-8")
        return GenerationResult(id=artifact_id, files=files, metadata=metadata)

    def validate(self, artifact_id: str) -> ValidationResult:
        """
        Run ``terraform init`` + ``terraform validate`` against the persisted
        artifact directory. Requires the ``terraform`` binary on PATH.
        """
        artifact_dir = self._artifact_dir(artifact_id)
        if not artifact_dir.exists():
            raise ArtifactNotFoundError(f"No artifact with id '{artifact_id}'")

        binary = shutil.which("terraform")
        if not binary:
            raise RuntimeError(
                "The 'terraform' binary was not found on PATH. "
                "Install Terraform to use the validation endpoint."
            )

        start = time.perf_counter()
        _, init_args = VALIDATE_STEPS[0]
        _, validate_args = VALIDATE_STEPS[1]
        init = self._run_terraform(binary, init_args, cwd=artifact_dir)
        validate = (
            self._run_terraform(binary, validate_args, cwd=artifact_dir)
            if init.returncode == 0
            else None
        )

        duration_ms = int((time.perf_counter() - start) * 1000)

        return ValidationResult(
            id=artifact_id,
            init_ok=init.returncode == 0,
            validate_ok=bool(validate and validate.returncode == 0),
            init_stdout=init.stdout or "",
            init_stderr=init.stderr or "",
            validate_stdout=(validate.stdout if validate else "") or "",
            validate_stderr=(validate.stderr if validate else "skipped: init failed") or "",
            duration_ms=duration_ms,
        )

    def plan(self, artifact_id: str) -> PlanResult:
        """
        Run ``terraform init`` + ``terraform plan -out=tfplan`` against the
        persisted artifact directory. Mirrors :meth:`validate` (same subprocess
        machinery, same ``-backend=false`` init) and writes the binary
        ``tfplan`` into the artifact directory.

        A plan that fails because cloud credentials are absent is reported
        through the returned :class:`PlanResult` (``plan_ok=False``) rather
        than raising — credential handling is out of scope for this phase.
        """
        artifact_dir = self._artifact_dir(artifact_id)
        if not artifact_dir.exists():
            raise ArtifactNotFoundError(f"No artifact with id '{artifact_id}'")

        binary = shutil.which("terraform")
        if not binary:
            raise RuntimeError(
                "The 'terraform' binary was not found on PATH. "
                "Install Terraform to use the plan endpoint."
            )

        start = time.perf_counter()
        _, init_args = PLAN_STEPS[0]
        _, plan_args = PLAN_STEPS[1]
        init = self._run_terraform(binary, init_args, cwd=artifact_dir)
        plan = (
            self._run_terraform(binary, plan_args, cwd=artifact_dir)
            if init.returncode == 0
            else None
        )

        duration_ms = int((time.perf_counter() - start) * 1000)

        plan_path = artifact_dir / PLAN_OUTPUT_FILE
        plan_file = str(plan_path) if plan_path.exists() else None

        return PlanResult(
            id=artifact_id,
            init_ok=init.returncode == 0,
            plan_ok=bool(plan and plan.returncode == 0),
            init_stdout=init.stdout or "",
            init_stderr=init.stderr or "",
            plan_stdout=(plan.stdout if plan else "") or "",
            plan_stderr=(plan.stderr if plan else "skipped: init failed") or "",
            plan_file=plan_file,
            duration_ms=duration_ms,
        )

    def artifact_path(self, artifact_id: str) -> Path:
        """Public accessor for an artifact's on-disk directory.

        Used by the streaming workflow handlers, which run terraform against
        the same directory this service persisted to.
        """
        return self._artifact_dir(artifact_id)

    def list_ids(self) -> List[str]:
        """Convenience: enumerate persisted artifact ids."""
        return sorted(
            entry.name
            for entry in self._storage_root.iterdir()
            if entry.is_dir() and (entry / "manifest.json").exists()
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _artifact_dir(self, artifact_id: str) -> Path:
        # Defensive id sanitisation — only hex chars + dashes allowed.
        safe = "".join(c for c in artifact_id if c.isalnum() or c == "-")
        if not safe or safe != artifact_id:
            raise ArtifactNotFoundError(f"Invalid artifact id '{artifact_id}'")
        return self._storage_root / safe

    def _persist(
        self,
        artifact_id: str,
        files: Dict[str, str],
        metadata: Dict[str, Any],
    ) -> None:
        artifact_dir = self._artifact_dir(artifact_id)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in files.items():
            (artifact_dir / filename).write_text(content, encoding="utf-8")
        (artifact_dir / "manifest.json").write_text(
            json.dumps(metadata, indent=2, default=str),
            encoding="utf-8",
        )

    def _run_terraform(
        self,
        binary: str,
        args: List[str],
        cwd: Path,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [binary, *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=self._timeout,
            check=False,
            env=terraform_subprocess_env(),
        )
