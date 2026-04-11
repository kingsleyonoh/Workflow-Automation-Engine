"""Background cleanup and pruning jobs for arq cron scheduler.

Provides three periodic jobs:
- cleanup_stale_executions: hourly, marks stuck 'running' executions as 'failed'
- prune_execution_logs: daily at 2am, deletes logs older than 30 days
- prune_webhook_deliveries: daily at 3am, deletes deliveries older than 7 days
"""

from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select, update

from src.db.models import Execution, ExecutionLog, StepExecution, WebhookDelivery
from src.lib.logger import get_logger
from src.lib.utils import utc_now

logger = get_logger(__name__)

STALE_THRESHOLD = timedelta(hours=1)
LOG_RETENTION = timedelta(days=30)
WEBHOOK_RETENTION = timedelta(days=7)
STALE_ERROR_MSG = "Execution timed out (stale)"
STALE_STEP_ERROR_MSG = "Parent execution timed out (stale)"


async def cleanup_stale_executions(ctx: dict[str, Any]) -> int:
    """Mark executions stuck in 'running' for >1h as 'failed'.

    Also marks their pending/running steps as 'failed'.
    Processes all tenants in a single pass.

    Args:
        ctx: arq worker context with db_session_factory.

    Returns:
        Number of stale executions cleaned up.
    """
    session_factory = ctx["db_session_factory"]
    cutoff = utc_now() - STALE_THRESHOLD
    now = utc_now()

    async with session_factory() as session:
        # Find stale executions
        stmt = select(Execution).where(
            Execution.status == "running",
            Execution.started_at < cutoff,
        )
        result = await session.execute(stmt)
        stale_executions = result.scalars().all()

        if not stale_executions:
            logger.info("stale_cleanup_complete", count=0)
            return 0

        stale_ids = [ex.id for ex in stale_executions]

        # Mark stale executions as failed
        await session.execute(
            update(Execution)
            .where(Execution.id.in_(stale_ids))
            .values(
                status="failed",
                error=STALE_ERROR_MSG,
                completed_at=now,
            )
        )

        # Mark pending/running steps of stale executions as failed
        await session.execute(
            update(StepExecution)
            .where(
                StepExecution.execution_id.in_(stale_ids),
                StepExecution.status.in_(["pending", "running", "queued"]),
            )
            .values(
                status="failed",
                error=STALE_STEP_ERROR_MSG,
                completed_at=now,
            )
        )

        await session.commit()

        logger.info("stale_cleanup_complete", count=len(stale_ids))
        return len(stale_ids)


async def prune_execution_logs(ctx: dict[str, Any]) -> int:
    """Delete execution logs older than 30 days.

    Processes all tenants in a single query.

    Args:
        ctx: arq worker context with db_session_factory.

    Returns:
        Number of deleted log rows.
    """
    session_factory = ctx["db_session_factory"]
    cutoff = utc_now() - LOG_RETENTION

    async with session_factory() as session:
        stmt = delete(ExecutionLog).where(ExecutionLog.created_at < cutoff)
        result = await session.execute(stmt)
        deleted = result.rowcount
        await session.commit()

        logger.info("log_pruning_complete", deleted_count=deleted)
        return deleted


async def prune_webhook_deliveries(ctx: dict[str, Any]) -> int:
    """Delete webhook deliveries older than 7 days.

    Processes all tenants in a single query.

    Args:
        ctx: arq worker context with db_session_factory.

    Returns:
        Number of deleted delivery rows.
    """
    session_factory = ctx["db_session_factory"]
    cutoff = utc_now() - WEBHOOK_RETENTION

    async with session_factory() as session:
        stmt = delete(WebhookDelivery).where(WebhookDelivery.created_at < cutoff)
        result = await session.execute(stmt)
        deleted = result.rowcount
        await session.commit()

        logger.info("webhook_pruning_complete", deleted_count=deleted)
        return deleted
