"""Infrastructure Destroy phase.

Tear down the AWS infrastructure MultiMindOps provisioned, WITHOUT the backend
ever running Terraform — GitHub Actions remains the execution engine. The phase
composes the platform's existing building blocks:

* generation  → reuse the GitHub Actions renderer (a target-agnostic
  ``destroy.yml.j2``),
* installation → reuse :class:`RepositoryInstallationService` to commit
  ``.github/workflows/destroy.yml`` (+ ``terraform/``) onto a dedicated branch,
* dispatch     → reuse ``workflow_dispatch`` to auto-trigger ``destroy.yml``,
* monitoring   → reuse the read-only GitHub Actions client to observe the run
  EXACTLY like ``bootstrap.yml`` and reconcile the persisted lifecycle state.
"""

from backend.app.services.infrastructure_destroy.destroy_service import (
    InfrastructureDestroyService,
)

__all__ = ["InfrastructureDestroyService"]
