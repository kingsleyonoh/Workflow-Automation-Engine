"""Pydantic models for workflow definition parsing.

Defines the schema for step definitions, retry configuration,
and the validated workflow definition returned by the parser.
"""

import enum
from typing import Any

from pydantic import BaseModel, Field


class StepType(enum.StrEnum):
    """Valid step types for workflow definitions."""

    HTTP = "http"
    TRANSFORM = "transform"
    CONDITION = "condition"
    DELAY = "delay"
    SUB_WORKFLOW = "sub_workflow"


class RetryConfig(BaseModel):
    """Retry configuration for a workflow step.

    Controls how many times a failed step is retried and the
    delay between attempts.
    """

    max_attempts: int = Field(default=3, ge=1, le=10)
    delay_seconds: int = Field(default=5, ge=0, le=300)


class StepDefinition(BaseModel):
    """A single step within a workflow definition.

    Each step has a unique ID, a type, configuration, optional
    dependencies on other steps, and optional retry settings.
    """

    id: str = Field(..., min_length=1, max_length=100)
    type: StepType
    config: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    retry: RetryConfig | None = None


class WorkflowDefinition(BaseModel):
    """Validated workflow definition returned by the parser.

    Contains the parsed steps, the computed dependency graph,
    and metadata from the raw workflow definition.
    """

    name: str
    trigger_type: str
    steps: list[StepDefinition]
    dependency_graph: dict[str, list[str]] = Field(default_factory=dict)
