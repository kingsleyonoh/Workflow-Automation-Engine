"""Manual trigger service for workflow execution.

Validates workflow ownership and active state, then delegates
to the orchestrator to start a new execution.
"""

import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Workflow
from src.lib.logger import get_logger
from src.lib.utils import AppError

logger = get_logger(__name__)


async def get_tenant_workflow(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Workflow:
    """Fetch a workflow scoped to the given tenant.

    Args:
        session: Async SQLAlchemy session.
        workflow_id: The workflow UUID.
        tenant_id: The tenant UUID for scoping.

    Returns:
        The matching Workflow instance.

    Raises:
        AppError: NOT_FOUND (404) if not found or belongs to another tenant.
    """
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
            message="Workflow not found.",
            status_code=404,
        )

    return workflow


def validate_workflow_active(workflow: Workflow) -> None:
    """Validate that a workflow is active for execution.

    Args:
        workflow: The workflow to validate.

    Raises:
        AppError: WORKFLOW_INACTIVE (400) if workflow is not active.
    """
    if not workflow.is_active:
        raise AppError(
            code="WORKFLOW_INACTIVE",
            message="Workflow is not active.",
            status_code=400,
        )
