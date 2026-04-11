"""Execution API routes.

POST /api/workflows/:id/execute — manual execution trigger
GET /api/executions — list executions (tenant-scoped, paginated)
GET /api/executions/:id — get execution with step details
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from src.api.execution_models import (
    ExecutionDetailResponse,
    ExecutionListResponse,
    ManualExecuteRequest,
    decode_execution_cursor,
    encode_execution_cursor,
    execution_to_response,
    step_execution_to_response,
)
from src.db.models import Execution
from src.db.postgres import async_session_factory
from src.engine.orchestrator import start_execution
from src.lib.logger import get_logger
from src.lib.utils import AppError
from src.triggers.manual import get_tenant_workflow, validate_workflow_active

logger = get_logger(__name__)

router = APIRouter(tags=["executions"])


@router.post("/api/workflows/{workflow_id}/execute", status_code=202)
async def manual_execute(
    workflow_id: uuid.UUID,
    body: ManualExecuteRequest,
    request: Request,
) -> JSONResponse:
    """Manually trigger a workflow execution.

    Validates the workflow belongs to the tenant, is active,
    then starts a new execution with the provided trigger_data.

    Args:
        workflow_id: The workflow UUID to execute.
        body: Request body with optional trigger_data.
        request: HTTP request with tenant context.

    Returns:
        202 with ``{ execution_id }``.
    """
    tenant = request.state.tenant

    async with async_session_factory() as session:
        workflow = await get_tenant_workflow(session, workflow_id, tenant.id)
        validate_workflow_active(workflow)

        trigger_data = {
            "source": "manual",
            "data": body.trigger_data,
        }

        execution = await start_execution(
            session=session,
            workflow=workflow,
            trigger_data=trigger_data,
            tenant_id=tenant.id,
        )
        await session.commit()

    logger.info(
        "manual_execution_triggered",
        workflow_id=str(workflow_id),
        execution_id=str(execution.id),
        tenant_id=str(tenant.id),
    )

    return JSONResponse(
        status_code=202,
        content={"execution_id": str(execution.id)},
    )


@router.get("/api/executions", response_model=ExecutionListResponse)
async def list_executions(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    status: str | None = Query(default=None),
    workflow_id: uuid.UUID | None = Query(default=None),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
) -> ExecutionListResponse:
    """List executions for the authenticated tenant.

    Supports cursor-based pagination and filtering by status,
    workflow_id, created_after, and created_before.

    Args:
        request: HTTP request with tenant context.
        cursor: Pagination cursor from previous response.
        limit: Maximum number of executions to return.
        status: Filter by execution status.
        workflow_id: Filter by workflow ID.
        created_after: Filter by minimum created_at.
        created_before: Filter by maximum created_at.

    Returns:
        Paginated list of executions with optional next cursor.
    """
    tenant = request.state.tenant

    stmt = (
        select(Execution)
        .where(Execution.tenant_id == tenant.id)
        .order_by(Execution.created_at.asc(), Execution.id.asc())
    )

    if status is not None:
        stmt = stmt.where(Execution.status == status)

    if workflow_id is not None:
        stmt = stmt.where(Execution.workflow_id == workflow_id)

    if created_after is not None:
        stmt = stmt.where(Execution.created_at >= created_after)

    if created_before is not None:
        stmt = stmt.where(Execution.created_at <= created_before)

    if cursor:
        cursor_created_at, cursor_id = decode_execution_cursor(cursor)
        stmt = stmt.where(
            and_(
                Execution.created_at >= cursor_created_at,
                ~and_(
                    Execution.created_at == cursor_created_at,
                    Execution.id <= cursor_id,
                ),
            )
        )

    stmt = stmt.limit(limit + 1)

    async with async_session_factory() as session:
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    has_more = len(rows) > limit
    executions = rows[:limit]

    next_cursor = None
    if has_more and executions:
        last = executions[-1]
        next_cursor = encode_execution_cursor(last.created_at, last.id)

    return ExecutionListResponse(
        executions=[execution_to_response(ex) for ex in executions],
        cursor=next_cursor,
    )


@router.get("/api/executions/{execution_id}")
async def get_execution(
    execution_id: uuid.UUID,
    request: Request,
) -> ExecutionDetailResponse:
    """Get a single execution with step details, scoped to tenant.

    Args:
        execution_id: The execution UUID.
        request: HTTP request with tenant context.

    Returns:
        Execution detail with associated step executions.

    Raises:
        AppError: NOT_FOUND (404).
    """
    tenant = request.state.tenant

    async with async_session_factory() as session:
        stmt = (
            select(Execution)
            .where(
                and_(
                    Execution.id == execution_id,
                    Execution.tenant_id == tenant.id,
                )
            )
            .options(selectinload(Execution.step_executions))
        )
        result = await session.execute(stmt)
        execution = result.scalar_one_or_none()

    if execution is None:
        raise AppError(
            code="NOT_FOUND",
            message="Execution not found.",
            status_code=404,
        )

    return ExecutionDetailResponse(
        execution=execution_to_response(execution),
        steps=[step_execution_to_response(se) for se in execution.step_executions],
    )
