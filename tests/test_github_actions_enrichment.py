"""GPT-5-mini enrichment for the GitHub Actions deployment workflow.

The rendered template is the SOURCE OF TRUTH; enrichment is an OPTIONAL polish
pass that must ALWAYS return content safe to persist. These tests pin the safety
contract by stubbing the LLM seam (``_call_llm``) — no network, deterministic:

  * successful enrichment is accepted (and itself validates),
  * invalid YAML / empty / removed-job / removed-deploy-step responses fall back
    to the untouched template render,
  * an LLM error falls back,
  * disabled enrichment short-circuits without ever calling the model,
  * the config flag defaults OFF,
  * markdown code fences are tolerated.
"""

from __future__ import annotations

import pytest

from backend.app.services.github_actions_generation.github_actions_enrichment_service import (
    GitHubActionsEnrichmentService as SVC,
)
from backend.app.services.github_actions_generation.models import DeploymentContext
from backend.app.services.github_actions_generation.yaml_validator import (
    validate_workflow_yaml,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

# A realistic rendered ECS deploy workflow: valid YAML, single ``deploy`` job,
# carrying every critical marker the guardrails protect.
RENDERED = """\
name: Deploy myapp to ECS
on:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: myapp
  ECS_CLUSTER: myapp-cluster
  ECS_SERVICE: myapp-svc
  TERRAFORM_DIR: terraform
  IMAGE_TAG: ${{ github.sha }}
jobs:
  deploy:
    name: Build, provision and deploy
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
      - name: Terraform init
        run: terraform init -input=false
      - name: Terraform apply
        run: terraform apply -auto-approve -input=false
      - name: Log in to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2
      - name: Build and push image
        run: |
          docker build -t img .
          docker push img
      - name: Deploy to Amazon ECS
        run: aws ecs update-service --force-new-deployment
"""

# Accepted improvement: adds a concurrency group, keeps the job + every marker.
GOOD = RENDERED.replace(
    "permissions:\n  contents: read\n",
    "permissions:\n  contents: read\nconcurrency:\n"
    "  group: deploy-myapp\n  cancel-in-progress: false\n",
)

# Renames the only job → job set changes.
JOB_REMOVED = RENDERED.replace("  deploy:\n", "  release:\n")

# Same job, valid YAML, but the Terraform steps are gone → critical marker lost.
STEP_REMOVED = """\
name: Deploy myapp to ECS
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
      - name: Log in to Amazon ECR
        uses: aws-actions/amazon-ecr-login@v2
      - name: Build and push image
        run: |
          docker build -t img .
          docker push img
      - name: Deploy to Amazon ECS
        run: aws ecs update-service --force-new-deployment
"""

INVALID_YAML = "a: [b: c"

FENCED_GOOD = "```yaml\n" + GOOD + "```"


@pytest.fixture
def context() -> DeploymentContext:
    return DeploymentContext(
        deployment_target="ecs",
        project_name="myapp",
        docker_artifacts=["dockerfile"],
        terraform_artifacts=["terraform_main", "terraform_providers"],
    )


def _patch_llm(monkeypatch, value=None, *, raises=None):
    """Replace the model call so no network is hit."""

    def fake(cls, rendered_yaml, ctx):
        if raises is not None:
            raise raises
        return value

    monkeypatch.setattr(SVC, "_call_llm", classmethod(fake))


# ── 1. Successful enrichment is accepted (Phase 2/5) ─────────────────────────

def test_successful_enrichment_is_applied(monkeypatch, context):
    _patch_llm(monkeypatch, GOOD)
    result = SVC.enrich(RENDERED, context, enabled=True)

    assert result.applied is True
    assert result.reason == "ok"
    assert "concurrency:" in result.content
    # Validation AFTER enrichment: the accepted candidate is a valid workflow.
    assert validate_workflow_yaml(result.content).valid is True


# ── 2. Invalid YAML falls back to the template (Phase 4) ─────────────────────

def test_invalid_yaml_falls_back(monkeypatch, context):
    _patch_llm(monkeypatch, INVALID_YAML)
    result = SVC.enrich(RENDERED, context, enabled=True)

    assert result.applied is False
    assert result.reason == "invalid_yaml"
    assert result.content == RENDERED


# ── 3. Empty response falls back (Phase 4) ───────────────────────────────────

@pytest.mark.parametrize("empty", ["", "   \n  "])
def test_empty_response_falls_back(monkeypatch, context, empty):
    _patch_llm(monkeypatch, empty)
    result = SVC.enrich(RENDERED, context, enabled=True)

    assert result.applied is False
    assert result.reason == "empty_response"
    assert result.content == RENDERED


# ── 4. Removing/renaming a job falls back (Phase 4) ──────────────────────────

def test_job_set_changed_falls_back(monkeypatch, context):
    _patch_llm(monkeypatch, JOB_REMOVED)
    result = SVC.enrich(RENDERED, context, enabled=True)

    assert result.applied is False
    assert result.reason == "job_set_changed"
    assert result.content == RENDERED


# ── 5. Removing terraform/deploy steps falls back (Phase 4) ──────────────────

def test_critical_step_removed_falls_back(monkeypatch, context):
    _patch_llm(monkeypatch, STEP_REMOVED)
    result = SVC.enrich(RENDERED, context, enabled=True)

    assert result.applied is False
    assert result.reason == "critical_step_removed"
    assert result.content == RENDERED


# ── 6. An LLM error falls back (Phase 4) ─────────────────────────────────────

def test_llm_error_falls_back(monkeypatch, context):
    _patch_llm(monkeypatch, raises=RuntimeError("boom"))
    result = SVC.enrich(RENDERED, context, enabled=True)

    assert result.applied is False
    assert result.reason == "llm_error"
    assert result.content == RENDERED


# ── 7. Disabled enrichment short-circuits, never calls the model (Phase 6) ───

def test_disabled_does_not_call_model(monkeypatch, context):
    def explode(cls, rendered_yaml, ctx):  # pragma: no cover - must not run
        raise AssertionError("LLM must not be called when disabled")

    monkeypatch.setattr(SVC, "_call_llm", classmethod(explode))
    result = SVC.enrich(RENDERED, context, enabled=False)

    assert result.applied is False
    assert result.reason == "disabled"
    assert result.content == RENDERED


# ── 8. Config flag defaults OFF (Phase 6) ────────────────────────────────────

def test_flag_defaults_off():
    from backend.app.core.config import settings

    assert settings.ENABLE_GITHUB_ACTIONS_ENRICHMENT is False
    assert SVC.is_enabled() is False


def test_enabled_resolves_from_settings(monkeypatch, context):
    from backend.app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_GITHUB_ACTIONS_ENRICHMENT", True)
    assert SVC.is_enabled() is True
    _patch_llm(monkeypatch, GOOD)
    # enabled=None → resolve from settings (now True) → enrichment runs.
    result = SVC.enrich(RENDERED, context)
    assert result.applied is True


# ── 9. Logs are surfaced for the UI (Phase 7) ────────────────────────────────

def test_emits_user_facing_logs(monkeypatch, context):
    _patch_llm(monkeypatch, GOOD)
    logs: list[dict] = []
    SVC.enrich(RENDERED, context, enabled=True, logs=logs)

    messages = " ".join(entry["message"] for entry in logs)
    assert all(entry["step"] == "github_actions" for entry in logs)
    assert "Optimizing workflow with AI..." in messages
    assert "GPT-5-mini" in messages
    assert "succeeded" in messages


# ── 10. Markdown code fences are tolerated ───────────────────────────────────

def test_code_fences_are_stripped(monkeypatch, context):
    _patch_llm(monkeypatch, FENCED_GOOD)
    result = SVC.enrich(RENDERED, context, enabled=True)

    assert result.applied is True
    assert result.reason == "ok"
    assert "```" not in result.content
    assert validate_workflow_yaml(result.content).valid is True


# ── 11. Forbidden-marker guard (deploy.yml must never gain terraform) ────────

# A delivery (deploy) workflow: valid YAML, single ``deploy`` job, NO terraform.
DEPLOY_RENDERED = """\
name: Deploy myapp to ECS
on:
  push:
    branches:
      - main
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: deployment
  cancel-in-progress: true
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
      - name: Log in to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2
      - name: Build and push image
        run: |
          docker build -t img .
          docker push img
      - name: Deploy to Amazon ECS
        run: aws ecs update-service --force-new-deployment
"""

# Same job + delivery markers, but the model injected a terraform step.
DEPLOY_WITH_TERRAFORM = DEPLOY_RENDERED.replace(
    "      - name: Build and push image\n",
    "      - name: Terraform apply\n"
    "        run: terraform apply -auto-approve\n"
    "      - name: Build and push image\n",
)

_TF_FORBIDDEN = ("terraform init", "terraform apply")


def test_forbidden_marker_added_falls_back(monkeypatch, context):
    """An enrichment that injects terraform into deploy.yml is rejected."""
    _patch_llm(monkeypatch, DEPLOY_WITH_TERRAFORM)
    result = SVC.enrich(
        DEPLOY_RENDERED, context, enabled=True, forbidden_markers=_TF_FORBIDDEN
    )
    assert result.applied is False
    assert result.reason == "forbidden_step_added"
    assert result.content == DEPLOY_RENDERED


def test_clean_deploy_enrichment_with_forbidden_guard(monkeypatch, context):
    """A clean enrichment passes even with the forbidden-marker guard active."""
    good = DEPLOY_RENDERED.replace(
        "permissions:\n  contents: read\n",
        "permissions:\n  contents: read\n# tuned by AI\n",
    )
    _patch_llm(monkeypatch, good)
    result = SVC.enrich(
        DEPLOY_RENDERED, context, enabled=True, forbidden_markers=_TF_FORBIDDEN
    )
    assert result.applied is True
    assert result.reason == "ok"
    assert "terraform apply" not in result.content
