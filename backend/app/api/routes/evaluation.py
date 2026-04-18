"""
Evaluation API — LLM-as-a-Judge endpoints.

POST /evaluation/judge
    Evaluate a single generated artifact (Dockerfile, YAML, Python, …).

POST /evaluation/plan
    Evaluate an AI-generated DevSecOps execution plan on 4 metrics:
    completeness, clarity, agent_readiness, security_fit.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.app.services.quality.llm_judge_service import get_llm_judge_service
from backend.app.services.quality.plan_judge_service import get_plan_judge_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

ArtifactType = Literal[
    "dockerfile",
    "docker-compose",
    "python",
    "yaml",
    "terraform",
    "typescript",
    "documentation",
]


class JudgeRequest(BaseModel):
    artifact_type: str = Field(
        ...,
        description=(
            "Type of artifact to evaluate. "
            "One of: dockerfile | docker-compose | python | yaml | "
            "terraform | typescript | documentation"
        ),
        examples=["dockerfile"],
    )
    artifact_content: str = Field(
        ...,
        description="Raw text content of the artifact to evaluate.",
        min_length=1,
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional hints for the evaluator, e.g. "
            '{"framework": "FastAPI", "python_version": "3.11"}.'
        ),
    )

    @field_validator("artifact_content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("artifact_content must not be blank")
        return v


class MetricDetail(BaseModel):
    score: int = Field(..., ge=0, le=100)
    feedback: str


class JudgeResponse(BaseModel):
    artifact_type: str
    global_score: int = Field(..., ge=0, le=100)
    metrics: Dict[str, MetricDetail]
    recommendations: List[str]
    detailed_report: str


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post(
    "/judge",
    response_model=JudgeResponse,
    summary="Evaluate an artifact with LLM-as-a-Judge",
    description=(
        "Submit any generated artifact (Dockerfile, Compose file, Python code, "
        "YAML, Terraform, TypeScript, or documentation) to be evaluated by the "
        "GLM-5.1:cloud model. Returns per-metric scores (0-100) weighted into a "
        "global score, plus top-3 actionable recommendations."
    ),
)
def judge_artifact(payload: JudgeRequest) -> JudgeResponse:
    """Synchronous endpoint — GLMService uses the blocking OpenAI SDK."""
    judge = get_llm_judge_service()

    try:
        result = judge.evaluate_artifact(
            artifact_type=payload.artifact_type,
            content=payload.artifact_content,
            context=payload.context,
        )
    except Exception as exc:
        logger.error("Unexpected error in /evaluation/judge: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Evaluation failed: {type(exc).__name__}: {exc}",
        ) from exc

    # global_score == 0 with no metrics feedback usually means a hard failure
    if result["global_score"] == 0 and not any(
        m["score"] > 0 for m in result["metrics"].values()
    ):
        raise HTTPException(
            status_code=502,
            detail=result.get("detailed_report", "LLM evaluation returned no usable scores."),
        )

    return JudgeResponse(
        artifact_type=result["artifact_type"],
        global_score=result["global_score"],
        metrics={k: MetricDetail(**v) for k, v in result["metrics"].items()},
        recommendations=result["recommendations"],
        detailed_report=result["detailed_report"],
    )


# ---------------------------------------------------------------------------
# Plan evaluation
# ---------------------------------------------------------------------------


class PlanJudgeRequest(BaseModel):
    plan_dict: Dict[str, Any] = Field(
        ...,
        description=(
            "The plan dict returned by the planner. "
            "Expected keys: steps, required_artifacts, reasoning_summary, "
            "estimated_complexity."
        ),
    )
    original_prompt: str = Field(
        ...,
        description="The user's original task description.",
        min_length=1,
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional hints for the evaluator, e.g. "
            '{"language": "Java", "framework": "Spring Boot", "has_docker": true}.'
        ),
    )

    @field_validator("original_prompt")
    @classmethod
    def prompt_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("original_prompt must not be blank")
        return v


@router.post(
    "/plan",
    response_model=JudgeResponse,
    summary="Evaluate a DevSecOps plan with LLM-as-a-Judge",
    description=(
        "Submit an AI-generated DevSecOps execution plan to be evaluated by "
        "GLM-5:cloud on four axes: completeness, clarity, agent_readiness, "
        "and security_fit. Returns per-metric scores (0-100), a weighted global "
        "score, and top-3 actionable recommendations."
    ),
)
def judge_plan(payload: PlanJudgeRequest) -> JudgeResponse:
    """Synchronous endpoint — GLMService uses the blocking OpenAI SDK."""
    judge = get_plan_judge_service()

    try:
        result = judge.evaluate_plan(
            plan=payload.plan_dict,
            original_prompt=payload.original_prompt,
            context=payload.context,
        )
    except Exception as exc:
        logger.error("Unexpected error in /evaluation/plan: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Plan evaluation failed: {type(exc).__name__}: {exc}",
        ) from exc

    if result["global_score"] == 0 and not any(
        m["score"] > 0 for m in result["metrics"].values()
    ):
        raise HTTPException(
            status_code=502,
            detail=result.get("detailed_report", "LLM plan evaluation returned no usable scores."),
        )

    return JudgeResponse(
        artifact_type="plan",
        global_score=result["global_score"],
        metrics={k: MetricDetail(**v) for k, v in result["metrics"].items()},
        recommendations=result["recommendations"],
        detailed_report=result["detailed_report"],
    )
