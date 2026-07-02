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
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
# Backend initialisation is selected automatically (see ``build_validate_steps``
# / ``build_plan_steps``): when the generated config declares NO backend block we
# keep the historical ``-backend=false`` init (never touch a real backend, need
# no credentials); when it declares ANY backend block (``local`` or ``s3``) we
# run a real, re-configuring ``terraform init`` so the declared backend is
# actually initialised. The AWS provider may still demand credentials/region at
# plan time; that failure is surfaced through the result rather than swallowed.
#
# ``VALIDATE_STEPS`` / ``PLAN_STEPS`` remain the NO-BACKEND baseline sequences
# (the ``directory_declares_backend`` → False branch of the builders). They are
# kept as importable constants for back-compat and as the default the builders
# fall back to.

VALIDATE_STEPS: List[tuple] = [
    ("init",     ["init", "-backend=false", "-input=false", "-no-color"]),
    ("validate", ["validate", "-no-color"]),
]

PLAN_STEPS: List[tuple] = [
    ("init", ["init", "-backend=false", "-input=false", "-no-color"]),
    ("plan", ["plan", "-out=tfplan", "-input=false", "-no-color"]),
]

PLAN_OUTPUT_FILE = "tfplan"


# ── Backend detection + init-flavour selection ───────────────────────────────
#
# A backend is declared as ``backend "<type>" { ... }`` inside the top-level
# ``terraform {}`` block — any type counts (``local``, ``s3``, ``gcs``, …). HCL
# comments are stripped first so a commented-out backend never triggers a real
# init.

_BACKEND_BLOCK_RE = re.compile(r'\bbackend\s+"[^"]+"\s*\{')
_HCL_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_HCL_LINE_COMMENT_RE = re.compile(r"(#|//).*?$", re.MULTILINE)


def _strip_hcl_comments(hcl: str) -> str:
    """Remove ``/* */`` block comments and ``#`` / ``//`` line comments.

    Deliberately simple (it does not track string literals): it only ever
    *removes* text, and the backend-block pattern it feeds never legitimately
    appears inside a string, so the worst case is a false negative on a
    pathological literal — never a false positive on a commented-out backend.
    """
    without_block = _HCL_BLOCK_COMMENT_RE.sub("", hcl)
    return _HCL_LINE_COMMENT_RE.sub("", without_block)


def config_declares_backend(hcl: str) -> bool:
    """True when ``hcl`` declares a ``backend "<type>" {`` block.

    Any backend type counts — including ``local`` and ``s3``. Comments are
    ignored so a commented-out backend does not register.
    """
    if not hcl:
        return False
    return bool(_BACKEND_BLOCK_RE.search(_strip_hcl_comments(hcl)))


def directory_declares_backend(artifact_dir: Path) -> bool:
    """True when any ``*.tf`` file in ``artifact_dir`` declares a backend block.

    Missing directories / unreadable files are treated as "no backend" so the
    caller falls back to the safe ``-backend=false`` init.
    """
    directory = Path(artifact_dir)
    if not directory.is_dir():
        return False
    for tf_file in sorted(directory.glob("*.tf")):
        try:
            if config_declares_backend(tf_file.read_text(encoding="utf-8")):
                return True
        except OSError:
            continue
    return False


def terraform_init_args(*, declares_backend: bool) -> List[str]:
    """Select the ``terraform init`` argument list.

    * No backend block → ``-backend=false`` (historical behaviour: never touches
      a real/remote backend, requires no credentials).
    * Backend declared → a real, re-configuring init so the declared backend
      (``local`` or ``s3``) is actually initialised. ``-reconfigure`` keeps it
      idempotent across re-runs against a possibly-stale ``.terraform/`` dir
      (the artifact directory is reused/rehydrated between phases).
    """
    if declares_backend:
        return ["init", "-reconfigure", "-input=false", "-no-color"]
    return ["init", "-backend=false", "-input=false", "-no-color"]


def build_validate_steps(artifact_dir: Path) -> List[Tuple[str, List[str]]]:
    """VALIDATE_STEPS with the ``init`` flavour chosen from the artifact's backend."""
    init = terraform_init_args(declares_backend=directory_declares_backend(artifact_dir))
    return [("init", init), ("validate", ["validate", "-no-color"])]


def build_plan_steps(artifact_dir: Path) -> List[Tuple[str, List[str]]]:
    """PLAN_STEPS with the ``init`` flavour chosen from the artifact's backend."""
    init = terraform_init_args(declares_backend=directory_declares_backend(artifact_dir))
    return [
        ("init", init),
        ("plan", ["plan", "-out=tfplan", "-input=false", "-no-color"]),
    ]


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
        project_id: Optional[str] = None,
    ) -> GenerationResult:
        """
        Render the template set for ``(architecture, tier)`` and persist it
        as a new artifact on disk.

        ``project_id`` keys the S3 remote-state backend. The standalone path has
        no real project, so it defaults to the generated ``artifact_id`` — each
        ad-hoc generation gets its own isolated state. Rendering raises if the
        TF_STATE_* env vars are unset (no placeholder backend is ever emitted).
        """
        architecture = architecture.lower().strip()
        tier = tier.lower().strip()

        blueprint_dict = _blueprint_for(architecture, tier)
        blueprint = parse_blueprint(blueprint_dict)

        artifact_id = uuid.uuid4().hex[:12]
        render = self._renderer.render(
            blueprint=blueprint,
            task_id=artifact_id,
            project_id=project_id or artifact_id,
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
        (_, init_args), (_, validate_args) = build_validate_steps(artifact_dir)
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
        machinery, same backend-aware init selection) and writes the binary
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
        (_, init_args), (_, plan_args) = build_plan_steps(artifact_dir)
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

    def rehydrate(
        self,
        artifact_id: str,
        files: Dict[str, str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Materialise a set of Terraform files onto disk under the artifact dir.

        This is the "disk sync" step of the unified pipeline: the canonical
        ``.tf`` source lives in the DB (``Artifact`` rows produced by the LLM
        TerraformAgent); ``rehydrate`` writes that source back to
        ``<storage_root>/<artifact_id>/`` so the streamed validate/plan phases
        run ``terraform`` against the *real generated* artifact.

        Idempotent: re-writing the same id overwrites the directory's files.
        Because the source of truth is the DB, this can be called defensively
        before validate/plan to reconstruct a directory that a process restart
        wiped — closing the ephemeral-storage durability gap.
        """
        if not files:
            raise ValueError("rehydrate requires at least one file to write")

        meta: Dict[str, Any] = dict(metadata or {})
        meta.setdefault("generated_by", "rehydrate")
        meta.setdefault("rehydrated_at", time.time())

        self._persist(artifact_id, files, meta)
        logger.info(
            "[TerraformPipelineService] Rehydrated artifact id=%s (%d files) → %s",
            artifact_id, len(files), self._artifact_dir(artifact_id),
        )
        return self._artifact_dir(artifact_id)

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
