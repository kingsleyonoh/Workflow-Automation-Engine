"""Global error handling middleware for FastAPI.

Catches AppError instances and unhandled exceptions, returning
the standard error response format: {"error": {"code", "message", "details"}}.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.lib.logger import get_logger
from src.lib.utils import AppError, create_error_response

logger = get_logger(__name__)


async def app_error_handler(
    request: Request,
    exc: AppError,
) -> JSONResponse:
    """Handle AppError and return standardized error JSON.

    Args:
        request: The incoming request that triggered the error.
        exc: The application error with code, message, and details.

    Returns:
        JSONResponse with the standard error format and appropriate status code.
    """
    logger.warning(
        "app_exception",
        code=exc.code,
        message=exc.message,
        status_code=exc.status_code,
        path=str(request.url),
        method=request.method,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
        ),
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Handle Starlette/FastAPI HTTPExceptions in the standard error format.

    Args:
        request: The incoming request that triggered the error.
        exc: The HTTP exception from Starlette/FastAPI.

    Returns:
        JSONResponse with the standard error format.
    """
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_ERROR",
    }
    error_code = code_map.get(exc.status_code, "HTTP_ERROR")

    logger.warning(
        "http_exception",
        code=error_code,
        status_code=exc.status_code,
        detail=str(exc.detail),
        path=str(request.url),
        method=request.method,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=create_error_response(
            code=error_code,
            message=str(exc.detail),
        ),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle unexpected exceptions with a generic 500 error.

    Logs the full traceback server-side but never leaks stack traces
    to the client.

    Args:
        request: The incoming request that triggered the error.
        exc: The unhandled exception.

    Returns:
        JSONResponse with a generic 500 error in the standard format.
    """
    logger.error(
        "unhandled_exception",
        exc_type=type(exc).__name__,
        exc_message=str(exc),
        path=str(request.url),
        method=request.method,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content=create_error_response(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
        ),
    )
