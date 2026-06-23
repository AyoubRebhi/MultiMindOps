---
name: project_github_actions_phase
description: New GITHUB_ACTIONS_GENERATION deployment phase — renders deploy.yml from validated Docker+Terraform artifacts (June 2026)
metadata:
  type: project
---

New workflow phase `GITHUB_ACTIONS_GENERATION` — a DEPLOYMENT orchestration phase (not a CI builder / not repo analysis). Consumes validated Docker + Terraform artifacts + the architecture decision and renders ONE `.github/workflows/deploy.yml`. Deployment target is DERIVED from the selected blueprint's `compute.type` (ECS→ecs, EKS→eks, Lambda→lambda, EC2→ec2) — never asked. Added after Terraform Plan in the journey. (June 2026)

**Backend** (`backend/app/services/github_actions_generation/`):
- `models.DeploymentContext` (pydantic) + `deployment_context_builder.py` (reads `state["plan"]["infrastructure_blueprint"]`, DB docker/terraform artifacts via `ArtifactPersistenceService.get_docker_artifacts/get_terraform_files`; reuses terraform `build_variable_context` so deploy.yml references the SAME ECR/ECS/EKS/Lambda names Terraform creates).
- `templates/{ecs,eks,lambda,ec2}_deploy.yml.j2` — Jinja with **custom delimiters `<< >>`** (block `<% %>`, comment `<# #>`) so GitHub `${{ }}` passes through untouched. `renderer.py` (StrictUndefined). `template_selector.py`.
- `yaml_validator.py` (rejects empty/invalid/malformed; note: `on:` parses to boolean `True` under PyYAML — checked). `enrichment.py` (optional LLM, DEFAULT OFF via `settings.GITHUB_ACTIONS_LLM_ENRICH`, guarded: must validate + preserve job set else falls back to template). `generation_service.py` ties it: context→select→render→enrich→validate.

**Wiring**: `WorkflowOrchestrationService._run_github_actions_generation` (inline like TF generation; prereqs PLAN_SELECTED+DOCKER+TERRAFORM_GENERATION completed; persists artifact `type=github_actions` subtype `.github/workflows/deploy.yml` ONLY when valid; success marks workflow `completed`). Added `PHASE_GH_ACTIONS` const + to `PhaseName` literal. Read projection: `github_actions_phase_projection_service.py` + schema + `GET /api/projects/{pid}/workflows/{wid}/github-actions`.

**Frontend**: `WorkflowGithubActionsPhase.jsx` + `useGithubActionsPhase` hook + `workflowApi.getGithubActionsPhase/runGithubActionsPhase` + `mapGithubActionsPhase`. constants: phase view `github_actions` added to `WORKFLOW_PHASE_VIEW`/`IMPLEMENTED_WORKFLOW_VIEWS`/`BACKEND_WORKFLOW_PHASE_META`; timeline reuses existing `cicd` step. "Proceed to GitHub Actions" button added to Terraform phase. Wired into `WorkflowRunPage`.

Tests: `tests/test_github_actions_generation.py` (13, all pass). The legacy `services/cicd/*` + `cicd_agent` (generic CI) are deactivated and were NOT touched. Relates to [[project_terraform_generation_phase]], [[project_docker_generation_phase]], [[project_workflow_engine_unification]].
