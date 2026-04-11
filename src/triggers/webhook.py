"""Webhook trigger service for inbound webhook processing.

Validates HMAC-SHA256 signatures, logs deliveries in webhook_deliveries
table, and triggers new workflow executions from webhook payloads.
"""

import hashlib
import hmac
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import WebhookDelivery, Workflow
from src.lib.logger import get_logger
from src.lib.utils import AppError

logger = get_logger(__name__)


async def lookup_workflow_by_path(
    session: AsyncSession,
    webhook_path: str,
) -> Workflow:
    """Look up a workflow by its webhook_path.

    Args:
        session: Async SQLAlchemy session.
        webhook_path: The unique webhook path slug.

    Returns:
        The matching Workflow instance.

    Raises:
        AppError: NOT_FOUND (404) if no workflow matches.
    """
    stmt = select(Workflow).where(Workflow.webhook_path == webhook_path)
    result = await session.execute(stmt)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise AppError(
            code="NOT_FOUND",
            message="Webhook path not found.",
            status_code=404,
        )

    return workflow


def validate_hmac_signature(
    secret: str,
    body: bytes,
    signature_header: str | None,
) -> None:
    """Validate HMAC-SHA256 signature from X-Hub-Signature-256 header.

    Args:
        secret: The webhook secret for HMAC computation.
        body: The raw request body bytes.
        signature_header: The X-Hub-Signature-256 header value.

    Raises:
        AppError: INVALID_SIGNATURE (401) if signature is missing or invalid.
    """
    if not signature_header:
        raise AppError(
            code="INVALID_SIGNATURE",
            message="Missing X-Hub-Signature-256 header.",
            status_code=401,
        )

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    expected_sig = f"sha256={expected}"

    if not hmac.compare_digest(signature_header, expected_sig):
        raise AppError(
            code="INVALID_SIGNATURE",
            message="Invalid webhook signature.",
            status_code=401,
        )


async def log_webhook_delivery(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    method: str,
    headers: dict[str, Any],
    payload: dict[str, Any],
    source_ip: str | None,
    status: str,
    execution_id: uuid.UUID | None = None,
    rejection_reason: str | None = None,
) -> WebhookDelivery:
    """Log a webhook delivery in the webhook_deliveries table.

    Args:
        session: Async SQLAlchemy session.
        tenant_id: Tenant UUID from the matched workflow.
        workflow_id: Matched workflow UUID.
        method: HTTP method of the request.
        headers: Request headers as dict.
        payload: Request payload as dict.
        source_ip: Client IP address.
        status: Delivery status (received/accepted/rejected/error).
        execution_id: UUID of the execution created, if any.
        rejection_reason: Reason for rejection, if applicable.

    Returns:
        The created WebhookDelivery instance.
    """
    delivery = WebhookDelivery(
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        execution_id=execution_id,
        method=method,
        headers=headers,
        payload=payload,
        source_ip=source_ip,
        status=status,
        rejection_reason=rejection_reason,
    )
    session.add(delivery)
    await session.flush()

    logger.info(
        "webhook_delivery_logged",
        delivery_id=str(delivery.id),
        workflow_id=str(workflow_id),
        status=status,
    )

    return delivery
