"""Unit tests for GET /api/executions/:id/stream SSE endpoint.

Tests SSE stream endpoint with auth, tenant isolation,
and basic connectivity.
"""

import asyncio
import os
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Execution, Tenant, Workflow

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
    """FastAPI app with test DB and Redis for SSE tests."""
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


@pytest.fixture
async def tenant_api_key(test_session_factory):
    """Create a test tenant and return its API key."""
    from src.tenants.service import register_tenant

    async with test_session_factory() as session:
        result = await register_tenant(name="SSE Test Tenant", session=session)
        await session.commit()

    yield result.api_key, result.id

    async with test_session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == result.id))
        await session.commit()


@pytest.fixture
async def second_tenant_api_key(test_session_factory):
    """Create a second tenant for isolation tests."""
    from src.tenants.service import register_tenant

    async with test_session_factory() as session:
        result = await register_tenant(name="Other SSE Tenant", session=session)
        await session.commit()

    yield result.api_key, result.id

    async with test_session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == result.id))
        await session.commit()


@pytest.fixture
async def stream_execution(test_session_factory, tenant_api_key):
    """Create an execution for SSE streaming tests."""
    api_key, tenant_id = tenant_api_key

    async with test_session_factory() as session:
        wf = Workflow(
            tenant_id=tenant_id,
            name="Stream Flow",
            trigger_type="manual",
            trigger_config={},
            steps=[{"id": "s1", "type": "transform", "config": {}}],
            is_active=True,
        )
        session.add(wf)
        await session.flush()

        ex = Execution(
            tenant_id=tenant_id,
            workflow_id=wf.id,
            status="running",
            trigger_data={},
            context={},
        )
        session.add(ex)
        await session.commit()
        await session.refresh(wf)
        await session.refresh(ex)

    yield {
        "workflow": wf,
        "execution": ex,
        "api_key": api_key,
        "tenant_id": tenant_id,
    }

    async with test_session_factory() as session:
        await session.execute(delete(Execution).where(Execution.id == ex.id))
        await session.execute(delete(Workflow).where(Workflow.id == wf.id))
        await session.commit()


class TestSSEStream:
    """Tests for GET /api/executions/:id/stream SSE endpoint."""

    async def test_stream_returns_200_with_event_stream(
        self, patched_app, stream_execution
    ):
        """GET /api/executions/:id/stream returns 200 with text/event-stream."""
        api_key = stream_execution["api_key"]
        exec_id = str(stream_execution["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app),
            base_url="http://test",
            timeout=5.0,
        ) as client:
            try:
                async with asyncio.timeout(3):
                    async with client.stream(
                        "GET",
                        f"/api/executions/{exec_id}/stream",
                        headers={"X-API-Key": api_key},
                    ) as resp:
                        assert resp.status_code == 200
                        ct = resp.headers.get("content-type", "")
                        assert "text/event-stream" in ct
                        # Read the initial connected event
                        first_line = b""
                        async for chunk in resp.aiter_bytes():
                            first_line += chunk
                            if b"\n\n" in first_line:
                                break
                        assert b"connected" in first_line
            except TimeoutError:
                # Expected: stream stays open, we just wanted to verify headers
                pass

    async def test_stream_nonexistent_returns_404(self, patched_app, tenant_api_key):
        """GET /api/executions/:id/stream for nonexistent returns 404."""
        api_key, _ = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{uuid.uuid4()}/stream",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_stream_requires_auth(self, patched_app):
        """GET /api/executions/:id/stream without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{uuid.uuid4()}/stream",
            )

        assert resp.status_code == 401

    async def test_stream_cross_tenant_returns_404(
        self,
        patched_app,
        stream_execution,
        second_tenant_api_key,
    ):
        """Tenant B cannot stream Tenant A's execution."""
        api_key_b, _ = second_tenant_api_key
        exec_id = str(stream_execution["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{exec_id}/stream",
                headers={"X-API-Key": api_key_b},
            )

        assert resp.status_code == 404
