"""Execution replay service.

Loads the original execution's trigger data, optionally merges
override data, creates a new execution linked via replayed_from,
and delegates to the orchestrator.
"""

import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Execution, Workflow
from src.engine.orchestrator import start_execution
from src.lib.logger import get_logger
from src.lib.utils import AppError

logger = get_logger(__name__)


async def replay_execution(
    session: AsyncSession,
    execution_id: uuid.UUID,
    tenant_id: uuid.UUID,
    override_data: dict[str, Any] | None = None,
) -> Execution:
    """Replay a previous execution with optional data overrides.

    Loads the original execution's trigger_data, merges any
    override_data, and starts a new execution linked via
    replayed_from.

    Args:
        session: Async SQLAlchemy session.
        execution_id: UUID of the original execution to replay.
        tenant_id: UUID of the requesting tenant.
        override_data: Optional dict to merge into trigger_data.

    Returns:
        The new Execution instance.

    Raises:
        AppError: NOT_FOUND if execution doesn't exist or wrong tenant.
        AppError: WORKFLOW_INACTIVE if the workflow is not active.
    """
    # Load original execution (tenant-scoped)
    stmt = select(Execution).where(
        and_(
            Execution.id == execution_id,
            Execution.tenant_id == tenant_id,
        )
    )
    result = await session.execute(stmt)
    original = result.scalar_one_or_none()

    if original is None:
        raise AppError(
            code="NOT_FOUND",
            message="Execution not found.",
            status_code=404,
        )

    # Load the workflow
    wf_stmt = select(Workflow).where(
        and_(
            Workflow.id == original.workflow_id,
            Workflow.tenant_id == tenant_id,
        )
    )
    wf_result = await session.execute(wf_stmt)
    workflow = wf_result.scalar_one_or_none()

    if workflow is None:
        raise AppError(
            code="NOT_FOUND",
            message="Workflow not found.",
            status_code=404,
        )

    if not workflow.is_active:
        raise AppError(
            code="WORKFLOW_INACTIVE",
            message="Workflow is not active.",
            status_code=400,
        )

    # Merge trigger data with overrides
    trigger_data = dict(original.trigger_data) if original.trigger_data else {}
    if override_data:
        data_section = dict(trigger_data.get("data", {}))
        data_section.update(override_data)
        trigger_data["data"] = data_section

    logger.info(
        "replay_execution",
        original_id=str(execution_id),
        tenant_id=str(tenant_id),
        has_overrides=bool(override_data),
    )

    # Start new execution linked to original
    new_execution = await start_execution(
        session=session,
        workflow=workflow,
        trigger_data=trigger_data,
        tenant_id=tenant_id,
        replayed_from=execution_id,
    )

    return new_execution
