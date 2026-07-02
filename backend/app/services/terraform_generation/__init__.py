"""
Terraform generation services — deterministic, template-driven.

Layout
------
    templates/      Strategy-specific .tf.j2 templates (monolith/microservices/serverless × low_cost/balanced/high_performance)
    modules/        Reusable HCL modules referenced from templates (future)
    renderers/      Jinja2 → .tf rendering pipeline
    validators/     hcl2 parse, terraform fmt/validate, tfsec, checkov
    correctors/     TerraformCorrectorAgent helpers (future)
    utils/          Shared helpers (variable context building, naming)

Public API
----------
* ``BackendConfig`` / ``render_backend_tf`` — deterministic backend.tf (LLM-free).
* ``TerraformTemplateRenderer`` — primary entry point. Selects a template set
  from ``InfrastructureBlueprint`` and renders all .tf files deterministically.
* ``TerraformValidator`` — runs the full validation pipeline (fmt / init /
  validate / tfsec / checkov) with graceful tool detection.

Design invariants
-----------------
1. The LLM is structurally forbidden from emitting backend.tf, providers.tf,
   variables.tf, or outputs.tf. Templates are version-controlled, reviewable
   in PR, and deterministic across runs.
2. Every render maps {blueprint, strategy_tier} → one specific template set.
   There is no fallback "generic" path; missing template sets raise loudly.
3. Variable injection is typed and validated — undeclared variables raise
   ``MissingTemplateVariableError`` before any rendering happens.
"""

from backend.app.services.terraform_generation.backend_injector import (
    BackendConfig,
    BackendConfigurationError,
    backend_config_from_env,
    remote_backend_configured,
    render_backend_tf,
    render_local_backend_tf,
)
from backend.app.services.terraform_generation.renderers.template_renderer import (
    TerraformBackendConfigError,
    TerraformTemplateRenderer,
    RenderResult,
)
from backend.app.services.terraform_generation.validators.terraform_validator import (
    TerraformValidator,
)
from backend.app.services.terraform_generation.validators.models import (
    TerraformValidationIssue,
    TerraformSecurityIssue,
    TerraformValidationResult,
    ValidationSeverity,
    ValidationStatus,
)

__all__ = [
    "BackendConfig",
    "BackendConfigurationError",
    "backend_config_from_env",
    "remote_backend_configured",
    "render_backend_tf",
    "render_local_backend_tf",
    "TerraformBackendConfigError",
    "TerraformTemplateRenderer",
    "RenderResult",
    "TerraformValidator",
    "TerraformValidationResult",
    "TerraformValidationIssue",
    "TerraformSecurityIssue",
    "ValidationSeverity",
    "ValidationStatus",
]
