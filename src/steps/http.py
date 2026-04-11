"""HTTP step executor for external API calls.

Makes async HTTP requests via httpx with Jinja2 templating in URL,
headers, and body. Captures response status, headers, body, and duration.
Raises retryable errors on 5xx/timeout; 4xx responses are captured.
"""

import time
from typing import Any

import httpx

from src.config import settings
from src.lib.expressions import evaluate_expression
from src.lib.logger import get_logger
from src.lib.utils import AppError
from src.steps.base import BaseStepExecutor

logger = get_logger(__name__)

MAX_RESPONSE_BODY_SIZE = settings.max_response_body_size
HTTP_STEP_TIMEOUT = settings.http_step_timeout


class HttpExecutor(BaseStepExecutor):
    """Step executor that makes async HTTP requests.

    Config: ``{ url, method, headers, body, timeout_seconds }``
    Output: ``{ status_code, headers, body, duration_ms }``

    Jinja2 templating is applied to url, header values, and body.
    5xx responses and timeouts raise retryable errors.
    4xx responses are captured normally (not retried).
    """

    async def execute(
        self, config: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute an HTTP request with the given config and context.

        Args:
            config: Step configuration with url, method, headers, body.
            context: Execution context for Jinja2 template evaluation.

        Returns:
            Dict with status_code, headers, body, duration_ms.

        Raises:
            AppError: STEP_CONFIG_ERROR if url is missing.
            AppError: HTTP_STEP_ERROR on 5xx or connection failure.
            AppError: HTTP_STEP_TIMEOUT on request timeout.
        """
        url_template = config.get("url")
        if not url_template:
            raise AppError(
                code="STEP_CONFIG_ERROR",
                message="HTTP step requires 'url' in config.",
                status_code=400,
            )

        method = config.get("method", "GET").upper()
        timeout_seconds = config.get("timeout_seconds", HTTP_STEP_TIMEOUT)

        # Evaluate Jinja2 templates
        url = evaluate_expression(url_template, context)
        headers = _render_headers(config.get("headers", {}), context)
        body = _render_body(config.get("body"), context)

        logger.info(
            "http_step_execute",
            method=method,
            url=url[:200],
        )

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    content=body.encode("utf-8") if body else None,
                )
        except httpx.TimeoutException as exc:
            raise AppError(
                code="HTTP_STEP_TIMEOUT",
                message=f"HTTP request timed out after {timeout_seconds}s: {exc}",
                status_code=504,
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                code="HTTP_STEP_ERROR",
                message=f"HTTP request failed: {exc}",
                status_code=502,
            ) from exc

        duration_ms = int((time.monotonic() - start) * 1000)

        # Capture response body with size limit
        response_body = response.text
        if len(response_body) > MAX_RESPONSE_BODY_SIZE:
            response_body = (
                response_body[:MAX_RESPONSE_BODY_SIZE]
                + "... [truncated]"
            )

        response_headers = dict(response.headers)

        # 5xx: raise retryable error
        if response.status_code >= 500:
            raise AppError(
                code="HTTP_STEP_ERROR",
                message=(
                    f"HTTP {method} {url} returned {response.status_code}: "
                    f"{response_body[:200]}"
                ),
                status_code=502,
                details=[{
                    "status_code": response.status_code,
                    "body": response_body[:500],
                }],
            )

        return {
            "status_code": response.status_code,
            "headers": response_headers,
            "body": response_body,
            "duration_ms": duration_ms,
        }


def _render_headers(
    headers: dict[str, str], context: dict[str, Any]
) -> dict[str, str]:
    """Evaluate Jinja2 templates in header values.

    Args:
        headers: Header name-value pairs (values may be templates).
        context: Execution context for template evaluation.

    Returns:
        Dict with evaluated header values.
    """
    if not headers:
        return {}
    return {
        key: evaluate_expression(value, context)
        for key, value in headers.items()
    }


def _render_body(body: str | None, context: dict[str, Any]) -> str | None:
    """Evaluate Jinja2 template in request body.

    Args:
        body: Request body string (may be a Jinja2 template).
        context: Execution context for template evaluation.

    Returns:
        Evaluated body string, or None if no body.
    """
    if not body:
        return None
    return evaluate_expression(body, context)
