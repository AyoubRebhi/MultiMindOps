"""
Pydantic models for the Corrector Agent system.

These models define the structured output contract for all corrector agents.
All analysis results must conform to these schemas — no raw text blobs.

Phase 2 additions:
  • StructuredPatch    — exact file-level patches (target + replacement)
  • FailureConfidence  — per-dimension confidence scores
  • MultiStageAnalysis — primary + secondary + future failure breakdown
  • DistroContext      — distro/package-manager context for contextual remediation
  • CorrectorResult    — extended with patches, confidence, multi-stage, anti-patterns
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

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
    DISTRO_MISMATCH = "distro_mismatch"
    EXEC_FORM_INVALID = "exec_form_invalid"
    HEALTHCHECK_DEPENDENCY = "healthcheck_dependency"
    UNKNOWN_FAILURE = "unknown_failure"


class RemediationSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PatchOperation(str, Enum):
    REPLACE = "replace"
    PREPEND_BEFORE = "prepend_before"
    APPEND_AFTER = "append_after"
    DELETE = "delete"


class CorrectorPhase(str, Enum):
    """Workflow phases introduced by the corrector lifecycle."""
    CORRECTOR_ANALYSIS_RUNNING = "corrector_analysis_running"
    CORRECTOR_ANALYSIS_COMPLETED = "corrector_analysis_completed"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    EXECUTION_FAILED = "execution_failed"


# ── New Phase 2 models ────────────────────────────────────────────────────────

class StructuredPatch(BaseModel):
    """
    Exact file-level patch for precise programmatic application.

    The frontend can render this as a diff; the regeneration loop feeds it
    back to the InfrastructureAgent to guide section regeneration.
    """
    file: str                                   # "Dockerfile" | "requirements.txt" | etc.
    operation: PatchOperation = PatchOperation.REPLACE
    target: str                                 # Exact line/block to replace
    replacement: str                            # Corrected content
    reason: str
    section_id: Optional[str] = None           # Linked blueprint section (if known)
    confidence: float = Field(ge=0.0, le=1.0, default=0.9)


class FailureConfidence(BaseModel):
    """Per-dimension confidence scores for the analysis result."""
    overall: float = Field(ge=0.0, le=1.0, description="Overall analysis confidence")
    root_cause: float = Field(ge=0.0, le=1.0, description="Root cause identification confidence")
    fix: float = Field(ge=0.0, le=1.0, description="Fix correctness confidence")
    runtime_success: float = Field(
        ge=0.0, le=1.0,
        description="Probability of successful build after applying fixes",
    )


class SecondaryFailure(BaseModel):
    """A cascading or latent failure identified alongside the primary."""
    failure_type: FailureType
    description: str
    severity: RemediationSeverity = RemediationSeverity.MEDIUM
    will_surface: str  # "immediately" | "at_runtime" | "under_load" | "conditionally"


class MultiStageAnalysis(BaseModel):
    """
    Layered failure analysis: primary cause + cascading issues + hidden future failures.

    Example:
      primary:    invalid base image (build fails immediately)
      secondary:  curl missing (healthcheck would fail at runtime)
      future:     actuator endpoint assumed — may fail under load if not configured
    """
    primary_failure: str
    secondary_failures: List[SecondaryFailure] = Field(default_factory=list)
    future_risks: List[str] = Field(default_factory=list)
    fix_order: List[str] = Field(
        default_factory=list,
        description="Ordered list of fix steps (apply in this sequence)",
    )


class DistroContext(BaseModel):
    """Detected distro/package-manager context for contextual remediation."""
    detected_family: Optional[str] = None       # "alpine" | "debian" | "ubi" | "unknown"
    package_manager: Optional[str] = None       # "apt" | "apk" | "dnf"
    runtime_image: Optional[str] = None
    builder_image: Optional[str] = None


class RegenerationGuidance(BaseModel):
    """
    Structured guidance fed back to InfrastructureAgent for regeneration.

    When the corrector sends this back, the generator's next iteration avoids
    the patterns that caused the failure and applies the explicit patches.
    """
    avoid_patterns: List[str] = Field(
        default_factory=list,
        description="Anti-patterns to avoid in next generation attempt",
    )
    force_variables: Dict[str, str] = Field(
        default_factory=dict,
        description="Section variable overrides to apply deterministically",
    )
    section_hints: Dict[str, str] = Field(
        default_factory=dict,
        description="Per-section corrective hints for the LLM prompt",
    )


# ── Unchanged core models (backward compatible) ───────────────────────────────

class RemediationFix(BaseModel):
    """A single actionable remediation suggestion."""
    title: str
    explanation: str
    patch: Optional[str] = None
    severity: RemediationSeverity = RemediationSeverity.MEDIUM
    applies_to: Optional[str] = None


class FailureClassification(BaseModel):
    """Result of the deterministic failure classifier."""
    failure_type: FailureType
    confidence: float = Field(ge=0.0, le=1.0)
    matched_rule: Optional[str] = None
    secondary_type: Optional[FailureType] = None


class ExtractedError(BaseModel):
    """Deterministically extracted error information from raw logs."""
    last_error_line: Optional[str] = None
    failed_step: Optional[str] = None
    failed_line_number: Optional[int] = None
    exit_code: Optional[int] = None
    error_excerpt: Optional[str] = None
    stack_trace: Optional[str] = None
    stderr_summary: Optional[str] = None
    package_manager: Optional[str] = None


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

    Phase 2 extensions are optional to preserve backward compatibility with
    existing API consumers that only read the Phase 1 fields.
    """
    # ── Phase 1 fields (unchanged) ────────────────────────────────────────────
    status: str                     # "analyzed" | "error"
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

    # ── Phase 2 extensions ────────────────────────────────────────────────────
    structured_patches: List[StructuredPatch] = Field(
        default_factory=list,
        description="Exact file-level patches ready for programmatic application",
    )
    failure_confidence: Optional[FailureConfidence] = Field(
        default=None,
        description="Per-dimension confidence scores",
    )
    multi_stage_analysis: Optional[MultiStageAnalysis] = Field(
        default=None,
        description="Primary + cascading + future failure breakdown",
    )
    distro_context: Optional[DistroContext] = Field(
        default=None,
        description="Detected distro context for contextual remediation",
    )
    regeneration_guidance: Optional[RegenerationGuidance] = Field(
        default=None,
        description="Structured feedback for the InfrastructureAgent regeneration loop",
    )

    def to_dict(self) -> dict:
        data = self.model_dump()
        data["error_type"] = self.error_type.value
        data["fixes"] = [
            {
                **f,
                "severity": (
                    f["severity"]
                    if isinstance(f["severity"], str)
                    else f["severity"].value
                ),
            }
            for f in data["fixes"]
        ]
        if data.get("structured_patches"):
            for p in data["structured_patches"]:
                if isinstance(p.get("operation"), str):
                    pass  # Already serialized
                elif hasattr(p.get("operation"), "value"):
                    p["operation"] = p["operation"].value
        return data


class CorrectorExecutionState(BaseModel):
    """
    Persisted at workflow_state.execution.corrector.
    Tracks retry lifecycle and latest analysis result.
    """
    status: str = "pending"
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
