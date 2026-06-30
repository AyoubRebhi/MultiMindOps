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
    6. Emit ``backend.tf`` deterministically (LLM-free, project-keyed S3 remote
       state). If the backend cannot be configured this RAISES — a placeholder
       backend is never generated.
    7. Return a ``RenderResult`` with artifact dict + metadata.

The LLM is not called from this module. The template choice is mechanical:
{architecture_style, strategy_tier} → exactly one template directory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

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
    BackendConfigurationError,
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


class TerraformBackendConfigError(AgentError):
    """Raised when backend.tf cannot be configured (no project_id, or the
    TF_STATE_* env vars are unset).

    This replaces the old behaviour of silently emitting a placeholder backend.
    A missing remote-state backend is unrecoverable: Terraform would fall back
    to empty local state on the ephemeral GitHub runner, so destroy would tear
    down nothing and re-running bootstrap would hit ``AlreadyExists`` errors.
    """

    code = "terraform_backend_config_missing"
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


# ── Template-set resolution ────────────────────────────────────────────────────


# Every architecture ships a "balanced" template set; it is the universal
# baseline that a missing cost tier falls back to (TASK 1 — SAFE FALLBACK).
FALLBACK_STRATEGY_TIER: str = "balanced"

# Every cost tier the ArchitectureDecisionAgent can emit. Used to report the
# renderable matrix (TASK 3 — MATRIX VALIDATION).
ALL_STRATEGY_TIERS: tuple[str, ...] = ("low_cost", "balanced", "high_performance")


def _dir_has_templates(candidate: Path) -> bool:
    """True when ``candidate`` is a directory holding at least one ``*.tf.j2``.

    An empty directory is NOT a valid template set — the tree may have been
    scaffolded ahead of the templates being written.
    """
    return candidate.is_dir() and any(candidate.glob("*.tf.j2"))


class _ResolvedTemplate(NamedTuple):
    """Outcome of resolving an (architecture, tier) request to a directory."""

    template_dir: Path
    effective_tier: str       # tier whose templates were actually selected
    fallback_applied: bool    # True when the requested tier was downgraded


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

    # Tier that every architecture must provide; a missing tier downgrades to it.
    FALLBACK_TIER: str = FALLBACK_STRATEGY_TIER

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
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
        environment: str = "dev",
        container_port: Optional[int] = None,
    ) -> RenderResult:
        """
        Render the full template set for ``blueprint``. Returns a RenderResult
        whose ``artifacts`` dict is keyed by the orchestrator's artifact keys
        (terraform_main, terraform_outputs, …).

        ``project_id`` keys the S3 remote-state backend so every project gets an
        isolated, persistent state object. The production workflow always passes
        the real ``project.id``; ``task_id`` is accepted as a fallback scope for
        the standalone renderer and unit tests. If neither is available — or the
        TF_STATE_* env vars are unset — backend generation raises
        ``TerraformBackendConfigError`` rather than emitting a placeholder.
        """
        arch = blueprint.architecture_style
        tier = blueprint.strategy_tier
        if tier is None:
            raise BlueprintContractError(
                "Blueprint reached TerraformTemplateRenderer without strategy_tier "
                "— check ArchitectureDecisionAgent / resume_with_selected_plan.",
                metadata={"architecture_style": arch},
            )

        resolved = self._resolve_template_dir(arch, tier)
        template_dir = resolved.template_dir
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

        # Deterministic backend.tf — always machine-emitted, never a placeholder.
        # Keyed by project_id (falling back to task_id for the standalone
        # renderer / tests). Raises TerraformBackendConfigError when the backend
        # cannot be configured.
        artifacts["terraform_backend"] = self._render_backend(project_id or task_id)
        files_rendered.append("backend.tf")

        metadata = {
            "artifact_type": "terraform",
            "template_family": arch,
            "strategy_tier": tier,                      # requested tier (preserved)
            "template_tier": resolved.effective_tier,   # tier actually rendered
            "tier_fallback_applied": resolved.fallback_applied,
            "render_mode": "deterministic_template",
            "template_dir": str(template_dir.relative_to(self._templates_root)),
            "generated_by": "TerraformTemplateRenderer",
            "variables_used": sorted(variables.keys()),
        }

        logger.info(
            "[TerraformTemplateRenderer] Rendered %d files for %s/%s "
            "(requested_tier=%s, fallback=%s, task=%s)",
            len(files_rendered), arch, resolved.effective_tier, tier,
            resolved.fallback_applied, task_id,
        )
        return RenderResult(
            artifacts=artifacts,
            metadata=metadata,
            files_rendered=files_rendered,
        )

    # ── Matrix introspection (TASK 3 — renderable-combination validation) ──

    @classmethod
    def available_template_sets(
        cls, templates_root: Optional[Path] = None
    ) -> List[str]:
        """List ``"<arch>/<tier>"`` directories that contain real templates."""
        root = Path(templates_root) if templates_root else cls.TEMPLATES_ROOT
        sets: List[str] = []
        if not root.exists():
            return sets
        for arch_dir in sorted(root.iterdir()):
            if not arch_dir.is_dir():
                continue
            for tier_dir in sorted(arch_dir.iterdir()):
                if _dir_has_templates(tier_dir):
                    sets.append(f"{arch_dir.name}/{tier_dir.name}")
        return sets

    @classmethod
    def is_renderable(
        cls,
        architecture_style: str,
        strategy_tier: Optional[str],
        templates_root: Optional[Path] = None,
    ) -> bool:
        """Whether the renderer can produce HCL for this (architecture, tier).

        True when the exact ``<arch>/<tier>`` set exists, OR the architecture
        has a ``balanced`` baseline that a missing tier falls back to. This is
        the predicate the ArchitectureDecisionAgent uses so it never offers a
        combination the renderer cannot build (TASK 3).
        """
        root = Path(templates_root) if templates_root else cls.TEMPLATES_ROOT
        tier = strategy_tier or cls.FALLBACK_TIER
        if _dir_has_templates(root / architecture_style / tier):
            return True
        return _dir_has_templates(root / architecture_style / cls.FALLBACK_TIER)

    @classmethod
    def renderable_matrix(
        cls, templates_root: Optional[Path] = None
    ) -> Dict[str, Dict[str, str]]:
        """Map ``arch → {tier: 'direct'|'fallback'|'unavailable'}`` for every
        architecture on disk: ``direct`` = own template set, ``fallback`` =
        served by the balanced baseline, ``unavailable`` = cannot render.
        """
        root = Path(templates_root) if templates_root else cls.TEMPLATES_ROOT
        matrix: Dict[str, Dict[str, str]] = {}
        if not root.exists():
            return matrix
        for arch_dir in sorted(root.iterdir()):
            if not arch_dir.is_dir():
                continue
            has_baseline = _dir_has_templates(arch_dir / cls.FALLBACK_TIER)
            row: Dict[str, str] = {}
            for tier in ALL_STRATEGY_TIERS:
                if _dir_has_templates(arch_dir / tier):
                    row[tier] = "direct"
                elif has_baseline:
                    row[tier] = "fallback"
                else:
                    row[tier] = "unavailable"
            matrix[arch_dir.name] = row
        return matrix

    @classmethod
    def architectures_missing_baseline(
        cls, templates_root: Optional[Path] = None
    ) -> List[str]:
        """Architectures lacking a ``balanced`` baseline. Non-empty means the
        fallback cannot rescue a missing tier for those architectures — a
        packaging error worth failing a CI invariant test on.
        """
        root = Path(templates_root) if templates_root else cls.TEMPLATES_ROOT
        broken: List[str] = []
        if not root.exists():
            return broken
        for arch_dir in sorted(root.iterdir()):
            if arch_dir.is_dir() and not _dir_has_templates(
                arch_dir / cls.FALLBACK_TIER
            ):
                broken.append(arch_dir.name)
        return broken

    # ── Internals ─────────────────────────────────────────────────────────

    def _resolve_template_dir(self, arch: str, tier: str) -> _ResolvedTemplate:
        """Resolve ``templates/<arch>/<tier>``, downgrading to the
        architecture's balanced baseline when the requested tier is absent
        (TASK 1 — SAFE FALLBACK).

        Rules
        -----
        * ``<arch>/<tier>`` has templates        → exact match.
        * else ``<arch>/balanced`` has templates → fallback + WARNING. The
          architecture is PRESERVED; only the cost tier is downgraded.
        * else                                   → TemplateSelectionError. The
          architecture itself is unrenderable — a missing balanced baseline is
          a packaging bug, never a routine condition.

        Generation therefore never hard-fails on a missing *tier*; it only fails
        when an entire architecture family has no baseline template set.
        """
        exact = self._templates_root / arch / tier
        if _dir_has_templates(exact):
            return _ResolvedTemplate(exact, tier, fallback_applied=False)

        baseline = self._templates_root / arch / self.FALLBACK_TIER
        if tier != self.FALLBACK_TIER and _dir_has_templates(baseline):
            logger.warning(
                "[TerraformTemplateRenderer] No '%s' template set for "
                "architecture='%s' — falling back to '%s/%s'. Architecture "
                "preserved; cost tier downgraded to the baseline.",
                tier, arch, arch, self.FALLBACK_TIER,
            )
            return _ResolvedTemplate(
                baseline, self.FALLBACK_TIER, fallback_applied=True
            )

        raise TemplateSelectionError(
            f"No template set found for architecture='{arch}', "
            f"strategy_tier='{tier}', and no '{self.FALLBACK_TIER}' baseline "
            f"exists for this architecture to fall back to.",
            metadata={
                "requested": {"architecture_style": arch, "strategy_tier": tier},
                "available": self._enumerate_available_template_sets(),
                "templates_root": str(self._templates_root),
            },
        )

    def _enumerate_available_template_sets(self) -> List[str]:
        """List template directories that contain at least one .tf.j2 file."""
        return self.available_template_sets(self._templates_root)

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

    def _render_backend(self, project_id: Optional[str]) -> str:
        """Deterministic backend.tf via backend_injector — never LLM, never a
        placeholder.

        Raises ``TerraformBackendConfigError`` when the S3 remote-state backend
        cannot be configured (no project_id, or the TF_STATE_* env vars are
        unset). We refuse to emit a placeholder: that would make Terraform use
        empty local state on the GitHub runner, breaking destroy and re-deploy.
        """
        if not project_id:
            raise TerraformBackendConfigError(
                "Cannot generate backend.tf: a project_id is required so the S3 "
                "remote state is isolated per project "
                "(key = projects/<project-id>/terraform.tfstate).",
                metadata={"reason": "missing_project_id"},
            )
        try:
            cfg = backend_config_from_env(project_id)
        except BackendConfigurationError as exc:
            raise TerraformBackendConfigError(
                f"Cannot generate backend.tf: {exc}",
                metadata={
                    "reason": "backend_config_unavailable",
                    "project_id": project_id,
                },
            ) from exc
        logger.info(
            "[TerraformTemplateRenderer] backend.tf emitted (bucket=%s, key=%s)",
            cfg.bucket, cfg.state_key,
        )
        return render_backend_tf(cfg)
