"""Workflow CRUD API routes.

POST /api/workflows — create workflow
GET /api/workflows — list workflows (tenant-scoped, paginated)
GET /api/workflows/:id — get single workflow
PUT /api/workflows/:id — update workflow
DELETE /api/workflows/:id — delete workflow
"""

import uuid

from fastapi import APIRouter, Query, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.workflow_models import (
    WorkflowCreateRequest,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowUpdateRequest,
    decode_cursor,
    encode_cursor,
    generate_webhook_path,
    workflow_to_response,
)
from src.db.models import Workflow
from src.db.postgres import async_session_factory
from src.engine.parser import parse_workflow_definition
from src.lib.cache import workflow_cache
from src.lib.logger import get_logger
from src.lib.utils import AppError

logger = get_logger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    body: WorkflowCreateRequest,
    request: Request,
) -> WorkflowResponse:
    """Create a new workflow definition.

    Validates the workflow steps via the parser, auto-generates a
    webhook_path for webhook triggers, and stores in the database.

    Args:
        body: Workflow creation request body.
        request: HTTP request with tenant context.

    Returns:
        The created workflow with generated ID and timestamps.
    """
    tenant = request.state.tenant

    parse_workflow_definition(
        {
            "name": body.name,
            "trigger_type": body.trigger_type,
            "steps": body.steps,
        }
    )

    webhook_path = generate_webhook_path() if body.trigger_type == "webhook" else None

    workflow = Workflow(
        tenant_id=tenant.id,
        name=body.name,
        description=body.description,
        trigger_type=body.trigger_type,
        trigger_config=body.trigger_config,
        steps=body.steps,
        is_active=body.is_active,
        webhook_path=webhook_path,
        webhook_secret=body.webhook_secret,
    )

    async with async_session_factory() as session:
        session.add(workflow)
        await session.commit()
        await session.refresh(workflow)

    logger.info(
        "workflow_created",
        workflow_id=str(workflow.id),
        tenant_id=str(tenant.id),
        name=body.name,
        trigger_type=body.trigger_type,
    )

    return workflow_to_response(workflow)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    trigger_type: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
) -> WorkflowListResponse:
    """List workflows for the authenticated tenant.

    Supports cursor-based pagination and filtering by trigger_type
    and is_active.

    Args:
        request: HTTP request with tenant context.
        cursor: Pagination cursor from previous response.
        limit: Maximum number of workflows to return.
        trigger_type: Filter by trigger type.
        is_active: Filter by active status.

    Returns:
        Paginated list of workflows with optional next cursor.
    """
    tenant = request.state.tenant

    stmt = (
        select(Workflow)
        .where(Workflow.tenant_id == tenant.id)
        .order_by(Workflow.created_at.asc(), Workflow.id.asc())
    )

    if trigger_type is not None:
        stmt = stmt.where(Workflow.trigger_type == trigger_type)

    if is_active is not None:
        stmt = stmt.where(Workflow.is_active == is_active)

    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        stmt = stmt.where(
            and_(
                Workflow.created_at >= cursor_created_at,
                ~and_(
                    Workflow.created_at == cursor_created_at,
                    Workflow.id <= cursor_id,
                ),
            )
        )

    stmt = stmt.limit(limit + 1)

    async with async_session_factory() as session:
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

    has_more = len(rows) > limit
    workflows = rows[:limit]

    next_cursor = None
    if has_more and workflows:
        last = workflows[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    return WorkflowListResponse(
        workflows=[workflow_to_response(w) for w in workflows],
        cursor=next_cursor,
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID,
    request: Request,
) -> WorkflowResponse:
    """Get a single workflow by ID, scoped to authenticated tenant.

    Args:
        workflow_id: The workflow UUID.
        request: HTTP request with tenant context.

    Returns:
        The workflow if found and owned by the tenant.

    Raises:
        AppError: NOT_FOUND (404).
    """
    tenant = request.state.tenant

    async with async_session_factory() as session:
        workflow = await _get_tenant_workflow(session, workflow_id, tenant.id)

    return workflow_to_response(workflow)


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdateRequest,
    request: Request,
) -> WorkflowResponse:
    """Update an existing workflow, scoped to authenticated tenant.

    If steps are changed, re-validates them with the parser.
    If trigger_type changed to webhook, auto-generates webhook_path.

    Args:
        workflow_id: The workflow UUID.
        body: Partial update request body.
        request: HTTP request with tenant context.

    Returns:
        The updated workflow.

    Raises:
        AppError: NOT_FOUND (404).
    """
    tenant = request.state.tenant

    async with async_session_factory() as session:
        workflow = await _get_tenant_workflow(session, workflow_id, tenant.id)

        if body.name is not None:
            workflow.name = body.name

        if body.description is not None:
            workflow.description = body.description

        if body.trigger_config is not None:
            workflow.trigger_config = body.trigger_config

        if body.is_active is not None:
            workflow.is_active = body.is_active

        if body.steps is not None:
            parse_workflow_definition(
                {
                    "name": workflow.name,
                    "trigger_type": (body.trigger_type or workflow.trigger_type),
                    "steps": body.steps,
                }
            )
            workflow.steps = body.steps

        if body.webhook_secret is not None:
            workflow.webhook_secret = body.webhook_secret

        if body.trigger_type is not None:
            workflow.trigger_type = body.trigger_type
            if body.trigger_type == "webhook" and not workflow.webhook_path:
                workflow.webhook_path = generate_webhook_path()
            elif body.trigger_type != "webhook":
                workflow.webhook_path = None

        session.add(workflow)
        await session.commit()
        await session.refresh(workflow)

    workflow_cache.invalidate(workflow.id)

    logger.info(
        "workflow_updated",
        workflow_id=str(workflow.id),
        tenant_id=str(tenant.id),
    )

    return workflow_to_response(workflow)


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: uuid.UUID,
    request: Request,
) -> dict:
    """Delete a workflow by ID, scoped to authenticated tenant.

    CASCADE deletes related executions, step_executions, etc.
    as configured via FK ON DELETE CASCADE in the database schema.

    Args:
        workflow_id: The workflow UUID.
        request: HTTP request with tenant context.

    Returns:
        ``{"deleted": True}`` on success.

    Raises:
        AppError: NOT_FOUND (404) if not found or wrong tenant.
    """
    tenant = request.state.tenant

    async with async_session_factory() as session:
        workflow = await _get_tenant_workflow(session, workflow_id, tenant.id)
        await session.delete(workflow)
        await session.commit()

    workflow_cache.invalidate(workflow_id)

    logger.info(
        "workflow_deleted",
        workflow_id=str(workflow_id),
        tenant_id=str(tenant.id),
    )

    return {"deleted": True}


async def _get_tenant_workflow(
    session: AsyncSession,
    workflow_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Workflow:
    """Fetch a workflow scoped to the given tenant.

    Raises:
        AppError: NOT_FOUND if the workflow doesn't exist or belongs
                  to a different tenant.
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
