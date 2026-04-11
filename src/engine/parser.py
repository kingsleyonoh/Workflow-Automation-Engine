"""Workflow definition parser with DAG validation.

Validates workflow JSON definitions, builds dependency graphs,
detects cycles, enforces depth limits, and validates Jinja2 expressions.
Returns a typed WorkflowDefinition Pydantic model.
"""

from typing import Any

from pydantic import ValidationError

from src.config import settings
from src.engine.graph import (
    build_dependency_graph,
    detect_cycles,
    validate_max_depth,
)
from src.engine.models import StepDefinition, StepType, WorkflowDefinition
from src.lib.logger import get_logger
from src.lib.utils import AppError

logger = get_logger(__name__)

VALID_STEP_TYPES = {t.value for t in StepType}


def parse_workflow_definition(raw: dict[str, Any]) -> WorkflowDefinition:
    """Parse and validate a raw workflow definition dictionary.

    Validates step types, builds the dependency graph, detects cycles,
    enforces depth and step count limits, and validates Jinja2 expressions
    in step configs.

    Args:
        raw: Raw workflow definition dictionary with name, trigger_type,
             and steps array.

    Returns:
        A validated WorkflowDefinition model.

    Raises:
        AppError: With codes NO_STEPS, TOO_MANY_STEPS, UNKNOWN_STEP_TYPE,
                  DUPLICATE_STEP_ID, INVALID_DEPENDENCY, CYCLE_DETECTED,
                  MAX_DEPTH_EXCEEDED, EXPRESSION_ERROR, or VALIDATION_ERROR.
    """
    raw_steps = raw.get("steps", [])

    _validate_step_count(raw_steps)
    steps = _parse_steps(raw_steps)
    _validate_unique_ids(steps)
    _validate_step_types(steps)
    _validate_dependencies(steps)

    graph = build_dependency_graph(steps)
    detect_cycles(graph)
    validate_max_depth(graph)
    _validate_jinja2_expressions(steps)

    return WorkflowDefinition(
        name=raw.get("name", ""),
        trigger_type=raw.get("trigger_type", ""),
        steps=steps,
        dependency_graph=graph,
    )


def _validate_step_count(raw_steps: list[Any]) -> None:
    """Validate the number of steps is within allowed bounds."""
    if not raw_steps:
        raise AppError(
            code="NO_STEPS",
            message="Workflow must contain at least one step.",
            status_code=400,
        )

    if len(raw_steps) > settings.max_steps_per_workflow:
        raise AppError(
            code="TOO_MANY_STEPS",
            message=(
                f"Workflow has {len(raw_steps)} steps, "
                f"exceeding the maximum of "
                f"{settings.max_steps_per_workflow}."
            ),
            status_code=400,
        )


def _parse_steps(raw_steps: list[Any]) -> list[StepDefinition]:
    """Parse raw step dicts into validated StepDefinition models."""
    steps: list[StepDefinition] = []
    for i, raw_step in enumerate(raw_steps):
        try:
            step = StepDefinition(**raw_step)
            steps.append(step)
        except ValidationError as exc:
            step_type = raw_step.get("type", "") if isinstance(raw_step, dict) else ""
            if step_type and step_type not in VALID_STEP_TYPES:
                raise AppError(
                    code="UNKNOWN_STEP_TYPE",
                    message=(f"Unknown step type '{step_type}' on step at index {i}."),
                    status_code=400,
                    details=[{"step_index": i, "step_type": step_type}],
                ) from exc
            raise AppError(
                code="VALIDATION_ERROR",
                message=f"Invalid step at index {i}: {exc}",
                status_code=400,
            ) from exc
        except TypeError as exc:
            raise AppError(
                code="VALIDATION_ERROR",
                message=f"Invalid step at index {i}: {exc}",
                status_code=400,
            ) from exc
    return steps


def _validate_unique_ids(steps: list[StepDefinition]) -> None:
    """Ensure all step IDs are unique."""
    seen: set[str] = set()
    for step in steps:
        if step.id in seen:
            raise AppError(
                code="DUPLICATE_STEP_ID",
                message=f"Duplicate step ID: '{step.id}'.",
                status_code=400,
                details=[{"step_id": step.id}],
            )
        seen.add(step.id)


def _validate_step_types(steps: list[StepDefinition]) -> None:
    """Ensure all step types are recognized."""
    for step in steps:
        if step.type.value not in VALID_STEP_TYPES:
            raise AppError(
                code="UNKNOWN_STEP_TYPE",
                message=(f"Unknown step type '{step.type}' on step '{step.id}'."),
                status_code=400,
                details=[{"step_id": step.id, "step_type": step.type}],
            )


def _validate_dependencies(steps: list[StepDefinition]) -> None:
    """Ensure all depends_on references point to existing step IDs."""
    step_ids = {s.id for s in steps}
    for step in steps:
        for dep in step.depends_on:
            if dep not in step_ids:
                raise AppError(
                    code="INVALID_DEPENDENCY",
                    message=(
                        f"Step '{step.id}' depends on '{dep}', which does not exist."
                    ),
                    status_code=400,
                    details=[{"step_id": step.id, "dependency": dep}],
                )


def _validate_jinja2_expressions(
    steps: list[StepDefinition],
) -> None:
    """Validate Jinja2 syntax in step config string values.

    Scans all string values in step configs for Jinja2 template syntax
    ({{ ... }} or {% ... %}) and validates they can be parsed.
    """
    from jinja2.sandbox import SandboxedEnvironment

    env = SandboxedEnvironment()

    for step in steps:
        _validate_config_expressions(step.id, step.config, env)


def _validate_config_expressions(
    step_id: str,
    config: dict[str, Any],
    env: Any,
) -> None:
    """Recursively validate Jinja2 expressions in a config dict."""
    for key, value in config.items():
        if isinstance(value, str) and _has_jinja2(value):
            _parse_expression(step_id, key, value, env)
        elif isinstance(value, dict):
            _validate_config_expressions(step_id, value, env)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and _has_jinja2(item):
                    _parse_expression(step_id, key, item, env)


def _has_jinja2(value: str) -> bool:
    """Check if a string contains Jinja2 template syntax."""
    return "{{" in value or "{%" in value


def _parse_expression(step_id: str, key: str, value: str, env: Any) -> None:
    """Parse a single Jinja2 expression, raising on error."""
    try:
        env.parse(value)
    except Exception as exc:
        raise AppError(
            code="EXPRESSION_ERROR",
            message=(
                f"Invalid Jinja2 expression in step '{step_id}' "
                f"config key '{key}': {exc}"
            ),
            status_code=400,
            details=[{"step_id": step_id, "key": key}],
        ) from exc
