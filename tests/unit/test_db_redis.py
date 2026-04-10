"""Unit tests for Redis client module."""

import redis.asyncio as aioredis


async def test_get_redis_returns_client():
    """get_redis returns a Redis client instance."""
    from src.db.redis import get_redis

    client = get_redis()
    assert isinstance(client, aioredis.Redis)


async def test_redis_client_connects_to_configured_url():
    """Redis client connects to the URL from settings."""
    from src.db.redis import get_redis

    client = get_redis()
    # Verify the client can ping (requires running Redis)
    result = await client.ping()
    assert result is True
    await client.aclose()


async def test_redis_client_read_write():
    """Redis client can write and read data."""
    from src.db.redis import get_redis

    client = get_redis()
    await client.set("test_redis_module_key", "test_value")
    result = await client.get("test_redis_module_key")
    assert result == "test_value"
    await client.delete("test_redis_module_key")
    await client.aclose()


async def test_close_redis_disposes_connection():
    """close_redis closes the Redis connection pool cleanly."""
    from src.db.redis import close_redis, get_redis

    client = get_redis()
    assert await client.ping() is True
    await close_redis()
    # After close, a new get_redis should still work (creates new)
    client2 = get_redis()
    assert await client2.ping() is True
    await client2.aclose()
