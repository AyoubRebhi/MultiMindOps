"""Infrastructure Recovery phase — read-only diagnosis of a failed provisioning.

When ``bootstrap.yml`` fails during ``terraform apply``, this layer inspects the
failed run (read-only), the generated Terraform + remote state backend, and
classifies the failure into a structured :class:`RecoveryReport` with concrete
recovery recommendations. It NEVER runs ``terraform apply`` / ``destroy`` /
``import`` and never touches AWS — the engineer decides what to do.
"""

from backend.app.services.infrastructure_recovery.recovery_service import (
    InfrastructureRecoveryService,
)

__all__ = ["InfrastructureRecoveryService"]
