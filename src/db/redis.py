"""Redis client for arq task queue and caching.

Provides a shared Redis client factory. Each call to get_redis() returns
a new client instance configured from application settings. The close_redis()
function disposes the module-level client used during the application lifespan.
"""

import redis.asyncio as aioredis

from src.config import settings
from src.lib.logger import get_logger

logger = get_logger(__name__)

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Create and return a Redis client from configured URL.

    Returns a new client instance each call. Callers are responsible
    for closing the client when done, or use the module-level
    close_redis() during shutdown.

    Returns:
        An async Redis client connected to the configured URL.
    """
    global _client
    _client = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
    )
    return _client


async def close_redis() -> None:
    """Close the module-level Redis client if it exists.

    Call during application shutdown to release Redis resources.
    """
    global _client
    if _client is not None:
        logger.info("closing_redis")
        await _client.aclose()
        _client = None
