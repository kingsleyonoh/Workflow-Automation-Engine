"""Shared execution context management for workflow runs.

Provides functions to merge step output into the execution's
shared JSONB context and to assemble step input from context.
Uses DB-level JSONB merge for thread safety.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Execution
from src.lib.logger import get_logger
from src.lib.utils import AppError

logger = get_logger(__name__)


async def merge_step_output(
    session: AsyncSession,
    execution_id: uuid.UUID,
    step_id: str,
    output_data: dict[str, Any],
) -> None:
    """Merge a step's output into the execution's shared context.

    Updates the execution.context JSONB field with the step output
    using DB-level concatenation for thread safety. The resulting
    context structure is:
    ``{ "steps": { "<step_id>": { "output": {...} } }, ... }``

    Args:
        session: Async SQLAlchemy session.
        execution_id: UUID of the execution to update.
        step_id: The step ID whose output is being merged.
        output_data: The step output dict to merge.

    Raises:
        AppError: NOT_FOUND if execution doesn't exist.
    """
    # First fetch the execution to verify it exists and get current context
    stmt = select(Execution).where(Execution.id == execution_id)
    result = await session.execute(stmt)
    execution = result.scalar_one_or_none()

    if execution is None:
        raise AppError(
            code="NOT_FOUND",
            message="Execution not found.",
            status_code=404,
        )

    # Build new context with merged step output
    ctx = dict(execution.context) if execution.context else {}
    steps = dict(ctx.get("steps", {}))
    steps[step_id] = {"output": output_data}
    ctx["steps"] = steps

    execution.context = ctx
    session.add(execution)
    await session.flush()

    logger.info(
        "context_merge",
        execution_id=str(execution_id),
        step_id=step_id,
    )


def get_step_input(
    context: dict[str, Any],
    step_id: str,
    step_config: dict[str, Any],
) -> dict[str, Any]:
    """Assemble step input from execution context.

    Returns a dict with ``steps``, ``trigger``, and other context
    data that the step executor can reference via Jinja2 expressions.

    Args:
        context: The execution's shared context dict.
        step_id: The step ID that will receive this input.
        step_config: The step's configuration dict.

    Returns:
        Dict containing steps outputs and trigger data for
        template evaluation.
    """
    return {
        "steps": context.get("steps", {}),
        "trigger": context.get("trigger", {}),
    }
