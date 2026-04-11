"""Unit tests for GET /api/executions/:id/logs endpoint.

Tests logs endpoint with auth, tenant isolation,
step_id filtering, and ordered results.
"""

import os
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Execution, ExecutionLog, Tenant, Workflow

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
    """FastAPI app with test DB and Redis for logs tests."""
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
        result = await register_tenant(name="Logs Test Tenant", session=session)
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
        result = await register_tenant(name="Other Logs Tenant", session=session)
        await session.commit()

    yield result.api_key, result.id

    async with test_session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == result.id))
        await session.commit()


@pytest.fixture
async def execution_with_logs(test_session_factory, tenant_api_key):
    """Create an execution with log entries for testing."""
    api_key, tenant_id = tenant_api_key

    async with test_session_factory() as session:
        wf = Workflow(
            tenant_id=tenant_id,
            name="Logs Flow",
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
            status="completed",
            trigger_data={},
            context={},
        )
        session.add(ex)
        await session.flush()

        log1 = ExecutionLog(
            tenant_id=tenant_id,
            execution_id=ex.id,
            level="info",
            message="Execution started",
            data={},
        )
        log2 = ExecutionLog(
            tenant_id=tenant_id,
            execution_id=ex.id,
            step_id="s1",
            level="info",
            message="Step s1 completed",
            data={"duration_ms": 15},
        )
        log3 = ExecutionLog(
            tenant_id=tenant_id,
            execution_id=ex.id,
            level="warn",
            message="Slow response",
            data={},
        )
        session.add_all([log1, log2, log3])
        await session.commit()
        await session.refresh(wf)
        await session.refresh(ex)
        await session.refresh(log1)
        await session.refresh(log2)
        await session.refresh(log3)

    yield {
        "workflow": wf,
        "execution": ex,
        "logs": [log1, log2, log3],
        "api_key": api_key,
        "tenant_id": tenant_id,
    }

    async with test_session_factory() as session:
        await session.execute(
            delete(ExecutionLog).where(ExecutionLog.execution_id == ex.id)
        )
        await session.execute(delete(Execution).where(Execution.id == ex.id))
        await session.execute(delete(Workflow).where(Workflow.id == wf.id))
        await session.commit()


class TestGetExecutionLogs:
    """Tests for GET /api/executions/:id/logs."""

    async def test_get_logs_returns_200(self, patched_app, execution_with_logs):
        """GET /api/executions/:id/logs returns 200 with logs array."""
        api_key = execution_with_logs["api_key"]
        exec_id = str(execution_with_logs["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{exec_id}/logs",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "logs" in body
        assert len(body["logs"]) == 3

    async def test_get_logs_ordered_by_created_at(
        self, patched_app, execution_with_logs
    ):
        """Logs are ordered by created_at ascending."""
        api_key = execution_with_logs["api_key"]
        exec_id = str(execution_with_logs["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{exec_id}/logs",
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        timestamps = [log["created_at"] for log in body["logs"]]
        assert timestamps == sorted(timestamps)

    async def test_get_logs_filter_by_step_id(self, patched_app, execution_with_logs):
        """GET /api/executions/:id/logs?step_id=s1 filters logs by step."""
        api_key = execution_with_logs["api_key"]
        exec_id = str(execution_with_logs["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{exec_id}/logs?step_id=s1",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["logs"]) == 1
        assert body["logs"][0]["step_id"] == "s1"

    async def test_get_logs_nonexistent_execution_returns_404(
        self, patched_app, tenant_api_key
    ):
        """GET /api/executions/:id/logs for nonexistent execution returns 404."""
        api_key, _ = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{uuid.uuid4()}/logs",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_get_logs_requires_auth(self, patched_app):
        """GET /api/executions/:id/logs without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{uuid.uuid4()}/logs",
            )

        assert resp.status_code == 401

    async def test_get_logs_cross_tenant_returns_404(
        self,
        patched_app,
        execution_with_logs,
        second_tenant_api_key,
    ):
        """Tenant B cannot see Tenant A's execution logs."""
        api_key_b, _ = second_tenant_api_key
        exec_id = str(execution_with_logs["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{exec_id}/logs",
                headers={"X-API-Key": api_key_b},
            )

        assert resp.status_code == 404

    async def test_get_logs_response_structure(self, patched_app, execution_with_logs):
        """Each log entry has the expected fields."""
        api_key = execution_with_logs["api_key"]
        exec_id = str(execution_with_logs["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{exec_id}/logs",
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        log = body["logs"][0]
        assert "id" in log
        assert "level" in log
        assert "message" in log
        assert "data" in log
        assert "created_at" in log

    async def test_get_logs_empty_execution(
        self, patched_app, tenant_api_key, test_session_factory
    ):
        """Execution with no logs returns empty array."""
        api_key, tenant_id = tenant_api_key

        async with test_session_factory() as session:
            wf = Workflow(
                tenant_id=tenant_id,
                name="No Logs Flow",
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
                status="completed",
                trigger_data={},
                context={},
            )
            session.add(ex)
            await session.commit()
            await session.refresh(ex)
            await session.refresh(wf)

        try:
            async with AsyncClient(
                transport=ASGITransport(app=patched_app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/api/executions/{ex.id}/logs",
                    headers={"X-API-Key": api_key},
                )

            assert resp.status_code == 200
            body = resp.json()
            assert body["logs"] == []
        finally:
            async with test_session_factory() as session:
                await session.execute(delete(Execution).where(Execution.id == ex.id))
                await session.execute(delete(Workflow).where(Workflow.id == wf.id))
                await session.commit()
