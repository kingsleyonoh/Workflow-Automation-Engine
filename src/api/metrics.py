"""Execution analytics API routes.

GET /api/metrics/executions — aggregate execution statistics
including counts by status, average duration, per-workflow breakdown,
step failure rates, and webhook delivery stats.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import case, func, select

from src.db.models import Execution, StepExecution, WebhookDelivery, Workflow
from src.db.postgres import async_session_factory
from src.lib.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["metrics"])


@router.get("/api/metrics/executions")
async def get_execution_metrics(request: Request) -> dict[str, Any]:
    """Get execution analytics for the authenticated tenant.

    Returns aggregate metrics: total count, by-status breakdown,
    average duration, per-workflow stats, step failure rates,
    and webhook delivery statistics.

    Args:
        request: HTTP request with tenant context.

    Returns:
        Metrics response with total, by_status, avg_duration_ms,
        by_workflow, step_failure_rates, webhook_delivery_stats.
    """
    tenant = request.state.tenant
    tenant_id: uuid.UUID = tenant.id

    async with async_session_factory() as session:
        # Total + by_status + avg_duration
        status_stmt = (
            select(
                Execution.status,
                func.count().label("cnt"),
            )
            .where(Execution.tenant_id == tenant_id)
            .group_by(Execution.status)
        )
        status_result = await session.execute(status_stmt)
        status_rows = status_result.all()

        total = sum(row.cnt for row in status_rows)
        by_status = {row.status: row.cnt for row in status_rows}

        # Average duration
        avg_stmt = select(
            func.avg(Execution.duration_ms).label("avg_ms"),
        ).where(
            Execution.tenant_id == tenant_id,
            Execution.duration_ms.isnot(None),
        )
        avg_result = await session.execute(avg_stmt)
        avg_row = avg_result.one()
        avg_duration = int(avg_row.avg_ms) if avg_row.avg_ms else 0

        # Per-workflow breakdown
        wf_stmt = (
            select(
                Execution.workflow_id,
                Workflow.name.label("workflow_name"),
                func.count().label("cnt"),
                func.avg(Execution.duration_ms).label("avg_ms"),
            )
            .join(Workflow, Execution.workflow_id == Workflow.id)
            .where(Execution.tenant_id == tenant_id)
            .group_by(Execution.workflow_id, Workflow.name)
        )
        wf_result = await session.execute(wf_stmt)
        by_workflow = [
            {
                "workflow_id": str(row.workflow_id),
                "workflow_name": row.workflow_name,
                "count": row.cnt,
                "avg_duration_ms": int(row.avg_ms) if row.avg_ms else 0,
            }
            for row in wf_result.all()
        ]

        # Step failure rates by type
        step_stmt = (
            select(
                StepExecution.step_type,
                func.count().label("total"),
                func.count(
                    case(
                        (StepExecution.status == "failed", 1),
                    )
                ).label("failed"),
            )
            .where(StepExecution.tenant_id == tenant_id)
            .group_by(StepExecution.step_type)
        )
        step_result = await session.execute(step_stmt)
        step_failure_rates = [
            {
                "step_type": row.step_type,
                "total": row.total,
                "failed": row.failed,
                "rate": round(row.failed / row.total, 3) if row.total else 0,
            }
            for row in step_result.all()
        ]

        # Webhook delivery stats
        wh_stmt = (
            select(
                WebhookDelivery.status,
                func.count().label("cnt"),
            )
            .where(WebhookDelivery.tenant_id == tenant_id)
            .group_by(WebhookDelivery.status)
        )
        wh_result = await session.execute(wh_stmt)
        wh_rows = wh_result.all()

        wh_total = sum(row.cnt for row in wh_rows)
        wh_by_status = {row.status: row.cnt for row in wh_rows}

        webhook_stats = {
            "total": wh_total,
            "accepted": wh_by_status.get("accepted", 0),
            "rejected": wh_by_status.get("rejected", 0),
            "error": wh_by_status.get("error", 0),
        }

    return {
        "total": total,
        "by_status": by_status,
        "avg_duration_ms": avg_duration,
        "by_workflow": by_workflow,
        "step_failure_rates": step_failure_rates,
        "webhook_delivery_stats": webhook_stats,
    }
