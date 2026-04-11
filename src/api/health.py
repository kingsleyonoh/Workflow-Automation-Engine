"""Health check endpoint with PostgreSQL, Redis, and arq worker status.

Checks database connectivity via SELECT 1, Redis via PING, and arq
worker count via Redis key scanning. Returns overall system status.
"""

from fastapi import APIRouter
from sqlalchemy import text

from src.db.postgres import async_session_factory
from src.db.redis import get_redis
from src.lib.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


async def _check_postgres() -> bool:
    """Check PostgreSQL connectivity with SELECT 1.

    Returns:
        True if PostgreSQL responds, False otherwise.
    """
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("health_pg_check_failed", exc_info=True)
        return False


async def _check_redis() -> bool:
    """Check Redis connectivity with PING.

    Returns:
        True if Redis responds, False otherwise.
    """
    try:
        redis = get_redis()
        await redis.ping()
        return True
    except Exception:
        logger.warning("health_redis_check_failed", exc_info=True)
        return False


async def _count_workers() -> int:
    """Count active arq workers by scanning Redis keys.

    arq workers register keys matching 'arq:worker:*' in Redis.

    Returns:
        Number of active arq workers, or 0 if check fails.
    """
    try:
        redis = get_redis()
        keys = await redis.keys("arq:worker:*")
        return len(keys)
    except Exception:
        logger.warning("health_worker_check_failed", exc_info=True)
        return 0


def _compute_status(pg: bool, redis: bool) -> str:
    """Compute overall system status from component checks.

    Args:
        pg: PostgreSQL connectivity status.
        redis: Redis connectivity status.

    Returns:
        "ok" if all healthy, "degraded" if some down, "error" if all down.
    """
    if pg and redis:
        return "ok"
    if pg or redis:
        return "degraded"
    return "error"


@router.get("/api/health")
async def health_check() -> dict:
    """Full health check with PostgreSQL, Redis, and worker status.

    Returns overall system status and individual component health.
    No authentication required. No rate limiting applied.

    Returns:
        Dictionary with status, pg, redis, and workers fields.
    """
    pg = await _check_postgres()
    redis_ok = await _check_redis()
    workers = await _count_workers()
    status = _compute_status(pg, redis_ok)

    if status != "ok":
        logger.warning(
            "health_check_degraded",
            status=status,
            pg=pg,
            redis=redis_ok,
            workers=workers,
        )

    return {
        "status": status,
        "pg": pg,
        "redis": redis_ok,
        "workers": workers,
    }
