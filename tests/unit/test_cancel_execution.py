"""Unit tests for POST /api/executions/:id/cancel endpoint.

Tests cancel execution endpoint with auth, tenant isolation,
and state transition validation.
"""

import os
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Execution, StepExecution, Tenant, Workflow

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
    """FastAPI app with test DB and Redis for cancel tests."""
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
        result = await register_tenant(name="Cancel Test Tenant", session=session)
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
        result = await register_tenant(name="Other Cancel Tenant", session=session)
        await session.commit()

    yield result.api_key, result.id

    async with test_session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == result.id))
        await session.commit()


@pytest.fixture
async def running_execution(test_session_factory, tenant_api_key):
    """Create a running execution with pending steps."""
    api_key, tenant_id = tenant_api_key

    async with test_session_factory() as session:
        workflow = Workflow(
            tenant_id=tenant_id,
            name="Cancel Flow",
            trigger_type="manual",
            trigger_config={},
            steps=_valid_steps(),
            is_active=True,
        )
        session.add(workflow)
        await session.flush()

        execution = Execution(
            tenant_id=tenant_id,
            workflow_id=workflow.id,
            status="running",
            trigger_data={"source": "test"},
            context={},
        )
        session.add(execution)
        await session.flush()

        step1 = StepExecution(
            tenant_id=tenant_id,
            execution_id=execution.id,
            step_id="step_1",
            step_type="transform",
            status="pending",
            input_data={},
        )
        session.add(step1)
        await session.commit()
        await session.refresh(workflow)
        await session.refresh(execution)
        await session.refresh(step1)

    yield {
        "workflow": workflow,
        "execution": execution,
        "step_execution": step1,
        "api_key": api_key,
        "tenant_id": tenant_id,
    }

    async with test_session_factory() as session:
        await session.execute(
            delete(StepExecution).where(StepExecution.execution_id == execution.id)
        )
        await session.execute(delete(Execution).where(Execution.id == execution.id))
        await session.execute(delete(Workflow).where(Workflow.id == workflow.id))
        await session.commit()


class TestCancelExecution:
    """Tests for POST /api/executions/:id/cancel."""

    async def test_cancel_running_execution_returns_200(
        self, patched_app, running_execution
    ):
        """POST /api/executions/:id/cancel cancels a running execution."""
        api_key = running_execution["api_key"]
        exec_id = str(running_execution["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{exec_id}/cancel",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["cancelled"] is True

    async def test_cancel_already_completed_returns_409(
        self, patched_app, tenant_api_key, test_session_factory
    ):
        """Cannot cancel a completed execution."""
        api_key, tenant_id = tenant_api_key

        async with test_session_factory() as session:
            wf = Workflow(
                tenant_id=tenant_id,
                name="Done Flow",
                trigger_type="manual",
                trigger_config={},
                steps=_valid_steps(),
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
                resp = await client.post(
                    f"/api/executions/{ex.id}/cancel",
                    headers={"X-API-Key": api_key},
                )

            assert resp.status_code == 409
        finally:
            async with test_session_factory() as session:
                await session.execute(delete(Execution).where(Execution.id == ex.id))
                await session.execute(delete(Workflow).where(Workflow.id == wf.id))
                await session.commit()

    async def test_cancel_nonexistent_returns_404(self, patched_app, tenant_api_key):
        """POST /api/executions/:id/cancel for nonexistent execution returns 404."""
        api_key, _ = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{uuid.uuid4()}/cancel",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_cancel_requires_auth(self, patched_app):
        """POST /api/executions/:id/cancel without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{uuid.uuid4()}/cancel",
            )

        assert resp.status_code == 401

    async def test_cancel_cross_tenant_returns_404(
        self,
        patched_app,
        running_execution,
        second_tenant_api_key,
    ):
        """Tenant B cannot cancel Tenant A's execution."""
        api_key_b, _ = second_tenant_api_key
        exec_id = str(running_execution["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{exec_id}/cancel",
                headers={"X-API-Key": api_key_b},
            )

        assert resp.status_code == 404

    async def test_cancel_marks_pending_steps_skipped(
        self, patched_app, running_execution, test_session_factory
    ):
        """Cancelling execution marks pending steps as skipped."""
        api_key = running_execution["api_key"]
        exec_id = str(running_execution["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{exec_id}/cancel",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200

        # Verify steps are skipped
        async with test_session_factory() as session:
            from sqlalchemy import select

            stmt = select(StepExecution).where(
                StepExecution.execution_id == running_execution["execution"].id
            )
            result = await session.execute(stmt)
            steps = result.scalars().all()
            for step in steps:
                assert step.status == "skipped"
