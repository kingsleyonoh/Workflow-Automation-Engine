"""Unit tests for Redis-based rate limiting middleware.

Tests rate limit enforcement, header injection, 429 responses,
and per-route configuration using real Redis.
"""

import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
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
def patched_app(test_session_factory, redis_client):
    """FastAPI app with all dependencies patched for test infrastructure."""
    with (
        patch(
            "src.api.middleware.auth.async_session_factory",
            test_session_factory,
        ),
        patch(
            "src.api.tenants.async_session_factory",
            test_session_factory,
        ),
        patch(
            "src.api.health.async_session_factory",
            test_session_factory,
        ),
        patch(
            "src.api.health.get_redis",
            return_value=redis_client,
        ),
        patch(
            "src.api.middleware.rate_limit.get_redis",
            return_value=redis_client,
        ),
    ):
        from src.main import app

        yield app


class TestRateLimitHeaders:
    """Tests for rate limit response headers."""

    async def test_response_includes_rate_limit_headers(self, patched_app):
        """Successful request includes X-RateLimit-* headers."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        assert "X-RateLimit-Limit" in resp.headers
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers

    async def test_remaining_decrements_on_each_request(self, patched_app):
        """X-RateLimit-Remaining decreases with each request."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp1 = await client.get("/api/health")
            resp2 = await client.get("/api/health")

        remaining1 = int(resp1.headers["X-RateLimit-Remaining"])
        remaining2 = int(resp2.headers["X-RateLimit-Remaining"])
        assert remaining2 < remaining1


class TestRateLimitEnforcement:
    """Tests for rate limit enforcement with 429 responses."""

    async def test_exceeding_limit_returns_429(self, patched_app, test_session_factory):
        """Exceeding rate limit returns 429 Too Many Requests."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            for _ in range(6):
                resp = await client.post(
                    "/api/tenants/register",
                    json={"name": "Rate Test"},
                )

        # The 6th request should be rate limited
        assert resp.status_code == 429

        # Clean up any created tenants
        from src.db.models import Tenant

        async with test_session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.name == "Rate Test"))
            await session.commit()

    async def test_429_response_has_error_format(
        self, patched_app, test_session_factory
    ):
        """429 response follows standard error response format."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            for _ in range(6):
                resp = await client.post(
                    "/api/tenants/register",
                    json={"name": "Rate Fmt"},
                )

        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"

        # Clean up
        from src.db.models import Tenant

        async with test_session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.name == "Rate Fmt"))
            await session.commit()

    async def test_429_includes_rate_limit_headers(
        self, patched_app, test_session_factory
    ):
        """429 response includes rate limit headers."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            for _ in range(6):
                resp = await client.post(
                    "/api/tenants/register",
                    json={"name": "Rate Hdr"},
                )

        assert "X-RateLimit-Limit" in resp.headers
        assert int(resp.headers["X-RateLimit-Remaining"]) == 0

        # Clean up
        from src.db.models import Tenant

        async with test_session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.name == "Rate Hdr"))
            await session.commit()


class TestRateLimitPerRoute:
    """Tests for per-route rate limit configuration."""

    async def test_register_has_5_per_min_limit(
        self, patched_app, test_session_factory
    ):
        """POST /api/tenants/register is limited to 5/min."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            responses = []
            for _ in range(6):
                resp = await client.post(
                    "/api/tenants/register",
                    json={"name": "Limit Test"},
                )
                responses.append(resp)

        # First 5 should pass (not 429), 6th should be 429
        for r in responses[:5]:
            assert r.status_code != 429
        assert responses[5].status_code == 429

        # Clean up
        from src.db.models import Tenant

        async with test_session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.name == "Limit Test"))
            await session.commit()

    async def test_default_route_has_100_per_min_limit(self, patched_app):
        """Default routes have 100/min limit — not hit easily in tests."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/health")

        assert int(resp.headers["X-RateLimit-Limit"]) == 100
