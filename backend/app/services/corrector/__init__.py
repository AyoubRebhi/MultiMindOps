"""
Corrector Agent package.

Public surface:
  DockerCorrectorAgent  — analyze Docker build failures
  CorrectorResult       — structured output schema
  FailureType           — failure taxonomy enum
  CorrectorExecutionState — workflow_state persistence model
"""

from .base_corrector import BaseCorrectorAgent
from .docker_corrector import DockerCorrectorAgent
from .remediation_models import (
    CorrectorExecutionState,
    CorrectorResult,
    ExtractedError,
    FailureClassification,
    FailureType,
    RemediationFix,
    RemediationSeverity,
)

__all__ = [
    "BaseCorrectorAgent",
    "DockerCorrectorAgent",
    "CorrectorExecutionState",
    "CorrectorResult",
    "ExtractedError",
    "FailureClassification",
    "FailureType",
    "RemediationFix",
    "RemediationSeverity",
]
