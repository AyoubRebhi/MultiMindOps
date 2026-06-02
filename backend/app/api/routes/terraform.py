"""
Minimal Terraform generation + validation API.

Two endpoints, no auth, no projects, no orchestrator coupling — this is the
"hello world" path for the template-driven pipeline:

    POST /terraform/generate          → render + persist
    POST /terraform/validate/{id}     → terraform init + validate
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.services.terraform_pipeline import (
    ArtifactNotFoundError,
    TerraformPipelineService,
    UnsupportedArchitectureError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/terraform", tags=["Terraform"])

# Single shared service instance — stateless aside from the storage root.
_service = TerraformPipelineService()


# ── Request / response schemas ───────────────────────────────────────────────


class GenerateRequest(BaseModel):
    architecture: Literal["monolith", "microservices", "serverless"] = Field(
        ..., description="Architecture style to generate Terraform for."
    )
    tier: Literal["balanced"] = Field(
        "balanced",
        description="Strategy tier. Only 'balanced' is supported by the minimal pipeline.",
    )
    project_name: Optional[str] = Field(
        None,
        description="Optional project name; used as the prefix for AWS resources.",
        max_length=32,
    )


class GenerateResponse(BaseModel):
    id: str
    files: Dict[str, str]
    metadata: Dict[str, Any]


class ValidateResponse(BaseModel):
    id: str
    valid: bool
    init: Dict[str, Any]
    validate_result: Dict[str, Any] = Field(alias="validate")
    duration_ms: int

    model_config = {"populate_by_name": True}


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest) -> GenerateResponse:
    """Generate Terraform for the requested architecture/tier and persist it."""
    try:
        result = _service.generate(
            architecture=req.architecture,
            tier=req.tier,
            project_name=req.project_name,
        )
    except UnsupportedArchitectureError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[terraform.generate] generation failed")
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}") from exc

    return GenerateResponse(**result.to_dict())


@router.post("/validate/{artifact_id}", response_model=ValidateResponse, response_model_by_alias=True)
def validate_artifact(artifact_id: str) -> ValidateResponse:
    """Run ``terraform init`` + ``terraform validate`` against a generated artifact."""
    try:
        result = _service.validate(artifact_id)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        # Terraform binary missing.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("[terraform.validate] validation failed")
        raise HTTPException(status_code=500, detail=f"Validation failed: {exc}") from exc

    return ValidateResponse.model_validate(result.to_dict())


@router.get("/artifacts/{artifact_id}", response_model=GenerateResponse)
def get_artifact(artifact_id: str) -> GenerateResponse:
    """Convenience read-back for a persisted artifact."""
    try:
        result = _service.load(artifact_id)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GenerateResponse(**result.to_dict())
