"""Shared utilities for the Workflow Automation Engine.

Provides common helpers used across modules: UUID generation, UTC timestamps,
standard error response models, and application exception handling.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def generate_uuid() -> uuid.UUID:
    """Generate a new UUID v4.

    Returns:
        A randomly generated UUID.
    """
    return uuid.uuid4()


def utc_now() -> datetime:
    """Get the current UTC datetime with timezone info.

    Returns:
        Timezone-aware UTC datetime.
    """
    return datetime.now(UTC)


class ErrorDetail(BaseModel):
    """Single detail entry within an error response."""

    model_config = {"extra": "allow"}


class ErrorBody(BaseModel):
    """Inner error object in the standard error response format.

    Format: {"code": "ERROR_CODE", "message": "Human-readable", "details": [...]}
    """

    code: str = Field(description="Machine-readable error code (e.g. CYCLE_DETECTED)")
    message: str = Field(description="Human-readable error description")
    details: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Additional structured error context",
    )


class ErrorResponse(BaseModel):
    """Standard error response wrapper.

    Format: {"error": {"code": "...", "message": "...", "details": [...]}}
    All API error responses MUST use this format.
    """

    error: ErrorBody


def create_error_response(
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a standardized error response dictionary.

    Args:
        code: Machine-readable error code (e.g. "VALIDATION_ERROR").
        message: Human-readable error description.
        details: Optional list of additional error context dicts.

    Returns:
        Dictionary matching the standard error response format.
    """
    response = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or [],
        )
    )
    return response.model_dump()


class AppError(Exception):
    """Application error that carries structured error information.

    Raise this from any layer. The error middleware catches it and returns
    the standard JSON error response with the appropriate HTTP status code.

    Attributes:
        status_code: HTTP status code to return (default 400).
        code: Machine-readable error code.
        message: Human-readable error description.
        details: Optional list of additional context dicts.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []
        super().__init__(message)
