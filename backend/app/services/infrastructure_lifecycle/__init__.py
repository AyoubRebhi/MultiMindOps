"""Infrastructure Lifecycle Management — the post-deployment operational phase.

Aggregates capabilities the platform already has (destroy, monitoring, recovery,
automatic import) into one control surface, plus an immutable lifecycle history.
Pure composition — no new orchestration engine, no workers; GitHub Actions stays
the only execution engine and the backend never runs Terraform.
"""

from backend.app.services.infrastructure_lifecycle.lifecycle_event_service import (
    LifecycleEventService,
)
from backend.app.services.infrastructure_lifecycle.lifecycle_service import (
    InfrastructureLifecycleService,
)
from backend.app.services.infrastructure_lifecycle.resource_inventory import (
    build_inventory,
    parse_state_location,
)

__all__ = [
    "InfrastructureLifecycleService",
    "LifecycleEventService",
    "build_inventory",
    "parse_state_location",
]
