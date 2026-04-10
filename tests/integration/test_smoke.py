"""Smoke tests to verify local dev services are running and accessible."""

import pytest

pytestmark = pytest.mark.integration


async def test_postgres_accepts_connections(pg_pool):
    """PostgreSQL is running and responds to queries."""
    async with pg_pool.acquire() as conn:
        result = await conn.fetchval("SELECT 1")
    assert result == 1


async def test_postgres_version(pg_pool):
    """PostgreSQL is version 16.x as required by the spec."""
    async with pg_pool.acquire() as conn:
        version = await conn.fetchval("SHOW server_version")
    assert version.startswith("16"), f"Expected PostgreSQL 16.x, got {version}"


async def test_postgres_test_database_exists(pg_pool):
    """The workflows_test database exists and is writable."""
    async with pg_pool.acquire() as conn:
        db_name = await conn.fetchval("SELECT current_database()")
    assert db_name == "workflows_test"


async def test_redis_accepts_connections(redis_client):
    """Redis is running and responds to PING."""
    result = await redis_client.ping()
    assert result is True


async def test_redis_read_write(redis_client):
    """Redis accepts writes and reads back data."""
    await redis_client.set("smoke_test_key", "smoke_test_value")
    result = await redis_client.get("smoke_test_key")
    assert result == "smoke_test_value"
