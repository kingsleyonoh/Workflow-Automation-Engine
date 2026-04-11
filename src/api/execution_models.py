"""Pydantic request/response models for execution API.

Defines the schemas for manual execution trigger, listing executions,
and execution detail with step data, plus cursor-based pagination.
"""

import base64
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.db.models import Execution, ExecutionLog, StepExecution
from src.lib.utils import AppError


class ManualExecuteRequest(BaseModel):
    """Request body for manual workflow execution trigger."""

    trigger_data: dict[str, Any] = Field(default_factory=dict)


class ExecutionResponse(BaseModel):
    """Response model for a single execution."""

    id: uuid.UUID
    workflow_id: uuid.UUID
    status: str
    trigger_data: dict[str, Any]
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    created_at: datetime


class StepExecutionResponse(BaseModel):
    """Response model for a single step execution."""

    id: uuid.UUID
    step_id: str
    step_type: str
    status: str
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    error: str | None
    attempt: int
    max_attempts: int
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    created_at: datetime


class ExecutionListResponse(BaseModel):
    """Response model for paginated execution list."""

    executions: list[ExecutionResponse]
    cursor: str | None


class ExecutionDetailResponse(BaseModel):
    """Response model for execution with step details."""

    execution: ExecutionResponse
    steps: list[StepExecutionResponse]


class ExecutionLogResponse(BaseModel):
    """Response model for a single execution log entry."""

    id: uuid.UUID
    step_id: str | None
    level: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class ExecutionLogsListResponse(BaseModel):
    """Response model for execution logs list."""

    logs: list[ExecutionLogResponse]


class CancelExecutionResponse(BaseModel):
    """Response model for cancel execution."""

    cancelled: bool


class ReplayRequest(BaseModel):
    """Request body for execution replay."""

    override_data: dict[str, Any] = Field(default_factory=dict)


def execution_to_response(ex: Execution) -> ExecutionResponse:
    """Convert an Execution ORM model to a response model."""
    return ExecutionResponse(
        id=ex.id,
        workflow_id=ex.workflow_id,
        status=ex.status,
        trigger_data=ex.trigger_data or {},
        error=ex.error,
        started_at=ex.started_at,
        completed_at=ex.completed_at,
        duration_ms=ex.duration_ms,
        created_at=ex.created_at,
    )


def step_execution_to_response(se: StepExecution) -> StepExecutionResponse:
    """Convert a StepExecution ORM model to a response model."""
    return StepExecutionResponse(
        id=se.id,
        step_id=se.step_id,
        step_type=se.step_type,
        status=se.status,
        input_data=se.input_data or {},
        output_data=se.output_data,
        error=se.error,
        attempt=se.attempt,
        max_attempts=se.max_attempts,
        started_at=se.started_at,
        completed_at=se.completed_at,
        duration_ms=se.duration_ms,
        created_at=se.created_at,
    )


def execution_log_to_response(log: ExecutionLog) -> ExecutionLogResponse:
    """Convert an ExecutionLog ORM model to a response model."""
    return ExecutionLogResponse(
        id=log.id,
        step_id=log.step_id,
        level=log.level,
        message=log.message,
        data=log.data or {},
        created_at=log.created_at,
    )


def encode_execution_cursor(created_at: datetime, ex_id: uuid.UUID) -> str:
    """Encode a pagination cursor from created_at + execution id."""
    raw = f"{created_at.isoformat()}|{ex_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_execution_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode a pagination cursor into created_at + execution id."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        parts = raw.split("|", 1)
        return datetime.fromisoformat(parts[0]), uuid.UUID(parts[1])
    except Exception as exc:
        raise AppError(
            code="INVALID_CURSOR",
            message="Invalid pagination cursor.",
            status_code=400,
        ) from exc
