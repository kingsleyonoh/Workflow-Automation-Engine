"""Step execution task definitions for arq worker.

Defines the execute_step arq task that looks up a step execution,
dispatches to the correct executor, and handles success/failure.
Also provides dispatch_step for enqueuing jobs.
"""

import uuid
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings

from src.config import settings
from src.engine.models import StepType
from src.lib.logger import get_logger
from src.lib.utils import AppError
from src.steps.base import BaseStepExecutor
from src.steps.condition import ConditionExecutor
from src.steps.delay import DelayExecutor
from src.steps.http import HttpExecutor
from src.steps.sub_workflow import SubWorkflowExecutor
from src.steps.transform import TransformExecutor

logger = get_logger(__name__)

STEP_REGISTRY: dict[StepType, type[BaseStepExecutor]] = {
    StepType.HTTP: HttpExecutor,
    StepType.TRANSFORM: TransformExecutor,
    StepType.CONDITION: ConditionExecutor,
    StepType.DELAY: DelayExecutor,
    StepType.SUB_WORKFLOW: SubWorkflowExecutor,
}


def _parse_redis_url(url: str) -> RedisSettings:
    """Parse a Redis URL into arq RedisSettings.

    Args:
        url: Redis connection URL (redis://host:port/db).

    Returns:
        arq RedisSettings instance.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


async def execute_step(
    ctx: dict[str, Any],
    step_execution_id: str,
    execution_id: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Execute a single workflow step as an arq task.

    Looks up the step execution record, determines the step type,
    creates the correct executor, and runs it. On success, merges
    output into the execution context. On failure, records the error.

    Args:
        ctx: arq worker context (contains db_session_factory, redis).
        step_execution_id: UUID of the step execution record.
        execution_id: UUID of the parent execution.
        tenant_id: UUID of the tenant.

    Returns:
        Step output dict on success.

    Raises:
        AppError: On step execution failure.
    """
    from sqlalchemy import select

    from src.db.models import Execution, StepExecution
    from src.engine.context import get_step_input, merge_step_output
    from src.engine.state import transition_step

    session_factory = ctx.get("db_session_factory")
    if session_factory is None:
        raise AppError(
            code="WORKER_ERROR",
            message="Database session factory not available in worker context.",
            status_code=500,
        )

    se_uuid = uuid.UUID(step_execution_id)
    ex_uuid = uuid.UUID(execution_id)

    async with session_factory() as session:
        # Look up step execution
        stmt = select(StepExecution).where(StepExecution.id == se_uuid)
        result = await session.execute(stmt)
        step_exec = result.scalar_one_or_none()

        if step_exec is None:
            raise AppError(
                code="NOT_FOUND",
                message=f"Step execution {step_execution_id} not found.",
                status_code=404,
            )

        # Look up execution for context
        ex_stmt = select(Execution).where(Execution.id == ex_uuid)
        ex_result = await session.execute(ex_stmt)
        execution = ex_result.scalar_one_or_none()

        if execution is None:
            raise AppError(
                code="NOT_FOUND",
                message=f"Execution {execution_id} not found.",
                status_code=404,
            )

        # Transition to running
        await transition_step(session, se_uuid, "running")

        # Determine executor
        step_type = StepType(step_exec.step_type)
        executor_class = STEP_REGISTRY.get(step_type)

        if executor_class is None:
            error_msg = f"Unsupported step type: {step_exec.step_type}"
            await transition_step(session, se_uuid, "failed", error=error_msg)
            await session.commit()
            raise AppError(
                code="UNSUPPORTED_STEP_TYPE",
                message=error_msg,
                status_code=400,
            )

        # Get context and execute
        context = execution.context or {}
        step_input = get_step_input(context, step_exec.step_id, {})
        executor = executor_class()

        try:
            output = await executor.execute(step_exec.input_data or {}, step_input)

            # Success: transition and merge output
            await transition_step(session, se_uuid, "completed")
            step_exec.output_data = output
            session.add(step_exec)
            await merge_step_output(session, ex_uuid, step_exec.step_id, output)
            await session.commit()

            logger.info(
                "step_completed",
                step_execution_id=step_execution_id,
                step_type=step_exec.step_type,
            )
            return output

        except (AppError, Exception) as exc:
            error_msg = str(exc)
            step_exec.attempt = (step_exec.attempt or 1) + 1
            session.add(step_exec)

            await transition_step(session, se_uuid, "failed", error=error_msg)
            await session.commit()

            logger.warning(
                "step_failed",
                step_execution_id=step_execution_id,
                error=error_msg,
            )
            raise


async def dispatch_step(
    redis: Any,
    step_execution_id: str,
    execution_id: str,
    tenant_id: str,
) -> None:
    """Enqueue a step execution job to the arq queue.

    Args:
        redis: Redis client instance (unused directly, but kept for
               interface consistency — arq creates its own pool).
        step_execution_id: UUID of the step execution to process.
        execution_id: UUID of the parent execution.
        tenant_id: UUID of the tenant.
    """
    redis_settings = _parse_redis_url(settings.redis_url)
    pool = await create_pool(redis_settings)

    try:
        job = await pool.enqueue_job(
            "execute_step",
            step_execution_id,
            execution_id,
            tenant_id,
        )
        logger.info(
            "step_dispatched",
            step_execution_id=step_execution_id,
            execution_id=execution_id,
            job_id=job.job_id if job else None,
        )
    finally:
        await pool.aclose()
