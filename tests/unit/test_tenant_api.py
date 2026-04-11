"""Unit tests for tenant API endpoints.

Tests POST /api/tenants/register and GET /api/tenants/me against
real PostgreSQL via httpx.AsyncClient with the FastAPI app.
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
    """FastAPI app with auth middleware + rate limiter using test resources."""
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
            "src.api.middleware.rate_limit.get_redis",
            return_value=redis_client,
        ),
    ):
        from src.main import app

        yield app


class TestRegisterTenantEndpoint:
    """Tests for POST /api/tenants/register."""

    async def test_register_happy_path(self, patched_app, test_session_factory):
        """POST /api/tenants/register with valid name returns 201 with tenant data."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/tenants/register",
                json={"name": "Test Corp"},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert body["name"] == "Test Corp"
        assert "api_key" in body
        assert body["api_key"].startswith("wae_live_")

        # Clean up
        from src.db.models import Tenant

        async with test_session_factory() as session:
            await session.execute(delete(Tenant).where(Tenant.name == "Test Corp"))
            await session.commit()

    async def test_register_missing_name_returns_422(self, patched_app):
        """POST /api/tenants/register without name returns 422."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/tenants/register",
                json={},
            )

        assert resp.status_code == 422

    async def test_register_empty_name_returns_422(self, patched_app):
        """POST /api/tenants/register with blank name returns 422."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/tenants/register",
                json={"name": "   "},
            )

        assert resp.status_code == 422

    async def test_register_no_auth_required(self, patched_app):
        """POST /api/tenants/register does not require X-API-Key."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/tenants/register",
                json={"name": "No Auth Test"},
            )

        # Should not be 401
        assert resp.status_code != 401

        # Clean up if created
        if resp.status_code == 201:
            from src.db.models import Tenant

            engine = create_async_engine(TEST_DATABASE_URL, echo=False)
            factory = async_sessionmaker(
                bind=engine, class_=AsyncSession, expire_on_commit=False
            )
            async with factory() as session:
                await session.execute(
                    delete(Tenant).where(Tenant.name == "No Auth Test")
                )
                await session.commit()
            await engine.dispose()

    async def test_register_disabled_returns_403(
        self, test_session_factory, redis_client
    ):
        """Register when SELF_REGISTRATION_ENABLED=False returns 403."""
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
                "src.api.middleware.rate_limit.get_redis",
                return_value=redis_client,
            ),
            patch("src.api.tenants.settings") as mock_settings,
        ):
            mock_settings.self_registration_enabled = False

            from src.main import app

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/tenants/register",
                    json={"name": "Blocked Corp"},
                )

        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "REGISTRATION_DISABLED"


class TestTenantMeEndpoint:
    """Tests for GET /api/tenants/me."""

    async def test_me_happy_path(self, patched_app, test_session_factory):
        """GET /api/tenants/me with valid API key returns tenant profile."""
        from src.tenants.service import register_tenant

        # Create a tenant
        async with test_session_factory() as session:
            result = await register_tenant(name="Me Test Corp", session=session)
            await session.commit()

        try:
            async with AsyncClient(
                transport=ASGITransport(app=patched_app),
                base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/tenants/me",
                    headers={"X-API-Key": result.api_key},
                )

            assert resp.status_code == 200
            body = resp.json()
            assert body["id"] == str(result.id)
            assert body["name"] == "Me Test Corp"
            assert body["is_active"] is True
            assert "created_at" in body
        finally:
            from src.db.models import Tenant

            async with test_session_factory() as session:
                await session.execute(
                    delete(Tenant).where(Tenant.id == result.id)
                )
                await session.commit()

    async def test_me_without_api_key_returns_401(self, patched_app):
        """GET /api/tenants/me without X-API-Key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/tenants/me")

        assert resp.status_code == 401

    async def test_me_invalid_api_key_returns_401(self, patched_app):
        """GET /api/tenants/me with invalid API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/tenants/me",
                headers={"X-API-Key": "wae_live_invalidinvalidinvalidin"},
            )

        assert resp.status_code == 401

    async def test_me_does_not_expose_api_key(
        self, patched_app, test_session_factory
    ):
        """GET /api/tenants/me response does NOT include the API key."""
        from src.tenants.service import register_tenant

        async with test_session_factory() as session:
            result = await register_tenant(name="No Key Corp", session=session)
            await session.commit()

        try:
            async with AsyncClient(
                transport=ASGITransport(app=patched_app),
                base_url="http://test",
            ) as client:
                resp = await client.get(
                    "/api/tenants/me",
                    headers={"X-API-Key": result.api_key},
                )

            body = resp.json()
            assert "api_key" not in body
            assert "api_key_hash" not in body
            assert "api_key_prefix" not in body
        finally:
            from src.db.models import Tenant

            async with test_session_factory() as session:
                await session.execute(
                    delete(Tenant).where(Tenant.id == result.id)
                )
                await session.commit()
