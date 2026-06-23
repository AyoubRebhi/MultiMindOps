"""GitHub Actions deployment-workflow generation.

A DEPLOYMENT ORCHESTRATION phase — NOT a CI builder and NOT a repo analyser.
It consumes artifacts that earlier phases already produced and validated
(Terraform .tf files, the Docker build inputs, the selected architecture
decision) and renders a single ``.github/workflows/deploy.yml`` that wires
them into a GitHub Actions deployment.

Pipeline (see ``generation_service.GitHubActionsGenerationService``):

    deployment context   (DeploymentContextBuilder — from DB artifacts + plan)
        ↓
    template selection   (deployment_target → ecs/eks/lambda/ec2 template)
        ↓
    Jinja2 render        (deterministic — the template is the source of truth)
        ↓
    optional LLM enrich  (DEFAULT OFF; never generates the workflow from scratch)
        ↓
    YAML validation      (reject invalid/empty/malformed BEFORE persistence)

The module owns NO infrastructure execution: it never runs terraform, never
builds an image, never talks to GitHub. It only emits the workflow file.
"""
