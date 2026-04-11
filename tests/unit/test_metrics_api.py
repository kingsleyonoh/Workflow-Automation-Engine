"""Unit tests for GET /api/metrics/executions endpoint.

Tests execution analytics with tenant scoping, auth, response shape,
and aggregation correctness.
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import (
    Execution,
    StepExecution,
    Tenant,
    WebhookDelivery,
    Workflow,
)

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:devpass@localhost:5435/workflows_test",
)


def _valid_steps() -> list[dict]:
    """Return a minimal valid steps array."""
    return [
        {
            "id": "step_1",
            "type": "transform",
            "config": {"expression": "{{ trigger.payload }}"},
        }
    ]


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
    """FastAPI app with test DB and Redis for metrics tests."""
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
            "src.api.metrics.async_session_factory",
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
        result = await register_tenant(name="Metrics Test Tenant", session=session)
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
        result = await register_tenant(name="Other Metrics Tenant", session=session)
        await session.commit()

    yield result.api_key, result.id

    async with test_session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == result.id))
        await session.commit()


@pytest.fixture
async def metrics_data(test_session_factory, tenant_api_key):
    """Create test data for metrics: workflow, executions, steps, webhooks."""
    api_key, tenant_id = tenant_api_key
    now = datetime.now(UTC)

    async with test_session_factory() as session:
        workflow = Workflow(
            tenant_id=tenant_id,
            name="Metrics Flow",
            trigger_type="webhook",
            trigger_config={},
            steps=_valid_steps(),
            is_active=True,
        )
        session.add(workflow)
        await session.flush()

        # Create completed executions with duration
        exec1 = Execution(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            status="completed",
            trigger_data={"source": "test"},
            context={},
            started_at=now - timedelta(seconds=2),
            completed_at=now,
            duration_ms=2000,
        )
        exec2 = Execution(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            status="completed",
            trigger_data={"source": "test"},
            context={},
            started_at=now - timedelta(seconds=3),
            completed_at=now,
            duration_ms=3000,
        )
        exec3 = Execution(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            status="failed",
            trigger_data={"source": "test"},
            context={},
            started_at=now - timedelta(seconds=1),
            completed_at=now,
            duration_ms=1000,
        )
        session.add_all([exec1, exec2, exec3])
        await session.flush()

        # Create step executions
        step1 = StepExecution(
            tenant_id=tenant_id,
            execution_id=exec1.id,
            step_id="step_1",
            step_type="transform",
            status="completed",
            input_data={},
        )
        step2 = StepExecution(
            tenant_id=tenant_id,
            execution_id=exec2.id,
            step_id="step_1",
            step_type="transform",
            status="completed",
            input_data={},
        )
        step3 = StepExecution(
            tenant_id=tenant_id,
            execution_id=exec3.id,
            step_id="step_1",
            step_type="transform",
            status="failed",
            input_data={},
            error="Transform failed",
        )
        session.add_all([step1, step2, step3])
        await session.flush()

        # Create webhook deliveries
        wd1 = WebhookDelivery(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            execution_id=exec1.id,
            method="POST",
            headers={},
            payload={},
            status="accepted",
        )
        wd2 = WebhookDelivery(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            execution_id=exec2.id,
            method="POST",
            headers={},
            payload={},
            status="rejected",
        )
        session.add_all([wd1, wd2])
        await session.commit()

        exec_ids = [exec1.id, exec2.id, exec3.id]
        step_ids = [step1.id, step2.id, step3.id]
        wd_ids = [wd1.id, wd2.id]

    yield {
        "workflow": workflow,
        "api_key": api_key,
        "tenant_id": tenant_id,
        "execution_ids": exec_ids,
    }

    async with test_session_factory() as session:
        for wd_id in wd_ids:
            await session.execute(
                delete(WebhookDelivery).where(WebhookDelivery.id == wd_id)
            )
        for s_id in step_ids:
            await session.execute(delete(StepExecution).where(StepExecution.id == s_id))
        for e_id in exec_ids:
            await session.execute(delete(Execution).where(Execution.id == e_id))
        await session.execute(delete(Workflow).where(Workflow.id == workflow.id))
        await session.commit()


class TestExecutionMetrics:
    """Tests for GET /api/metrics/executions."""

    async def test_metrics_returns_200(self, patched_app, metrics_data):
        """GET /api/metrics/executions returns 200 with metrics shape."""
        api_key = metrics_data["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/metrics/executions",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "by_status" in body
        assert "avg_duration_ms" in body
        assert "by_workflow" in body
        assert "step_failure_rates" in body
        assert "webhook_delivery_stats" in body

    async def test_metrics_total_count(self, patched_app, metrics_data):
        """Metrics total reflects correct execution count."""
        api_key = metrics_data["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/metrics/executions",
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        assert body["total"] == 3

    async def test_metrics_by_status(self, patched_app, metrics_data):
        """Metrics by_status counts are correct."""
        api_key = metrics_data["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/metrics/executions",
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        assert body["by_status"]["completed"] == 2
        assert body["by_status"]["failed"] == 1

    async def test_metrics_avg_duration(self, patched_app, metrics_data):
        """Metrics avg_duration_ms is correctly calculated."""
        api_key = metrics_data["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/metrics/executions",
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        # (2000 + 3000 + 1000) / 3 = 2000
        assert body["avg_duration_ms"] == 2000

    async def test_metrics_by_workflow(self, patched_app, metrics_data):
        """Metrics by_workflow includes per-workflow breakdown."""
        api_key = metrics_data["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/metrics/executions",
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        assert len(body["by_workflow"]) >= 1
        wf = body["by_workflow"][0]
        assert "workflow_id" in wf
        assert "workflow_name" in wf
        assert "count" in wf
        assert "avg_duration_ms" in wf

    async def test_metrics_step_failure_rates(self, patched_app, metrics_data):
        """Metrics step_failure_rates includes per-type breakdown."""
        api_key = metrics_data["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/metrics/executions",
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        assert len(body["step_failure_rates"]) >= 1
        sfr = body["step_failure_rates"][0]
        assert "step_type" in sfr
        assert "total" in sfr
        assert "failed" in sfr
        assert "rate" in sfr

    async def test_metrics_webhook_stats(self, patched_app, metrics_data):
        """Metrics webhook_delivery_stats includes delivery counts."""
        api_key = metrics_data["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/metrics/executions",
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        stats = body["webhook_delivery_stats"]
        assert stats["total"] == 2
        assert stats["accepted"] == 1
        assert stats["rejected"] == 1

    async def test_metrics_requires_auth(self, patched_app):
        """GET /api/metrics/executions without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/metrics/executions")

        assert resp.status_code == 401

    async def test_metrics_tenant_isolation(
        self, patched_app, metrics_data, second_tenant_api_key
    ):
        """Tenant B cannot see Tenant A's metrics."""
        api_key_b, _ = second_tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/metrics/executions",
                headers={"X-API-Key": api_key_b},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0

    async def test_metrics_empty_tenant(self, patched_app, tenant_api_key):
        """Metrics returns zero counts for tenant with no executions."""
        api_key, _ = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/metrics/executions",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["avg_duration_ms"] == 0
        assert body["by_status"] == {}
        assert body["by_workflow"] == []
        assert body["step_failure_rates"] == []
