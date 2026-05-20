"""
TerraformTemplateRenderer — single entry point for deterministic HCL emission.

Flow
----
    1. Resolve template directory: templates/<arch_style>/<strategy_tier>/
    2. Validate blueprint-template compatibility (architecture must match,
       multi_az invariants must hold).
    3. Build variable context from the typed blueprint.
    4. Load every *.tf.j2 file in the chosen directory.
    5. Render each with Jinja2 in StrictUndefined mode (any undeclared
       variable raises).
    6. Overwrite ``backend.tf`` deterministically (LLM-free, task-keyed).
    7. Return a ``RenderResult`` with artifact dict + metadata.

The LLM is not called from this module. The template choice is mechanical:
{architecture_style, strategy_tier} → exactly one template directory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateError,
    UndefinedError,
)

from backend.app.agents.errors import AgentError, BlueprintContractError
from backend.app.schemas.blueprint import InfrastructureBlueprint
from backend.app.services.terraform_generation.backend_injector import (
    backend_config_from_env,
    render_backend_tf,
)
from backend.app.services.terraform_generation.utils.variable_context import (
    build_variable_context,
)

logger = logging.getLogger(__name__)


# ── Errors ────────────────────────────────────────────────────────────────────


class TemplateSelectionError(AgentError):
    """Raised when no template set exists for the requested architecture/tier."""

    code = "terraform_template_missing"
    recoverable = False
    default_phase = "terraform_generation"


class MissingTemplateVariableError(AgentError):
    """Raised when a template references a variable not present in the context."""

    code = "terraform_template_variable_missing"
    recoverable = False
    default_phase = "terraform_generation"


class TemplateCompatibilityError(AgentError):
    """Raised when the blueprint violates a template invariant (e.g. high_performance ∧ ¬multi_az)."""

    code = "terraform_template_incompatible_blueprint"
    recoverable = False
    default_phase = "terraform_generation"


# ── Result type ───────────────────────────────────────────────────────────────


# Mapping from template filename → orchestrator artifact key. The orchestrator
# already uses these keys (terraform_main, terraform_variables, etc.) — keep
# them stable so the rest of the pipeline does not need to change.
_FILENAME_TO_ARTIFACT_KEY: Dict[str, str] = {
    "providers.tf": "terraform_providers",
    "main.tf": "terraform_main",
    "variables.tf": "terraform_variables",
    "terraform.tfvars": "terraform_tfvars",
    "outputs.tf": "terraform_outputs",
    # backend.tf is injected separately (always).
    "backend.tf": "terraform_backend",
}


@dataclass
class RenderResult:
    """Output of TerraformTemplateRenderer.render()."""

    artifacts: Dict[str, str]  # {orchestrator_key: hcl_content}
    metadata: Dict[str, Any]   # template_family, strategy_tier, render_mode, …
    files_rendered: List[str] = field(default_factory=list)


# ── Renderer ──────────────────────────────────────────────────────────────────


class TerraformTemplateRenderer:
    """
    Deterministic Terraform renderer.

    Construct once per process — the Jinja Environment is reused across
    renders for performance, but the FileSystemLoader is rooted at the
    package's ``templates/`` directory so every template path is relative
    to a fixed, version-controlled location.
    """

    TEMPLATES_ROOT: Path = (
        Path(__file__).resolve().parent.parent / "templates"
    )

    EXPECTED_FILES: tuple[str, ...] = (
        "providers.tf",
        "main.tf",
        "variables.tf",
        "terraform.tfvars",
        "outputs.tf",
    )

    def __init__(self, templates_root: Optional[Path] = None) -> None:
        root = Path(templates_root) if templates_root else self.TEMPLATES_ROOT
        if not root.exists():
            raise FileNotFoundError(f"Templates root does not exist: {root}")
        self._templates_root = root
        self._env = Environment(
            loader=FileSystemLoader(str(root)),
            undefined=StrictUndefined,        # undeclared variables RAISE
            autoescape=False,                 # we are emitting HCL, not HTML
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    # ── Public API ────────────────────────────────────────────────────────

    def render(
        self,
        blueprint: InfrastructureBlueprint,
        *,
        task_id: Optional[str] = None,
        project_name: Optional[str] = None,
        environment: str = "dev",
        container_port: Optional[int] = None,
    ) -> RenderResult:
        """
        Render the full template set for ``blueprint``. Returns a RenderResult
        whose ``artifacts`` dict is keyed by the orchestrator's artifact keys
        (terraform_main, terraform_outputs, …).
        """
        arch = blueprint.architecture_style
        tier = blueprint.strategy_tier
        if tier is None:
            raise BlueprintContractError(
                "Blueprint reached TerraformTemplateRenderer without strategy_tier "
                "— check ArchitectureDecisionAgent / resume_with_selected_plan.",
                metadata={"architecture_style": arch},
            )

        template_dir = self._resolve_template_dir(arch, tier)
        self._check_blueprint_compatibility(blueprint, template_dir)

        variables = build_variable_context(
            blueprint,
            task_id=task_id,
            project_name=project_name,
            environment=environment,
            container_port=container_port,
        )

        artifacts: Dict[str, str] = {}
        files_rendered: List[str] = []

        for filename in self.EXPECTED_FILES:
            template_path = template_dir / f"{filename}.j2"
            if not template_path.exists():
                raise TemplateSelectionError(
                    f"Template set for {arch}/{tier} is incomplete — missing {filename}.j2",
                    metadata={
                        "template_dir": str(template_dir.relative_to(self._templates_root)),
                        "missing_file": filename,
                        "expected_files": list(self.EXPECTED_FILES),
                    },
                )
            rel_template = template_path.relative_to(self._templates_root).as_posix()
            try:
                rendered = self._env.get_template(rel_template).render(**variables)
            except UndefinedError as exc:
                raise MissingTemplateVariableError(
                    f"Template {rel_template} references an undeclared variable: {exc}",
                    metadata={
                        "template": rel_template,
                        "available_variables": sorted(variables.keys()),
                    },
                ) from exc
            except TemplateError as exc:
                raise TemplateSelectionError(
                    f"Jinja2 render failed for {rel_template}: {exc}",
                    metadata={"template": rel_template, "error": str(exc)},
                ) from exc

            artifacts[_FILENAME_TO_ARTIFACT_KEY[filename]] = rendered
            files_rendered.append(filename)

        # Deterministic backend.tf — always machine-emitted. Falls back to a
        # placeholder when TF_STATE_* env vars are missing (development mode).
        artifacts["terraform_backend"] = self._render_backend(task_id)
        files_rendered.append("backend.tf")

        metadata = {
            "artifact_type": "terraform",
            "template_family": arch,
            "strategy_tier": tier,
            "render_mode": "deterministic_template",
            "template_dir": str(template_dir.relative_to(self._templates_root)),
            "generated_by": "TerraformTemplateRenderer",
            "variables_used": sorted(variables.keys()),
        }

        logger.info(
            "[TerraformTemplateRenderer] Rendered %d files for %s/%s (task=%s)",
            len(files_rendered), arch, tier, task_id,
        )
        return RenderResult(
            artifacts=artifacts,
            metadata=metadata,
            files_rendered=files_rendered,
        )

    # ── Internals ─────────────────────────────────────────────────────────

    def _resolve_template_dir(self, arch: str, tier: str) -> Path:
        candidate = self._templates_root / arch / tier
        # An empty directory must not be treated as a valid template set —
        # the directory may exist because the operator scaffolded the tree
        # ahead of writing templates.
        has_templates = candidate.exists() and candidate.is_dir() and any(
            candidate.glob("*.tf.j2")
        )
        if not has_templates:
            available = self._enumerate_available_template_sets()
            raise TemplateSelectionError(
                f"No template set found for architecture='{arch}', strategy_tier='{tier}'.",
                metadata={
                    "requested": {"architecture_style": arch, "strategy_tier": tier},
                    "available": available,
                    "templates_root": str(self._templates_root),
                },
            )
        return candidate

    def _enumerate_available_template_sets(self) -> List[str]:
        """List template directories that contain at least one .tf.j2 file."""
        available: List[str] = []
        for arch_dir in sorted(self._templates_root.iterdir()):
            if not arch_dir.is_dir():
                continue
            for tier_dir in sorted(arch_dir.iterdir()):
                if not tier_dir.is_dir():
                    continue
                if any(tier_dir.glob("*.tf.j2")):
                    available.append(f"{arch_dir.name}/{tier_dir.name}")
        return available

    def _check_blueprint_compatibility(
        self,
        blueprint: InfrastructureBlueprint,
        template_dir: Path,
    ) -> None:
        """
        Apply template-side invariants that the Pydantic schema alone cannot
        express:

        * high_performance → multi_az must be True
        * serverless → compute.type must be Lambda (caught by schema too, but
          a defence in depth here protects against template-set mis-selection)
        """
        tier = blueprint.strategy_tier
        arch = blueprint.architecture_style

        if tier == "high_performance" and not blueprint.is_multi_az:
            raise TemplateCompatibilityError(
                "high_performance templates require multi_az=true on the blueprint",
                metadata={
                    "strategy_tier": tier,
                    "multi_az": blueprint.is_multi_az,
                    "template_dir": str(template_dir.relative_to(self._templates_root)),
                },
            )
        if arch == "serverless" and blueprint.compute.type != "Lambda":
            raise TemplateCompatibilityError(
                "serverless templates require compute.type='Lambda'",
                metadata={
                    "architecture_style": arch,
                    "compute_type": blueprint.compute.type,
                },
            )
        if arch == "microservices" and blueprint.compute.type != "EKS":
            raise TemplateCompatibilityError(
                "microservices templates require compute.type='EKS'",
                metadata={
                    "architecture_style": arch,
                    "compute_type": blueprint.compute.type,
                },
            )
        if arch == "monolith" and blueprint.compute.type not in ("ECS", "EC2"):
            raise TemplateCompatibilityError(
                "monolith templates require compute.type='ECS' or 'EC2'",
                metadata={
                    "architecture_style": arch,
                    "compute_type": blueprint.compute.type,
                },
            )

    def _render_backend(self, task_id: Optional[str]) -> str:
        """Deterministic backend.tf via backend_injector — never LLM."""
        if not task_id:
            return (
                "# backend.tf placeholder — task_id not available at render time.\n"
                "# A real S3 backend will be injected by the orchestrator before apply.\n"
            )
        try:
            cfg = backend_config_from_env(task_id)
            return render_backend_tf(cfg)
        except RuntimeError as exc:
            logger.warning(
                "[TerraformTemplateRenderer] Backend env vars missing (%s) — "
                "emitting placeholder backend.tf (development mode only).", exc,
            )
            return (
                f"# backend.tf placeholder — TF_STATE_* env vars not configured.\n"
                f"# task_id={task_id}\n"
                "# In production, set TF_STATE_BUCKET / TF_STATE_REGION / TF_STATE_LOCK_TABLE.\n"
            )
