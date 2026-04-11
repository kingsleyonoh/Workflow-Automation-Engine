"""arq worker configuration for step execution.

Defines WorkerSettings with Redis connection, registered functions,
concurrency settings, and startup/shutdown hooks for DB connections.
Start with: arq src.queue.worker.WorkerSettings
"""

from typing import Any
from urllib.parse import urlparse

from arq.connections import RedisSettings

from src.config import settings
from src.lib.logger import get_logger

logger = get_logger(__name__)


def _parse_redis_url(url: str) -> RedisSettings:
    """Parse a Redis URL into arq RedisSettings.

    Args:
        url: Redis connection URL (redis://host:port/db).

    Returns:
        arq RedisSettings instance.
    """
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


async def on_startup(ctx: dict[str, Any]) -> None:
    """Worker startup hook — initialize DB and Redis connections.

    Creates the async session factory and Redis client, storing
    them in the worker context for use by task functions.

    Args:
        ctx: arq worker context dict (mutable, shared across jobs).
    """
    from src.db.postgres import async_session_factory
    from src.db.redis import get_redis
    from src.lib.logger import configure_logging

    configure_logging()
    logger.info("worker_startup", concurrency=settings.arq_concurrency)

    ctx["db_session_factory"] = async_session_factory
    ctx["redis"] = get_redis()


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Worker shutdown hook — close DB and Redis connections.

    Args:
        ctx: arq worker context dict.
    """
    from src.db.postgres import dispose_engine

    logger.info("worker_shutdown")

    redis = ctx.get("redis")
    if redis is not None:
        await redis.aclose()

    await dispose_engine()


class WorkerSettings:
    """arq worker settings for step execution.

    Start with: ``arq src.queue.worker.WorkerSettings``
    """

    from src.queue.tasks import execute_step

    functions = [execute_step]
    redis_settings = _parse_redis_url(settings.redis_url)
    max_jobs = settings.arq_concurrency
    on_startup = on_startup
    on_shutdown = on_shutdown
