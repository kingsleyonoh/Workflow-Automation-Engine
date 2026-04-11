"""Execution logging service for structured per-step logs.

Provides a simple async function to record structured log entries
into the execution_logs table. Called by step executors and the
orchestrator to track execution events.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ExecutionLog
from src.lib.logger import get_logger

logger = get_logger(__name__)

VALID_LEVELS = {"info", "warn", "error", "debug"}


async def record_execution_log(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    execution_id: uuid.UUID,
    level: str,
    message: str,
    step_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> ExecutionLog:
    """Record a structured log entry for an execution.

    Args:
        session: Async SQLAlchemy session.
        tenant_id: The tenant UUID (multi-tenant scoping).
        execution_id: The execution UUID this log belongs to.
        level: Log level (info, warn, error, debug).
        message: Human-readable log message.
        step_id: Optional step ID if log is step-specific.
        data: Optional JSONB data payload.

    Returns:
        The created ExecutionLog instance.

    Raises:
        ValueError: If level is not one of info, warn, error, debug.
    """
    if level not in VALID_LEVELS:
        raise ValueError(f"Invalid log level: {level!r}. Must be one of {VALID_LEVELS}")

    log_entry = ExecutionLog(
        tenant_id=tenant_id,
        execution_id=execution_id,
        step_id=step_id,
        level=level,
        message=message,
        data=data or {},
    )
    session.add(log_entry)
    await session.flush()

    logger.debug(
        "execution_log_recorded",
        execution_id=str(execution_id),
        step_id=step_id,
        level=level,
    )

    return log_entry
