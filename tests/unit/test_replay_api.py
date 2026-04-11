"""Unit tests for POST /api/executions/:id/replay endpoint.

Tests replay execution with auth, tenant isolation, config guard,
override data merging, and replayed_from linkage.
"""

import os
import uuid
from unittest.mock import AsyncMock, patch

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
    """FastAPI app with test DB and Redis for replay tests."""
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
        result = await register_tenant(name="Replay Test Tenant", session=session)
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
        result = await register_tenant(name="Other Replay Tenant", session=session)
        await session.commit()

    yield result.api_key, result.id

    async with test_session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == result.id))
        await session.commit()


@pytest.fixture
async def completed_execution(test_session_factory, tenant_api_key):
    """Create a workflow with a completed execution for replay testing."""
    api_key, tenant_id = tenant_api_key

    async with test_session_factory() as session:
        workflow = Workflow(
            tenant_id=tenant_id,
            name="Replay Flow",
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
            status="completed",
            trigger_data={"source": "manual", "data": {"key": "original"}},
            context={
                "trigger": {"source": "manual", "data": {"key": "original"}},
                "steps": {},
            },
        )
        session.add(execution)
        await session.flush()

        step_exec = StepExecution(
            tenant_id=tenant_id,
            execution_id=execution.id,
            step_id="step_1",
            step_type="transform",
            status="completed",
            input_data={},
            output_data={"result": "done"},
        )
        session.add(step_exec)
        await session.commit()
        await session.refresh(workflow)
        await session.refresh(execution)

    yield {
        "workflow": workflow,
        "execution": execution,
        "api_key": api_key,
        "tenant_id": tenant_id,
    }

    async with test_session_factory() as session:
        await session.execute(
            delete(StepExecution).where(StepExecution.execution_id == execution.id)
        )
        # Delete any replayed executions too
        await session.execute(
            delete(Execution).where(Execution.replayed_from == execution.id)
        )
        await session.execute(delete(Execution).where(Execution.id == execution.id))
        await session.execute(delete(Workflow).where(Workflow.id == workflow.id))
        await session.commit()


class TestReplayExecution:
    """Tests for POST /api/executions/:id/replay."""

    @patch("src.replay.service.start_execution", new_callable=AsyncMock)
    async def test_replay_returns_202(
        self, mock_start, patched_app, completed_execution
    ):
        """POST /api/executions/:id/replay returns 202 with execution_id."""
        api_key = completed_execution["api_key"]
        exec_id = str(completed_execution["execution"].id)

        mock_exec = AsyncMock()
        mock_exec.id = uuid.uuid4()
        mock_start.return_value = mock_exec

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{exec_id}/replay",
                json={},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert "execution_id" in body

    @patch("src.replay.service.start_execution", new_callable=AsyncMock)
    async def test_replay_with_override_data(
        self, mock_start, patched_app, completed_execution
    ):
        """POST /api/executions/:id/replay merges override_data."""
        api_key = completed_execution["api_key"]
        exec_id = str(completed_execution["execution"].id)

        mock_exec = AsyncMock()
        mock_exec.id = uuid.uuid4()
        mock_start.return_value = mock_exec

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{exec_id}/replay",
                json={"override_data": {"key": "overridden"}},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 202
        # Verify start_execution was called with merged trigger data
        assert mock_start.called
        call_kwargs = mock_start.call_args.kwargs
        trigger = call_kwargs["trigger_data"]
        assert trigger["data"]["key"] == "overridden"

    async def test_replay_nonexistent_returns_404(self, patched_app, tenant_api_key):
        """POST /api/executions/:id/replay for nonexistent returns 404."""
        api_key, _ = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{uuid.uuid4()}/replay",
                json={},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_replay_requires_auth(self, patched_app):
        """POST /api/executions/:id/replay without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{uuid.uuid4()}/replay",
                json={},
            )

        assert resp.status_code == 401

    async def test_replay_cross_tenant_returns_404(
        self,
        patched_app,
        completed_execution,
        second_tenant_api_key,
    ):
        """Tenant B cannot replay Tenant A's execution."""
        api_key_b, _ = second_tenant_api_key
        exec_id = str(completed_execution["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{exec_id}/replay",
                json={},
                headers={"X-API-Key": api_key_b},
            )

        assert resp.status_code == 404

    @patch("src.api.executions.settings")
    async def test_replay_disabled_returns_403(
        self, mock_settings, patched_app, completed_execution
    ):
        """Replay returns 403 when WEBHOOK_REPLAY_ENABLED is false."""
        api_key = completed_execution["api_key"]
        exec_id = str(completed_execution["execution"].id)

        mock_settings.webhook_replay_enabled = False

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/executions/{exec_id}/replay",
                json={},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "REPLAY_DISABLED"
