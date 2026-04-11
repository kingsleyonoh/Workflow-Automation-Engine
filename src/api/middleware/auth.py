"""API key validation middleware for FastAPI.

Extracts the X-API-Key header, validates it via the tenant service,
and injects TenantContext into request.state.tenant. Public paths
(health, docs, webhooks, registration) are exempt.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.db.postgres import async_session_factory
from src.lib.logger import get_logger
from src.lib.utils import AppError, create_error_response
from src.tenants.service import validate_api_key

logger = get_logger(__name__)

# Paths that do not require authentication
PUBLIC_PATH_PREFIXES = (
    "/api/health",
    "/webhooks/",
    "/api/tenants/register",
    "/docs",
    "/openapi.json",
    "/redoc",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that validates API keys and injects tenant context.

    For every non-public request, extracts the X-API-Key header,
    validates it against the tenant database, and sets
    request.state.tenant to the authenticated TenantContext.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process the request through auth validation.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The response from the downstream handler, or a 401/403 error.
        """
        path = request.url.path

        if self._is_public_path(path):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key", "")

        if not api_key:
            return JSONResponse(
                status_code=401,
                content=create_error_response(
                    code="INVALID_API_KEY",
                    message="Missing X-API-Key header.",
                ),
            )

        try:
            async with async_session_factory() as session:
                tenant_ctx = await validate_api_key(api_key=api_key, session=session)
            request.state.tenant = tenant_ctx
        except AppError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content=create_error_response(
                    code=exc.code,
                    message=exc.message,
                    details=exc.details,
                ),
            )
        except Exception:
            logger.error("auth_middleware_error", exc_info=True, path=path)
            return JSONResponse(
                status_code=500,
                content=create_error_response(
                    code="INTERNAL_ERROR",
                    message="An unexpected error occurred.",
                ),
            )

        return await call_next(request)

    @staticmethod
    def _is_public_path(path: str) -> bool:
        """Check if the request path is exempt from authentication.

        Args:
            path: The URL path to check.

        Returns:
            True if the path is public and does not require auth.
        """
        return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)
