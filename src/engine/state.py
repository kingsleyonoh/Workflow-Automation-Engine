"""State machine for execution and step status transitions.

Validates that transitions are legal, then persists the new status
to PostgreSQL. Invalid transitions raise AppError with code
INVALID_TRANSITION.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Execution, StepExecution
from src.lib.logger import get_logger
from src.lib.utils import AppError, utc_now

logger = get_logger(__name__)

# Execution: pending -> running -> completed/failed/cancelled
ALLOWED_EXECUTION_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

# Step: pending -> queued -> running -> completed/failed/skipped
# failed -> queued is allowed for retries
ALLOWED_STEP_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"queued", "skipped"},
    "queued": {"running"},
    "running": {"completed", "failed"},
    "completed": set(),
    "failed": {"queued"},
    "skipped": set(),
}


def validate_execution_transition(current_status: str, new_status: str) -> None:
    """Validate that an execution state transition is legal.

    Args:
        current_status: Current execution status.
        new_status: Desired new execution status.

    Raises:
        AppError: INVALID_TRANSITION if the transition is not allowed.
    """
    allowed = ALLOWED_EXECUTION_TRANSITIONS.get(current_status)
    if allowed is None or new_status not in allowed:
        raise AppError(
            code="INVALID_TRANSITION",
            message=(
                f"Invalid execution transition: '{current_status}' -> '{new_status}'"
            ),
            status_code=409,
        )


def validate_step_transition(current_status: str, new_status: str) -> None:
    """Validate that a step state transition is legal.

    Args:
        current_status: Current step status.
        new_status: Desired new step status.

    Raises:
        AppError: INVALID_TRANSITION if the transition is not allowed.
    """
    allowed = ALLOWED_STEP_TRANSITIONS.get(current_status)
    if allowed is None or new_status not in allowed:
        raise AppError(
            code="INVALID_TRANSITION",
            message=(f"Invalid step transition: '{current_status}' -> '{new_status}'"),
            status_code=409,
        )


async def transition_execution(
    session: AsyncSession,
    execution_id: uuid.UUID,
    new_status: str,
) -> Execution:
    """Transition an execution to a new status in the database.

    Fetches the execution, validates the transition, updates the
    status, and flushes to the database.

    Args:
        session: Async SQLAlchemy session.
        execution_id: UUID of the execution to transition.
        new_status: Desired new status.

    Returns:
        The updated Execution instance.

    Raises:
        AppError: NOT_FOUND if execution doesn't exist.
        AppError: INVALID_TRANSITION if the transition is not allowed.
    """
    stmt = select(Execution).where(Execution.id == execution_id)
    result = await session.execute(stmt)
    execution = result.scalar_one_or_none()

    if execution is None:
        raise AppError(
            code="NOT_FOUND",
            message="Execution not found.",
            status_code=404,
        )

    validate_execution_transition(execution.status, new_status)

    execution.status = new_status
    now = utc_now()

    if new_status == "running":
        execution.started_at = now
    elif new_status in ("completed", "failed", "cancelled"):
        execution.completed_at = now
        if execution.started_at:
            delta = now - execution.started_at
            execution.duration_ms = int(delta.total_seconds() * 1000)

    session.add(execution)
    await session.flush()

    logger.info(
        "execution_transition",
        execution_id=str(execution_id),
        new_status=new_status,
    )

    return execution


async def transition_step(
    session: AsyncSession,
    step_execution_id: uuid.UUID,
    new_status: str,
    error: str | None = None,
) -> StepExecution:
    """Transition a step execution to a new status in the database.

    Fetches the step execution, validates the transition, updates
    the status, and flushes to the database.

    Args:
        session: Async SQLAlchemy session.
        step_execution_id: UUID of the step execution to transition.
        new_status: Desired new status.
        error: Optional error message for failed transitions.

    Returns:
        The updated StepExecution instance.

    Raises:
        AppError: NOT_FOUND if step execution doesn't exist.
        AppError: INVALID_TRANSITION if the transition is not allowed.
    """
    stmt = select(StepExecution).where(StepExecution.id == step_execution_id)
    result = await session.execute(stmt)
    step_exec = result.scalar_one_or_none()

    if step_exec is None:
        raise AppError(
            code="NOT_FOUND",
            message="Step execution not found.",
            status_code=404,
        )

    validate_step_transition(step_exec.status, new_status)

    step_exec.status = new_status
    now = utc_now()

    if new_status == "running":
        step_exec.started_at = now
    elif new_status in ("completed", "failed"):
        step_exec.completed_at = now
        if step_exec.started_at:
            delta = now - step_exec.started_at
            step_exec.duration_ms = int(delta.total_seconds() * 1000)

    if error is not None:
        step_exec.error = error

    session.add(step_exec)
    await session.flush()

    logger.info(
        "step_transition",
        step_execution_id=str(step_execution_id),
        step_id=step_exec.step_id,
        new_status=new_status,
    )

    return step_exec
