"""Pydantic request/response models for workflow CRUD API.

Defines the schemas for creating, updating, and listing workflows,
plus cursor-based pagination helpers.
"""

import base64
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.db.models import Workflow
from src.lib.utils import AppError, generate_uuid


class WorkflowCreateRequest(BaseModel):
    """Request body for creating a workflow."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    trigger_type: str = Field(..., pattern=r"^(webhook|cron|manual)$")
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    steps: list[dict[str, Any]] = Field(..., min_length=1)
    is_active: bool = True


class WorkflowUpdateRequest(BaseModel):
    """Request body for updating a workflow. All fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    trigger_type: str | None = Field(default=None, pattern=r"^(webhook|cron|manual)$")
    trigger_config: dict[str, Any] | None = None
    steps: list[dict[str, Any]] | None = None
    is_active: bool | None = None


class WorkflowResponse(BaseModel):
    """Response model for a workflow."""

    id: uuid.UUID
    name: str
    description: str | None
    trigger_type: str
    trigger_config: dict[str, Any]
    steps: list[dict[str, Any]]
    is_active: bool
    webhook_path: str | None
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    """Response model for paginated workflow list."""

    workflows: list[WorkflowResponse]
    cursor: str | None


def generate_webhook_path() -> str:
    """Generate a unique webhook path slug."""
    return f"wh_{generate_uuid().hex[:24]}"


def workflow_to_response(wf: Workflow) -> WorkflowResponse:
    """Convert a Workflow ORM model to a response model."""
    return WorkflowResponse(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        trigger_type=wf.trigger_type,
        trigger_config=wf.trigger_config or {},
        steps=wf.steps or [],
        is_active=wf.is_active,
        webhook_path=wf.webhook_path,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


def encode_cursor(created_at: datetime, wf_id: uuid.UUID) -> str:
    """Encode a pagination cursor from created_at + workflow id."""
    raw = f"{created_at.isoformat()}|{wf_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decode a pagination cursor into created_at + workflow id."""
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
