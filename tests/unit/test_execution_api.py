"""Unit tests for execution API endpoints.

Tests POST /api/workflows/:id/execute, GET /api/executions,
GET /api/executions/:id against real PostgreSQL via
httpx.AsyncClient with the FastAPI app.
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
    """Return a minimal valid steps array for workflow creation."""
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
    """FastAPI app with test DB and Redis for execution tests."""
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
        result = await register_tenant(name="Exec Test Tenant", session=session)
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
        result = await register_tenant(name="Other Exec Tenant", session=session)
        await session.commit()

    yield result.api_key, result.id

    async with test_session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == result.id))
        await session.commit()


@pytest.fixture
async def workflow_with_execution(test_session_factory, tenant_api_key):
    """Create a workflow with a completed execution and step executions."""
    api_key, tenant_id = tenant_api_key

    async with test_session_factory() as session:
        workflow = Workflow(
            tenant_id=tenant_id,
            name="Test Flow",
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
            trigger_data={"source": "test"},
            context={"trigger": {"source": "test"}, "steps": {}},
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
        await session.refresh(step_exec)

    yield {
        "workflow": workflow,
        "execution": execution,
        "step_execution": step_exec,
        "api_key": api_key,
        "tenant_id": tenant_id,
    }

    async with test_session_factory() as session:
        await session.execute(
            delete(StepExecution).where(StepExecution.id == step_exec.id)
        )
        await session.execute(delete(Execution).where(Execution.id == execution.id))
        await session.execute(delete(Workflow).where(Workflow.id == workflow.id))
        await session.commit()


class TestManualExecute:
    """Tests for POST /api/workflows/:id/execute — manual trigger."""

    @patch("src.api.executions.start_execution", new_callable=AsyncMock)
    async def test_manual_execute_returns_202(
        self, mock_start, patched_app, tenant_api_key, test_session_factory
    ):
        """POST /api/workflows/:id/execute returns 202 with execution_id."""
        api_key, tenant_id = tenant_api_key

        # Create a workflow
        async with test_session_factory() as session:
            workflow = Workflow(
                tenant_id=tenant_id,
                name="Manual Flow",
                trigger_type="manual",
                trigger_config={},
                steps=_valid_steps(),
                is_active=True,
            )
            session.add(workflow)
            await session.commit()
            await session.refresh(workflow)

        mock_exec = AsyncMock()
        mock_exec.id = uuid.uuid4()
        mock_start.return_value = mock_exec

        try:
            async with AsyncClient(
                transport=ASGITransport(app=patched_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/workflows/{workflow.id}/execute",
                    json={"trigger_data": {"source": "manual"}},
                    headers={"X-API-Key": api_key},
                )

            assert resp.status_code == 202
            body = resp.json()
            assert "execution_id" in body
        finally:
            async with test_session_factory() as session:
                await session.execute(
                    delete(Workflow).where(Workflow.id == workflow.id)
                )
                await session.commit()

    @patch("src.api.executions.start_execution", new_callable=AsyncMock)
    async def test_manual_execute_without_trigger_data(
        self, mock_start, patched_app, tenant_api_key, test_session_factory
    ):
        """POST /api/workflows/:id/execute without trigger_data succeeds."""
        api_key, tenant_id = tenant_api_key

        async with test_session_factory() as session:
            workflow = Workflow(
                tenant_id=tenant_id,
                name="No Data Flow",
                trigger_type="manual",
                trigger_config={},
                steps=_valid_steps(),
                is_active=True,
            )
            session.add(workflow)
            await session.commit()
            await session.refresh(workflow)

        mock_exec = AsyncMock()
        mock_exec.id = uuid.uuid4()
        mock_start.return_value = mock_exec

        try:
            async with AsyncClient(
                transport=ASGITransport(app=patched_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/workflows/{workflow.id}/execute",
                    json={},
                    headers={"X-API-Key": api_key},
                )

            assert resp.status_code == 202
        finally:
            async with test_session_factory() as session:
                await session.execute(
                    delete(Workflow).where(Workflow.id == workflow.id)
                )
                await session.commit()

    async def test_manual_execute_nonexistent_workflow_returns_404(
        self, patched_app, tenant_api_key
    ):
        """POST /api/workflows/:id/execute for nonexistent workflow returns 404."""
        api_key, _ = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/workflows/{uuid.uuid4()}/execute",
                json={},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_manual_execute_requires_auth(self, patched_app):
        """POST /api/workflows/:id/execute without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/api/workflows/{uuid.uuid4()}/execute",
                json={},
            )

        assert resp.status_code == 401

    @patch("src.api.executions.start_execution", new_callable=AsyncMock)
    async def test_manual_execute_inactive_workflow_returns_400(
        self, mock_start, patched_app, tenant_api_key, test_session_factory
    ):
        """POST /api/workflows/:id/execute for inactive workflow returns 400."""
        api_key, tenant_id = tenant_api_key

        async with test_session_factory() as session:
            workflow = Workflow(
                tenant_id=tenant_id,
                name="Inactive Flow",
                trigger_type="manual",
                trigger_config={},
                steps=_valid_steps(),
                is_active=False,
            )
            session.add(workflow)
            await session.commit()
            await session.refresh(workflow)

        try:
            async with AsyncClient(
                transport=ASGITransport(app=patched_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/workflows/{workflow.id}/execute",
                    json={},
                    headers={"X-API-Key": api_key},
                )

            assert resp.status_code == 400
        finally:
            async with test_session_factory() as session:
                await session.execute(
                    delete(Workflow).where(Workflow.id == workflow.id)
                )
                await session.commit()

    async def test_manual_execute_cross_tenant_returns_404(
        self,
        patched_app,
        tenant_api_key,
        second_tenant_api_key,
        test_session_factory,
    ):
        """Cannot execute another tenant's workflow."""
        api_key_a, tenant_a_id = tenant_api_key
        api_key_b, _ = second_tenant_api_key

        async with test_session_factory() as session:
            workflow = Workflow(
                tenant_id=tenant_a_id,
                name="Tenant A Flow",
                trigger_type="manual",
                trigger_config={},
                steps=_valid_steps(),
                is_active=True,
            )
            session.add(workflow)
            await session.commit()
            await session.refresh(workflow)

        try:
            async with AsyncClient(
                transport=ASGITransport(app=patched_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    f"/api/workflows/{workflow.id}/execute",
                    json={},
                    headers={"X-API-Key": api_key_b},
                )

            assert resp.status_code == 404
        finally:
            async with test_session_factory() as session:
                await session.execute(
                    delete(Workflow).where(Workflow.id == workflow.id)
                )
                await session.commit()


class TestListExecutions:
    """Tests for GET /api/executions — list executions."""

    async def test_list_executions_returns_200(
        self, patched_app, workflow_with_execution
    ):
        """GET /api/executions returns 200 with executions array."""
        api_key = workflow_with_execution["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/executions",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "executions" in body
        assert len(body["executions"]) >= 1

    async def test_list_executions_filter_by_status(
        self, patched_app, workflow_with_execution
    ):
        """GET /api/executions?status=completed filters by status."""
        api_key = workflow_with_execution["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/executions?status=completed",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        for ex in body["executions"]:
            assert ex["status"] == "completed"

    async def test_list_executions_filter_by_workflow_id(
        self, patched_app, workflow_with_execution
    ):
        """GET /api/executions?workflow_id=... filters by workflow."""
        api_key = workflow_with_execution["api_key"]
        wf_id = str(workflow_with_execution["workflow"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions?workflow_id={wf_id}",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        for ex in body["executions"]:
            assert ex["workflow_id"] == wf_id

    async def test_list_executions_pagination(
        self, patched_app, workflow_with_execution, test_session_factory
    ):
        """GET /api/executions with limit returns correct page size."""
        api_key = workflow_with_execution["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/executions?limit=1",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["executions"]) <= 1

    async def test_list_executions_requires_auth(self, patched_app):
        """GET /api/executions without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/executions")

        assert resp.status_code == 401

    async def test_list_executions_tenant_isolation(
        self,
        patched_app,
        workflow_with_execution,
        second_tenant_api_key,
    ):
        """Tenant B cannot see Tenant A's executions."""
        api_key_b, _ = second_tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/executions",
                headers={"X-API-Key": api_key_b},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["executions"]) == 0


class TestGetExecution:
    """Tests for GET /api/executions/:id — get execution detail."""

    async def test_get_execution_returns_200(
        self, patched_app, workflow_with_execution
    ):
        """GET /api/executions/:id returns 200 with execution and steps."""
        api_key = workflow_with_execution["api_key"]
        exec_id = str(workflow_with_execution["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{exec_id}",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "execution" in body
        assert "steps" in body
        assert body["execution"]["id"] == exec_id
        assert len(body["steps"]) >= 1

    async def test_get_execution_not_found(self, patched_app, tenant_api_key):
        """GET /api/executions/:id for nonexistent execution returns 404."""
        api_key, _ = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{uuid.uuid4()}",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_get_execution_requires_auth(self, patched_app):
        """GET /api/executions/:id without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/executions/{uuid.uuid4()}")

        assert resp.status_code == 401

    async def test_get_execution_cross_tenant_returns_404(
        self,
        patched_app,
        workflow_with_execution,
        second_tenant_api_key,
    ):
        """Tenant B cannot see Tenant A's execution."""
        api_key_b, _ = second_tenant_api_key
        exec_id = str(workflow_with_execution["execution"].id)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/executions/{exec_id}",
                headers={"X-API-Key": api_key_b},
            )

        assert resp.status_code == 404
