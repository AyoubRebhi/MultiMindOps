"""
Pydantic schemas for structured LLM output.

These replace raw JSON parsing for infrastructure artifact generation:
  - InfrastructureArtifactsResponse  — full react-loop response from InfrastructureAgent
  - SectionVariablesResponse         — batched section variables from ArtifactSectionGenerator

Usage in ProviderFactory.chat_json():
  The OpenAI json_object response_format guarantees the model returns valid JSON.
  After parsing, callers can optionally validate against these schemas with
  InfrastructureArtifactsResponse.model_validate(parsed_dict) to catch schema drift.

For strict OpenAI json_schema enforcement (INFRA_ARTIFACTS_JSON_SCHEMA), pass the
schema dict as response_format to ProviderFactory.chat_json_structured(). This uses
OpenAI's native schema validation so the model can never return malformed artifacts.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ── Infrastructure artifact schemas ───────────────────────────────────────────

class ArtifactBundle(BaseModel):
    """Docker artifact bundle returned by InfrastructureAgent."""

    dockerfile: str
    dockerignore: str
    docker_compose: str
    env_example: Optional[str] = None
    security_notes: Optional[str] = None


class InfrastructureArtifactsResponse(BaseModel):
    """
    Full InfrastructureAgent ReAct loop response.

    The LLM is instructed (via system prompt) to return this exact shape.
    Schema enforcement via json_object mode guarantees valid JSON; this model
    validates the structural contract after parsing.
    """

    artifacts: ArtifactBundle
    generated_artifacts: List[str] = []
    summary: str = ""


# ── Section generator schema ───────────────────────────────────────────────────

class SectionVariablesResponse(BaseModel):
    """
    Batched section-variable response from ArtifactSectionGenerator.

    Top-level keys are section IDs; values are variable-name → value dicts.
    """

    sections: Dict[str, Dict[str, Any]] = {}


# ── OpenAI json_schema format (strict enforcement) ────────────────────────────
# Pass as response_format to ProviderFactory when strict schema is required.
# strict=True + additionalProperties=false forces the model to match the schema
# exactly — the model CANNOT return unexpected or missing fields.

INFRA_ARTIFACTS_JSON_SCHEMA: Dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "infrastructure_artifacts_response",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "artifacts": {
                    "type": "object",
                    "properties": {
                        "dockerfile": {"type": "string"},
                        "dockerignore": {"type": "string"},
                        "docker_compose": {"type": "string"},
                        "env_example": {
                            "anyOf": [{"type": "string"}, {"type": "null"}]
                        },
                        "security_notes": {
                            "anyOf": [{"type": "string"}, {"type": "null"}]
                        },
                    },
                    "required": [
                        "dockerfile",
                        "dockerignore",
                        "docker_compose",
                        "env_example",
                        "security_notes",
                    ],
                    "additionalProperties": False,
                },
                "generated_artifacts": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "summary": {"type": "string"},
            },
            "required": ["artifacts", "generated_artifacts", "summary"],
            "additionalProperties": False,
        },
    },
}
