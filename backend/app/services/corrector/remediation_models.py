"""
Pydantic models for the Corrector Agent system.

These models define the structured output contract for all corrector agents.
All analysis results must conform to these schemas — no raw text blobs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class FailureType(str, Enum):
    DEPENDENCY_FAILURE = "dependency_failure"
    PERMISSION_FAILURE = "permission_failure"
    MISSING_FILE = "missing_file"
    NETWORK_FAILURE = "network_failure"
    SYNTAX_ERROR = "syntax_error"
    PACKAGE_MANAGER_FAILURE = "package_manager_failure"
    BASE_IMAGE_FAILURE = "base_image_failure"
    ENVIRONMENT_VARIABLE_FAILURE = "environment_variable_failure"
    BUILD_CONTEXT_FAILURE = "build_context_failure"
    UNKNOWN_FAILURE = "unknown_failure"


class RemediationSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CorrectorPhase(str, Enum):
    """Workflow phases introduced by the corrector lifecycle."""
    CORRECTOR_ANALYSIS_RUNNING = "corrector_analysis_running"
    CORRECTOR_ANALYSIS_COMPLETED = "corrector_analysis_completed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    EXECUTION_FAILED = "execution_failed"  # Max retries exceeded


class RemediationFix(BaseModel):
    """A single actionable remediation suggestion."""
    title: str
    explanation: str
    patch: Optional[str] = None  # Concrete Dockerfile line or shell command hint
    severity: RemediationSeverity = RemediationSeverity.MEDIUM
    applies_to: Optional[str] = None  # e.g. "Dockerfile", "requirements.txt"


class FailureClassification(BaseModel):
    """Result of the deterministic failure classifier."""
    failure_type: FailureType
    confidence: float = Field(ge=0.0, le=1.0)
    matched_rule: Optional[str] = None
    secondary_type: Optional[FailureType] = None


class ExtractedError(BaseModel):
    """Deterministically extracted error information from raw logs."""
    last_error_line: Optional[str] = None
    failed_step: Optional[str] = None        # Dockerfile step, e.g. "RUN npm install"
    failed_line_number: Optional[int] = None
    exit_code: Optional[int] = None
    error_excerpt: Optional[str] = None      # Up to 10 lines around the error
    stack_trace: Optional[str] = None
    stderr_summary: Optional[str] = None
    package_manager: Optional[str] = None   # "npm" | "pip" | "apt" | "yarn" | ...


class FailureAnalysis(BaseModel):
    """Full combined analysis: classification + extraction + narrative."""
    classification: FailureClassification
    extracted_error: ExtractedError
    root_cause: str
    retry_recommended: bool
    fixes: List[RemediationFix] = Field(default_factory=list)
    llm_enriched: bool = False


class CorrectorResult(BaseModel):
    """
    Complete structured output of a corrector agent run.
    Persisted at workflow_state.execution.corrector.analysis.
    """
    status: str  # "analyzed" | "error"
    error_type: FailureType
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    failed_step: Optional[str] = None
    failed_line: Optional[int] = None
    error_excerpt: Optional[str] = None
    retry_recommended: bool = True
    fixes: List[RemediationFix] = Field(default_factory=list)
    llm_enriched: bool = False
    analyzed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        data = self.model_dump()
        # Ensure nested enums are serialized as strings
        data["error_type"] = self.error_type.value
        data["fixes"] = [
            {**f, "severity": f["severity"] if isinstance(f["severity"], str) else f["severity"].value}
            for f in data["fixes"]
        ]
        return data


class CorrectorExecutionState(BaseModel):
    """
    Persisted at workflow_state.execution.corrector.
    Tracks retry lifecycle and latest analysis result.
    """
    status: str = "pending"   # "pending" | "running" | "completed" | "error"
    retry_count: int = 0
    max_retries: int = 3
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    analysis: Optional[CorrectorResult] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        data = self.model_dump()
        if self.analysis is not None:
            data["analysis"] = self.analysis.to_dict()
        return data
