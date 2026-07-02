"""Automatic Terraform import recovery.

When ``terraform apply`` fails because AWS resources already exist
(RepositoryAlreadyExists / EntityAlreadyExists / ClusterAlreadyExists /
BucketAlreadyOwnedByYou …), this package adopts those resources into Terraform
state and retries the deployment — so no one runs ``terraform import`` by hand::

    detect → safety-check → import → refresh → plan → apply

It is a standalone, modular service (NOT wired into workflow orchestration) with
an injectable terraform runner, so the recovery logic is fully unit-testable.
"""

from backend.app.services.terraform_import.failure_parser import parse_failure
from backend.app.services.terraform_import.import_service import (
    TerraformBinaryMissingError,
    TerraformImportService,
)
from backend.app.services.terraform_import.models import (
    SUPPORTED_RESOURCE_TYPES,
    ImportableResource,
    ImportOutcome,
    ImportRecoveryResult,
)
from backend.app.services.terraform_import.safety import (
    ImportSafetyContext,
    validate_resource,
)

__all__ = [
    "TerraformImportService",
    "TerraformBinaryMissingError",
    "parse_failure",
    "validate_resource",
    "ImportSafetyContext",
    "ImportableResource",
    "ImportOutcome",
    "ImportRecoveryResult",
    "SUPPORTED_RESOURCE_TYPES",
]
