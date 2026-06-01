"""Pydantic schemas for the execution-jobs API.

``execution_context`` is intentionally NOT exposed in the response — it can
carry artifact bodies and is an internal worker concern. Clients get the
lifecycle metadata they need to render progress + offer cancellation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    """Lifecycle view of a job. No execution_context, no secrets."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    workflow_id: Optional[str]
    task_id: Optional[str]
    phase: str
    status: str
    cancel_requested: str
    retry_count: int
    max_retries: int
    worker_id: Optional[str]
    logs_reference: Optional[str]
    result_summary: Optional[dict[str, Any]]
    error_message: Optional[str]
    heartbeat_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class JobCancelResponse(BaseModel):
    id: str
    status: str
    message: str
