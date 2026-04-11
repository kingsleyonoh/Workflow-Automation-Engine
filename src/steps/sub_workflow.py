"""Sub-workflow step executor for nested workflow execution.

Triggers another workflow within the SAME tenant and waits for
completion. Enforces MAX_SUB_WORKFLOW_DEPTH to prevent infinite
recursion. Sub-workflows CANNOT cross tenant boundaries.
"""

import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import Workflow
from src.lib.expressions import evaluate_expression
from src.lib.logger import get_logger
from src.lib.utils import AppError
from src.steps.base import BaseStepExecutor

logger = get_logger(__name__)


class SubWorkflowExecutor(BaseStepExecutor):
    """Step executor that triggers a nested workflow execution.

    Config: ``{ workflow_id, input_mapping }``
    Output: ``{ status, context }``

    The sub-workflow runs within the same tenant. Nesting depth
    is tracked via the _depth context variable.
    """

    async def execute(
        self, config: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a sub-workflow step.

        Args:
            config: Must contain ``workflow_id``. Optional
                    ``input_mapping`` dict for trigger data.
            context: Execution context with _depth, _tenant_id,
                     _session for DB access.

        Returns:
            Dict with ``status`` and ``context`` from sub-workflow.

        Raises:
            AppError: STEP_CONFIG_ERROR if workflow_id missing.
            AppError: MAX_DEPTH_EXCEEDED if nesting too deep.
            AppError: NOT_FOUND if workflow not found in tenant.
            AppError: WORKFLOW_INACTIVE if workflow is inactive.
        """
        if "workflow_id" not in config:
            raise AppError(
                code="STEP_CONFIG_ERROR",
                message="Sub_workflow step requires 'workflow_id' in config.",
                status_code=400,
            )

        # Check depth limit
        current_depth = context.get("_depth", 0)
        max_depth = settings.max_sub_workflow_depth

        if current_depth >= max_depth:
            raise AppError(
                code="MAX_DEPTH_EXCEEDED",
                message=(
                    f"Sub-workflow depth {current_depth + 1} exceeds "
                    f"maximum of {max_depth}."
                ),
                status_code=400,
            )

        workflow_id = uuid.UUID(config["workflow_id"])
        tenant_id = uuid.UUID(context["_tenant_id"])
        session: AsyncSession = context["_session"]

        # Load workflow (tenant-scoped)
        stmt = select(Workflow).where(
            and_(
                Workflow.id == workflow_id,
                Workflow.tenant_id == tenant_id,
            )
        )
        result = await session.execute(stmt)
        workflow = result.scalar_one_or_none()

        if workflow is None:
            raise AppError(
                code="NOT_FOUND",
                message=f"Sub-workflow {workflow_id} not found.",
                status_code=404,
            )

        if not workflow.is_active:
            raise AppError(
                code="WORKFLOW_INACTIVE",
                message="Sub-workflow is not active.",
                status_code=400,
            )

        # Build trigger data from input_mapping
        trigger_data = _build_trigger_data(config, context)

        logger.info(
            "sub_workflow_execute",
            workflow_id=str(workflow_id),
            depth=current_depth + 1,
        )

        # Import here to avoid circular import at module load
        from src.engine.orchestrator import start_execution

        execution = await start_execution(
            session=session,
            workflow=workflow,
            trigger_data=trigger_data,
            tenant_id=tenant_id,
            depth=current_depth + 1,
        )

        return {
            "status": execution.status,
            "context": execution.context or {},
        }


def _build_trigger_data(
    config: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Build trigger data for the sub-workflow from input_mapping.

    Args:
        config: Step config with optional input_mapping.
        context: Parent execution context for expression evaluation.

    Returns:
        Trigger data dict for the sub-workflow.
    """
    input_mapping = config.get("input_mapping", {})

    if not input_mapping:
        return {"source": "sub_workflow", "data": {}}

    # Evaluate each mapping expression
    eval_context = {
        "steps": context.get("steps", {}),
        "trigger": context.get("trigger", {}),
    }
    mapped_data: dict[str, Any] = {}
    for key, expression in input_mapping.items():
        if isinstance(expression, str) and "{{" in expression:
            mapped_data[key] = evaluate_expression(expression, eval_context)
        else:
            mapped_data[key] = expression

    return {"source": "sub_workflow", "data": mapped_data}
