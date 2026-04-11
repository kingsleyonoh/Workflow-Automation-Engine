"""Webhook receiver API route.

POST /webhooks/:path — receive inbound webhook, match workflow,
validate HMAC signature, log delivery, trigger execution.
Returns 202 Accepted with execution_id.
"""

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.config import settings
from src.db.postgres import async_session_factory
from src.engine.orchestrator import start_execution
from src.lib.logger import get_logger
from src.lib.utils import AppError, create_error_response
from src.triggers.webhook import (
    log_webhook_delivery,
    lookup_workflow_by_path,
    validate_hmac_signature,
)

logger = get_logger(__name__)

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/{webhook_path}")
async def receive_webhook(
    webhook_path: str,
    request: Request,
) -> JSONResponse:
    """Receive an inbound webhook and trigger workflow execution.

    Looks up the workflow by webhook_path, validates HMAC if
    webhook_secret is set, logs the delivery, and starts a new
    execution asynchronously. Returns 202 Accepted.

    Args:
        webhook_path: The unique webhook path slug.
        request: The inbound HTTP request.

    Returns:
        202 with ``{ execution_id }`` on success.
    """
    # Check payload size
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > settings.max_payload_size:
        return JSONResponse(
            status_code=413,
            content=create_error_response(
                code="PAYLOAD_TOO_LARGE",
                message="Request payload exceeds maximum allowed size.",
            ),
        )

    # Read raw body for HMAC validation
    body = await request.body()

    if len(body) > settings.max_payload_size:
        return JSONResponse(
            status_code=413,
            content=create_error_response(
                code="PAYLOAD_TOO_LARGE",
                message="Request payload exceeds maximum allowed size.",
            ),
        )

    # Parse payload
    try:
        payload: dict[str, Any] = json.loads(body) if body else {}
    except (json.JSONDecodeError, ValueError):
        payload = {}

    source_ip = request.client.host if request.client else None
    request_headers = dict(request.headers)

    async with async_session_factory() as session:
        # Look up workflow by path
        try:
            workflow = await lookup_workflow_by_path(session, webhook_path)
        except AppError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=create_error_response(
                    code=exc.code,
                    message=exc.message,
                ),
            )

        # Check if workflow is active
        if not workflow.is_active:
            await log_webhook_delivery(
                session=session,
                tenant_id=workflow.tenant_id,
                workflow_id=workflow.id,
                method=request.method,
                headers=request_headers,
                payload=payload,
                source_ip=source_ip,
                status="rejected",
                rejection_reason="Workflow is not active.",
            )
            await session.commit()
            return JSONResponse(
                status_code=404,
                content=create_error_response(
                    code="NOT_FOUND",
                    message="Webhook path not found.",
                ),
            )

        # Validate HMAC if secret is set
        if workflow.webhook_secret:
            signature = request.headers.get("x-hub-signature-256")
            try:
                validate_hmac_signature(workflow.webhook_secret, body, signature)
            except AppError as exc:
                await log_webhook_delivery(
                    session=session,
                    tenant_id=workflow.tenant_id,
                    workflow_id=workflow.id,
                    method=request.method,
                    headers=request_headers,
                    payload=payload,
                    source_ip=source_ip,
                    status="rejected",
                    rejection_reason=exc.message,
                )
                await session.commit()
                return JSONResponse(
                    status_code=exc.status_code,
                    content=create_error_response(
                        code=exc.code,
                        message=exc.message,
                    ),
                )

        # Log delivery as received first (no execution_id yet)
        delivery = await log_webhook_delivery(
            session=session,
            tenant_id=workflow.tenant_id,
            workflow_id=workflow.id,
            method=request.method,
            headers=request_headers,
            payload=payload,
            source_ip=source_ip,
            status="received",
        )

        # Trigger execution
        trigger_data = {"payload": payload, "headers": request_headers}

        try:
            execution = await start_execution(
                session=session,
                workflow=workflow,
                trigger_data=trigger_data,
                tenant_id=workflow.tenant_id,
            )

            # Update delivery to accepted with execution_id
            delivery.status = "accepted"
            delivery.execution_id = execution.id
            session.add(delivery)
            await session.commit()

            logger.info(
                "webhook_execution_triggered",
                webhook_path=webhook_path,
                workflow_id=str(workflow.id),
                execution_id=str(execution.id),
            )

            return JSONResponse(
                status_code=202,
                content={"execution_id": str(execution.id)},
            )

        except Exception as exc:
            delivery.status = "error"
            delivery.rejection_reason = str(exc)
            session.add(delivery)
            await session.commit()

            logger.error(
                "webhook_execution_error",
                webhook_path=webhook_path,
                error=str(exc),
                exc_info=True,
            )
            raise
