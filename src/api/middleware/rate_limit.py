"""Redis-based rate limiting middleware for FastAPI.

Uses a sliding window counter with Redis INCR + EXPIRE to enforce
per-route request limits. Injects X-RateLimit-* headers on all responses
and returns 429 Too Many Requests when the limit is exceeded.
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.db.redis import get_redis
from src.lib.logger import get_logger
from src.lib.utils import create_error_response

logger = get_logger(__name__)

# Per-route rate limit configuration: (method, path_prefix) -> requests per minute
# More specific prefixes are checked first via ordered matching.
ROUTE_LIMITS: list[tuple[str, str, int]] = [
    ("POST", "/api/tenants/register", 5),
    ("POST", "/api/workflows", 20),
    ("PUT", "/api/workflows/", 20),
    ("DELETE", "/api/workflows/", 20),
    ("POST", "/api/executions/", 20),
    ("POST", "/api/workflows/", 30),
    ("GET", "/api/executions/", 100),
    ("GET", "/api/metrics/", 30),
    ("GET", "/api/", 100),
    ("POST", "/api/", 100),
    ("POST", "/webhooks/", 100),
]

# Note: SSE stream endpoint rate limit is 30/min (matched by GET /api/executions/),
# Cancel endpoint rate limit is 20/min (matched by POST /api/executions/),
# Logs endpoint rate limit is 100/min (matched by GET /api/executions/).

DEFAULT_LIMIT = 100
WINDOW_SECONDS = 60


def _get_rate_limit(method: str, path: str) -> int:
    """Determine the rate limit for a given request method and path.

    Args:
        method: HTTP method (GET, POST, etc.).
        path: Request URL path.

    Returns:
        Maximum requests per minute for this route.
    """
    for route_method, route_prefix, limit in ROUTE_LIMITS:
        if method == route_method and path.startswith(route_prefix):
            return limit
    return DEFAULT_LIMIT


def _get_client_key(request: Request) -> str:
    """Extract a client identifier from the request for rate limiting.

    Uses the client IP address. Falls back to 'unknown' if unavailable.

    Args:
        request: The incoming HTTP request.

    Returns:
        A string identifying the client.
    """
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces per-route rate limits using Redis.

    Tracks request counts in Redis with sliding window counters.
    Adds X-RateLimit-Limit, X-RateLimit-Remaining, and X-RateLimit-Reset
    headers to all responses. Returns 429 when limit is exceeded.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Check rate limit and add headers to response.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            Response with rate limit headers, or 429 if exceeded.
        """
        path = request.url.path
        method = request.method

        limit = _get_rate_limit(method, path)
        client_key = _get_client_key(request)
        redis_key = f"ratelimit:{client_key}:{method}:{path}"

        now = int(time.time())
        window_reset = now + WINDOW_SECONDS

        try:
            redis = get_redis()
            current = await redis.incr(redis_key)

            if current == 1:
                await redis.expire(redis_key, WINDOW_SECONDS)

            ttl = await redis.ttl(redis_key)
            if ttl < 0:
                ttl = WINDOW_SECONDS
            reset_at = now + ttl
            remaining = max(0, limit - current)

        except Exception:
            logger.warning(
                "rate_limit_redis_error",
                path=path,
                client=client_key,
                exc_info=True,
            )
            # Fail open: allow request if Redis is down
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(limit)
            response.headers["X-RateLimit-Reset"] = str(window_reset)
            return response

        if current > limit:
            return JSONResponse(
                status_code=429,
                content=create_error_response(
                    code="RATE_LIMIT_EXCEEDED",
                    message="Too many requests. Please try again later.",
                ),
                headers={
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                    "Retry-After": str(ttl),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_at)
        return response
