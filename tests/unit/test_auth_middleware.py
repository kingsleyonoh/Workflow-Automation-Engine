"""Unit tests for API key validation middleware.

Tests the auth middleware via httpx.AsyncClient against the FastAPI app,
verifying public path exemptions, header extraction, and error responses.
Uses a patched session factory to connect the middleware to the test database.
"""

import os
from unittest.mock import patch

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
def patched_app(test_session_factory, redis_client):
    """FastAPI app with auth middleware using the test database."""
    with (
        patch(
            "src.api.middleware.auth.async_session_factory",
            test_session_factory,
        ),
        patch(
            "src.api.workflows.async_session_factory",
            test_session_factory,
        ),
        patch(
            "src.api.webhooks.async_session_factory",
            test_session_factory,
        ),
        patch(
            "src.api.executions.async_session_factory",
            test_session_factory,
        ),
        patch(
            "src.api.middleware.rate_limit.get_redis",
            return_value=redis_client,
        ),
    ):
        from src.main import app

        yield app


class TestAuthMiddlewarePublicPaths:
    """Tests for paths that should NOT require authentication."""

    async def test_health_endpoint_no_auth(self, patched_app):
        """GET /api/health succeeds without API key."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_docs_endpoint_no_auth(self, patched_app):
        """GET /docs succeeds without API key."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/docs")
        assert resp.status_code == 200

    async def test_openapi_json_no_auth(self, patched_app):
        """GET /openapi.json succeeds without API key."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/openapi.json")
        assert resp.status_code == 200


class TestAuthMiddlewareMissingKey:
    """Tests for requests missing the X-API-Key header."""

    async def test_protected_path_missing_key_returns_401(self, patched_app):
        """Request to protected path without X-API-Key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/workflows")
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "INVALID_API_KEY"

    async def test_protected_path_empty_key_returns_401(self, patched_app):
        """Request with empty X-API-Key header returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/workflows", headers={"X-API-Key": ""}
            )
        assert resp.status_code == 401


class TestAuthMiddlewareInvalidKey:
    """Tests for requests with invalid API keys."""

    async def test_invalid_key_returns_401(self, patched_app):
        """Request with invalid API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/workflows",
                headers={
                    "X-API-Key": "wae_live_deadbeefdeadbeefdeadbeefdeadbeef"
                },
            )
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "INVALID_API_KEY"


class TestAuthMiddlewareValidKey:
    """Tests for requests with valid API keys."""

    async def test_valid_key_passes_through(
        self, patched_app, test_session_factory
    ):
        """Valid API key passes auth and reaches the handler."""
        from src.tenants.service import register_tenant

        # Use a real committed session so the middleware can see the data
        async with test_session_factory() as session:
            result = await register_tenant(
                name="Auth Test Corp", session=session
            )
            await session.commit()

        try:
            async with AsyncClient(
                transport=ASGITransport(app=patched_app),
                base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/workflows",
                    headers={"X-API-Key": result.api_key},
                )
            # Should be 404 (route doesn't exist yet) or 200, not 401
            assert resp.status_code != 401
        finally:
            # Clean up the committed tenant
            from sqlalchemy import delete

            from src.db.models import Tenant

            async with test_session_factory() as session:
                await session.execute(
                    delete(Tenant).where(Tenant.id == result.id)
                )
                await session.commit()


class TestAuthMiddlewareWebhookExemption:
    """Tests for webhook path exemption."""

    async def test_webhooks_path_no_auth(self, patched_app):
        """Webhook paths are exempt from auth."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post("/webhooks/some-path")
        # Should not be 401 — route may not exist yet (404 is fine)
        assert resp.status_code != 401


class TestAuthMiddlewareRegisterExemption:
    """Tests for tenant registration path exemption."""

    async def test_register_path_no_auth(self, patched_app):
        """POST /api/tenants/register is exempt from auth."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/tenants/register")
        # Should not be 401 — route may not exist (404/422 is fine)
        assert resp.status_code != 401
