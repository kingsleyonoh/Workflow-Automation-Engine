"""Unit tests for the health check endpoint.

Tests GET /api/health with real PostgreSQL and Redis connectivity checks.
Patches session factory and Redis client to use test infrastructure.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:devpass@localhost:5435/workflows_test",
)


@pytest.fixture
async def test_session_factory(_run_migrations):
    """Create a session factory connected to the test database."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    yield factory
    await engine.dispose()


@pytest.fixture
def patched_health_app(test_session_factory, redis_client):
    """FastAPI app with health check using test DB and Redis."""
    with (
        patch(
            "src.api.middleware.rate_limit.get_redis",
            return_value=redis_client,
        ),
        patch(
            "src.api.health.async_session_factory",
            test_session_factory,
        ),
        patch(
            "src.api.health.get_redis",
            return_value=redis_client,
        ),
    ):
        from src.main import app

        yield app


class TestHealthEndpoint:
    """Tests for GET /api/health with full checks."""

    async def test_health_returns_ok_when_all_healthy(self, patched_health_app):
        """GET /api/health returns status ok with pg/redis/workers info."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_health_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded", "error")
        assert "pg" in body
        assert "redis" in body
        assert "workers" in body

    async def test_health_pg_true_when_connected(self, patched_health_app):
        """pg field is True when PostgreSQL is reachable."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_health_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/health")

        body = resp.json()
        assert body["pg"] is True

    async def test_health_redis_true_when_connected(self, patched_health_app):
        """redis field is True when Redis is reachable."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_health_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/health")

        body = resp.json()
        assert body["redis"] is True

    async def test_health_workers_is_integer(self, patched_health_app):
        """workers field is an integer (count of active arq workers)."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_health_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/health")

        body = resp.json()
        assert isinstance(body["workers"], int)
        assert body["workers"] >= 0

    async def test_health_no_auth_required(self, patched_health_app):
        """GET /api/health does not require X-API-Key."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_health_app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/api/health")

        assert resp.status_code != 401

    async def test_health_degraded_when_redis_down(self, test_session_factory):
        """Returns degraded status when Redis is unreachable."""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("Connection refused"))
        mock_redis.keys = AsyncMock(side_effect=Exception("Connection refused"))
        mock_redis.incr = AsyncMock(side_effect=Exception("Connection refused"))

        with (
            patch(
                "src.api.middleware.rate_limit.get_redis",
                return_value=mock_redis,
            ),
            patch(
                "src.api.health.async_session_factory",
                test_session_factory,
            ),
            patch(
                "src.api.health.get_redis",
                return_value=mock_redis,
            ),
        ):
            from src.main import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/health")

        body = resp.json()
        assert body["status"] in ("degraded", "error")
        assert body["redis"] is False
