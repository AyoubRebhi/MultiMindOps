"""Helpers shared by renderers and validators."""

from backend.app.services.terraform_generation.utils.variable_context import (
    build_variable_context,
)

__all__ = ["build_variable_context"]
