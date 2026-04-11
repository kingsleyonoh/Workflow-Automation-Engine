"""Cron scheduler service for scheduled workflow execution.

On app startup, loads all active cron workflows across all tenants,
parses their cron expressions, and schedules them with APScheduler.
On workflow update/delete, dynamically updates the scheduler.
"""

from datetime import UTC, datetime
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Workflow
from src.lib.logger import get_logger

logger = get_logger(__name__)

# Module-level scheduler instance
_scheduler: AsyncIOScheduler | None = None


async def load_cron_workflows(
    session: AsyncSession,
) -> list[Workflow]:
    """Load all active cron-triggered workflows from the database.

    Args:
        session: Async SQLAlchemy session.

    Returns:
        List of active cron Workflow instances, limited by
        MAX_CRON_WORKFLOWS setting.
    """
    stmt = (
        select(Workflow)
        .where(
            and_(
                Workflow.trigger_type == "cron",
                Workflow.is_active.is_(True),
            )
        )
        .limit(settings.max_cron_workflows)
    )
    result = await session.execute(stmt)
    workflows = list(result.scalars().all())

    logger.info(
        "cron_workflows_loaded",
        count=len(workflows),
        max_allowed=settings.max_cron_workflows,
    )

    return workflows


def parse_cron_expression(expression: str) -> dict[str, str]:
    """Parse a standard 5-field cron expression into components.

    Args:
        expression: Standard cron expression (minute hour day month day_of_week).

    Returns:
        Dict with keys: minute, hour, day, month, day_of_week.

    Raises:
        ValueError: If the expression is not a valid 5-field cron expression.
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(
            f"Invalid cron expression: {expression!r}. "
            "Expected 5 fields: minute hour day month day_of_week"
        )

    # Validate by attempting to create a CronTrigger
    try:
        CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid cron expression: {expression!r}. {exc}") from exc

    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def build_trigger_data() -> dict[str, Any]:
    """Build the trigger_data payload for a cron-triggered execution.

    Returns:
        Dict with triggered_by and scheduled_time fields.
    """
    return {
        "triggered_by": "cron",
        "scheduled_time": datetime.now(UTC).isoformat(),
    }


async def _execute_cron_workflow(workflow_id: str, tenant_id: str) -> None:
    """Execute a cron-triggered workflow.

    Called by APScheduler on each cron tick. Creates a new execution
    via the orchestrator.

    Args:
        workflow_id: UUID string of the workflow to execute.
        tenant_id: UUID string of the tenant owning the workflow.
    """
    import uuid

    from src.db.postgres import async_session_factory
    from src.engine.orchestrator import start_execution

    trigger_data = build_trigger_data()

    try:
        async with async_session_factory() as session:
            stmt = select(Workflow).where(Workflow.id == uuid.UUID(workflow_id))
            result = await session.execute(stmt)
            workflow = result.scalar_one_or_none()

            if workflow is None or not workflow.is_active:
                logger.warning(
                    "cron_workflow_not_found_or_inactive",
                    workflow_id=workflow_id,
                )
                return

            await start_execution(
                session=session,
                workflow=workflow,
                trigger_data=trigger_data,
                tenant_id=uuid.UUID(tenant_id),
            )
            await session.commit()

        logger.info(
            "cron_execution_triggered",
            workflow_id=workflow_id,
            tenant_id=tenant_id,
        )

    except Exception:
        logger.error(
            "cron_execution_error",
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            exc_info=True,
        )


def get_scheduler() -> AsyncIOScheduler | None:
    """Get the module-level scheduler instance.

    Returns:
        The scheduler, or None if not started.
    """
    return _scheduler


async def start_scheduler() -> AsyncIOScheduler:
    """Start the cron scheduler and load all cron workflows.

    Loads active cron workflows from the database, schedules each
    one with APScheduler, and starts the scheduler.

    Returns:
        The started AsyncIOScheduler instance.
    """
    global _scheduler

    from src.db.postgres import async_session_factory

    scheduler = AsyncIOScheduler(timezone=settings.cron_timezone)

    async with async_session_factory() as session:
        workflows = await load_cron_workflows(session)

    for wf in workflows:
        cron_expr = (wf.trigger_config or {}).get("cron_expression", "")
        if not cron_expr:
            logger.warning(
                "cron_workflow_missing_expression",
                workflow_id=str(wf.id),
            )
            continue

        try:
            fields = parse_cron_expression(cron_expr)
            trigger = CronTrigger(**fields, timezone=settings.cron_timezone)
            scheduler.add_job(
                _execute_cron_workflow,
                trigger=trigger,
                args=[str(wf.id), str(wf.tenant_id)],
                id=f"cron_{wf.id}",
                replace_existing=True,
            )
            logger.info(
                "cron_job_scheduled",
                workflow_id=str(wf.id),
                expression=cron_expr,
            )
        except ValueError:
            logger.warning(
                "cron_invalid_expression",
                workflow_id=str(wf.id),
                expression=cron_expr,
            )

    scheduler.start()
    _scheduler = scheduler

    logger.info(
        "cron_scheduler_started",
        jobs_count=len(scheduler.get_jobs()),
    )

    return scheduler


async def stop_scheduler() -> None:
    """Stop the cron scheduler if it is running."""
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("cron_scheduler_stopped")
        _scheduler = None


async def add_cron_job(workflow: Workflow) -> None:
    """Add or update a cron job for a workflow.

    Called when a cron workflow is created or updated.

    Args:
        workflow: The cron Workflow instance.
    """
    if _scheduler is None:
        return

    cron_expr = (workflow.trigger_config or {}).get("cron_expression", "")
    if not cron_expr:
        return

    try:
        fields = parse_cron_expression(cron_expr)
        trigger = CronTrigger(**fields, timezone=settings.cron_timezone)
        _scheduler.add_job(
            _execute_cron_workflow,
            trigger=trigger,
            args=[str(workflow.id), str(workflow.tenant_id)],
            id=f"cron_{workflow.id}",
            replace_existing=True,
        )
        logger.info(
            "cron_job_added",
            workflow_id=str(workflow.id),
            expression=cron_expr,
        )
    except ValueError:
        logger.warning(
            "cron_add_invalid_expression",
            workflow_id=str(workflow.id),
            expression=cron_expr,
        )


async def remove_cron_job(workflow_id: str) -> None:
    """Remove a cron job for a workflow.

    Called when a cron workflow is deleted or deactivated.

    Args:
        workflow_id: UUID string of the workflow.
    """
    if _scheduler is None:
        return

    job_id = f"cron_{workflow_id}"
    job = _scheduler.get_job(job_id)
    if job:
        _scheduler.remove_job(job_id)
        logger.info("cron_job_removed", workflow_id=workflow_id)
