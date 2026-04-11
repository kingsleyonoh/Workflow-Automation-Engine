"""Unit tests for workflow CRUD API endpoints.

Tests POST/GET/PUT /api/workflows against real PostgreSQL via
httpx.AsyncClient with the FastAPI app.
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


def _valid_steps() -> list[dict]:
    """Return a minimal valid steps array for workflow creation."""
    return [
        {
            "id": "step_1",
            "type": "http",
            "config": {"url": "https://example.com/api"},
        }
    ]


def _multi_step_workflow() -> list[dict]:
    """Return a multi-step workflow with dependencies."""
    return [
        {
            "id": "fetch",
            "type": "http",
            "config": {"url": "https://api.example.com/data"},
        },
        {
            "id": "transform",
            "type": "transform",
            "config": {"expression": "{{ steps.fetch.output.body }}"},
            "depends_on": ["fetch"],
        },
        {
            "id": "notify",
            "type": "http",
            "config": {"url": "https://hooks.example.com/notify"},
            "depends_on": ["transform"],
        },
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
    """FastAPI app with test DB and Redis for workflow CRUD tests."""
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
            "src.api.workflows.async_session_factory",
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
    """Create a test tenant and return its API key for authenticated requests."""
    from src.tenants.service import register_tenant

    async with test_session_factory() as session:
        result = await register_tenant(name="Workflow Test Tenant", session=session)
        await session.commit()

    yield result.api_key, result.id

    # Cleanup: delete tenant (cascades to workflows)
    from src.db.models import Tenant

    async with test_session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == result.id))
        await session.commit()


@pytest.fixture
async def second_tenant_api_key(test_session_factory):
    """Create a second tenant for cross-tenant isolation tests."""
    from src.tenants.service import register_tenant

    async with test_session_factory() as session:
        result = await register_tenant(name="Other Tenant", session=session)
        await session.commit()

    yield result.api_key, result.id

    from src.db.models import Tenant

    async with test_session_factory() as session:
        await session.execute(delete(Tenant).where(Tenant.id == result.id))
        await session.commit()


class TestCreateWorkflow:
    """Tests for POST /api/workflows."""

    async def test_create_webhook_workflow(self, patched_app, tenant_api_key):
        """POST /api/workflows with webhook trigger returns 201 with webhook_path."""
        api_key, tenant_id = tenant_api_key
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Webhook Flow",
                    "trigger_type": "webhook",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Webhook Flow"
        assert body["trigger_type"] == "webhook"
        assert body["webhook_path"] is not None
        assert body["webhook_path"].startswith("wh_")
        assert body["is_active"] is True
        assert "id" in body
        assert "steps" in body

    async def test_create_cron_workflow(self, patched_app, tenant_api_key):
        """POST /api/workflows with cron trigger returns 201, no webhook_path."""
        api_key, tenant_id = tenant_api_key
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Cron Flow",
                    "trigger_type": "cron",
                    "trigger_config": {"schedule": "0 * * * *"},
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["trigger_type"] == "cron"
        assert body["webhook_path"] is None

    async def test_create_manual_workflow(self, patched_app, tenant_api_key):
        """POST /api/workflows with manual trigger returns 201."""
        api_key, tenant_id = tenant_api_key
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Manual Flow",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert body["trigger_type"] == "manual"
        assert body["webhook_path"] is None

    async def test_create_with_description(self, patched_app, tenant_api_key):
        """POST /api/workflows with description includes it in response."""
        api_key, tenant_id = tenant_api_key
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Described Flow",
                    "description": "A detailed description",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 201
        assert resp.json()["description"] == "A detailed description"

    async def test_create_with_multi_step_dependencies(
        self, patched_app, tenant_api_key
    ):
        """POST /api/workflows with multi-step dependencies returns 201."""
        api_key, tenant_id = tenant_api_key
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Multi Step",
                    "trigger_type": "webhook",
                    "steps": _multi_step_workflow(),
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 201
        body = resp.json()
        assert len(body["steps"]) == 3

    async def test_create_with_cycle_returns_400(self, patched_app, tenant_api_key):
        """POST /api/workflows with cyclic steps returns 400 CYCLE_DETECTED."""
        api_key, tenant_id = tenant_api_key
        cyclic_steps = [
            {
                "id": "a",
                "type": "http",
                "config": {"url": "https://x.com"},
                "depends_on": ["b"],
            },
            {
                "id": "b",
                "type": "http",
                "config": {"url": "https://x.com"},
                "depends_on": ["a"],
            },
        ]
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Cyclic Flow",
                    "trigger_type": "manual",
                    "steps": cyclic_steps,
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "CYCLE_DETECTED"

    async def test_create_missing_name_returns_422(self, patched_app, tenant_api_key):
        """POST /api/workflows without name returns 422."""
        api_key, tenant_id = tenant_api_key
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 422

    async def test_create_no_auth_returns_401(self, patched_app):
        """POST /api/workflows without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "name": "No Auth",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
            )

        assert resp.status_code == 401

    async def test_create_is_active_defaults_true(self, patched_app, tenant_api_key):
        """Workflow is_active defaults to True when not specified."""
        api_key, tenant_id = tenant_api_key
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Default Active",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 201
        assert resp.json()["is_active"] is True

    async def test_create_is_active_false(self, patched_app, tenant_api_key):
        """Workflow can be created with is_active=False."""
        api_key, tenant_id = tenant_api_key
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Inactive Flow",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                    "is_active": False,
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 201
        assert resp.json()["is_active"] is False


class TestListWorkflows:
    """Tests for GET /api/workflows."""

    async def test_list_returns_empty_for_new_tenant(self, patched_app, tenant_api_key):
        """GET /api/workflows for a new tenant returns empty list."""
        api_key, tenant_id = tenant_api_key
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/workflows",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["workflows"] == []
        assert body["cursor"] is None

    async def test_list_returns_own_workflows_only(
        self, patched_app, tenant_api_key, second_tenant_api_key
    ):
        """GET /api/workflows returns only the authenticated tenant's workflows."""
        api_key, tenant_id = tenant_api_key
        other_key, other_id = second_tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            # Create workflow as tenant 1
            await client.post(
                "/api/workflows",
                json={
                    "name": "T1 Flow",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )
            # Create workflow as tenant 2
            await client.post(
                "/api/workflows",
                json={
                    "name": "T2 Flow",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": other_key},
            )

            # List as tenant 1 — should only see T1 Flow
            resp = await client.get(
                "/api/workflows",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        names = [w["name"] for w in body["workflows"]]
        assert "T1 Flow" in names
        assert "T2 Flow" not in names

    async def test_list_pagination_limit(self, patched_app, tenant_api_key):
        """GET /api/workflows respects limit parameter."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            # Create 3 workflows
            for i in range(3):
                await client.post(
                    "/api/workflows",
                    json={
                        "name": f"Flow {i}",
                        "trigger_type": "manual",
                        "steps": _valid_steps(),
                    },
                    headers={"X-API-Key": api_key},
                )

            resp = await client.get(
                "/api/workflows",
                params={"limit": 2},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["workflows"]) == 2
        assert body["cursor"] is not None

    async def test_list_pagination_cursor(self, patched_app, tenant_api_key):
        """GET /api/workflows with cursor returns next page."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            # Create 3 workflows
            for i in range(3):
                await client.post(
                    "/api/workflows",
                    json={
                        "name": f"Page Flow {i}",
                        "trigger_type": "manual",
                        "steps": _valid_steps(),
                    },
                    headers={"X-API-Key": api_key},
                )

            # Get first page
            resp1 = await client.get(
                "/api/workflows",
                params={"limit": 2},
                headers={"X-API-Key": api_key},
            )
            cursor = resp1.json()["cursor"]

            # Get second page
            resp2 = await client.get(
                "/api/workflows",
                params={"limit": 2, "cursor": cursor},
                headers={"X-API-Key": api_key},
            )

        body2 = resp2.json()
        assert resp2.status_code == 200
        assert len(body2["workflows"]) >= 1
        # Should not overlap with first page
        page1_ids = {w["id"] for w in resp1.json()["workflows"]}
        page2_ids = {w["id"] for w in body2["workflows"]}
        assert page1_ids.isdisjoint(page2_ids)

    async def test_list_filter_by_trigger_type(self, patched_app, tenant_api_key):
        """GET /api/workflows?trigger_type=webhook filters results."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/workflows",
                json={
                    "name": "WH Flow",
                    "trigger_type": "webhook",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )
            await client.post(
                "/api/workflows",
                json={
                    "name": "Manual Flow",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )

            resp = await client.get(
                "/api/workflows",
                params={"trigger_type": "webhook"},
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        assert resp.status_code == 200
        for w in body["workflows"]:
            assert w["trigger_type"] == "webhook"

    async def test_list_filter_by_is_active(self, patched_app, tenant_api_key):
        """GET /api/workflows?is_active=false filters results."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/workflows",
                json={
                    "name": "Active",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )
            await client.post(
                "/api/workflows",
                json={
                    "name": "Inactive",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                    "is_active": False,
                },
                headers={"X-API-Key": api_key},
            )

            resp = await client.get(
                "/api/workflows",
                params={"is_active": "false"},
                headers={"X-API-Key": api_key},
            )

        body = resp.json()
        assert resp.status_code == 200
        for w in body["workflows"]:
            assert w["is_active"] is False

    async def test_list_no_auth_returns_401(self, patched_app):
        """GET /api/workflows without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/workflows")

        assert resp.status_code == 401


class TestGetWorkflow:
    """Tests for GET /api/workflows/:id."""

    async def test_get_existing_workflow(self, patched_app, tenant_api_key):
        """GET /api/workflows/:id returns the workflow."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            create_resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Get Me",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )
            wf_id = create_resp.json()["id"]

            resp = await client.get(
                f"/api/workflows/{wf_id}",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == wf_id
        assert body["name"] == "Get Me"
        assert "steps" in body
        assert "created_at" in body

    async def test_get_not_found_returns_404(self, patched_app, tenant_api_key):
        """GET /api/workflows/:id with non-existent ID returns 404."""
        api_key, tenant_id = tenant_api_key
        fake_id = "00000000-0000-0000-0000-000000000000"

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                f"/api/workflows/{fake_id}",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_get_other_tenant_workflow_returns_404(
        self, patched_app, tenant_api_key, second_tenant_api_key
    ):
        """GET /api/workflows/:id for another tenant's workflow returns 404."""
        api_key, tenant_id = tenant_api_key
        other_key, other_id = second_tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            # Create workflow as tenant 2
            create_resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Other Flow",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": other_key},
            )
            wf_id = create_resp.json()["id"]

            # Try to get it as tenant 1
            resp = await client.get(
                f"/api/workflows/{wf_id}",
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_get_no_auth_returns_401(self, patched_app):
        """GET /api/workflows/:id without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/workflows/00000000-0000-0000-0000-000000000000"
            )

        assert resp.status_code == 401


class TestUpdateWorkflow:
    """Tests for PUT /api/workflows/:id."""

    async def test_update_name(self, patched_app, tenant_api_key):
        """PUT /api/workflows/:id can update the workflow name."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            create_resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Original",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )
            wf_id = create_resp.json()["id"]

            resp = await client.put(
                f"/api/workflows/{wf_id}",
                json={"name": "Updated"},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"

    async def test_update_steps_revalidates(self, patched_app, tenant_api_key):
        """PUT /api/workflows/:id with new steps re-validates them."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            create_resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Revalidate",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )
            wf_id = create_resp.json()["id"]

            resp = await client.put(
                f"/api/workflows/{wf_id}",
                json={"steps": _multi_step_workflow()},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        assert len(resp.json()["steps"]) == 3

    async def test_update_steps_with_cycle_returns_400(
        self, patched_app, tenant_api_key
    ):
        """PUT /api/workflows/:id with cyclic steps returns 400."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            create_resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Will Cycle",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )
            wf_id = create_resp.json()["id"]

            cyclic_steps = [
                {
                    "id": "a",
                    "type": "http",
                    "config": {"url": "https://x.com"},
                    "depends_on": ["b"],
                },
                {
                    "id": "b",
                    "type": "http",
                    "config": {"url": "https://x.com"},
                    "depends_on": ["a"],
                },
            ]
            resp = await client.put(
                f"/api/workflows/{wf_id}",
                json={"steps": cyclic_steps},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "CYCLE_DETECTED"

    async def test_update_trigger_type_to_webhook_generates_path(
        self, patched_app, tenant_api_key
    ):
        """Changing trigger_type to webhook auto-generates webhook_path."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            create_resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Was Manual",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )
            wf_id = create_resp.json()["id"]
            assert create_resp.json()["webhook_path"] is None

            resp = await client.put(
                f"/api/workflows/{wf_id}",
                json={"trigger_type": "webhook"},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        assert resp.json()["webhook_path"] is not None
        assert resp.json()["webhook_path"].startswith("wh_")

    async def test_update_not_found_returns_404(self, patched_app, tenant_api_key):
        """PUT /api/workflows/:id with non-existent ID returns 404."""
        api_key, tenant_id = tenant_api_key
        fake_id = "00000000-0000-0000-0000-000000000000"

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.put(
                f"/api/workflows/{fake_id}",
                json={"name": "Ghost"},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_update_other_tenant_returns_404(
        self, patched_app, tenant_api_key, second_tenant_api_key
    ):
        """PUT /api/workflows/:id for another tenant's workflow returns 404."""
        api_key, tenant_id = tenant_api_key
        other_key, other_id = second_tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            # Create as tenant 2
            create_resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Other WF",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": other_key},
            )
            wf_id = create_resp.json()["id"]

            # Try to update as tenant 1
            resp = await client.put(
                f"/api/workflows/{wf_id}",
                json={"name": "Stolen"},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 404

    async def test_update_is_active(self, patched_app, tenant_api_key):
        """PUT /api/workflows/:id can toggle is_active."""
        api_key, tenant_id = tenant_api_key

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            create_resp = await client.post(
                "/api/workflows",
                json={
                    "name": "Toggle",
                    "trigger_type": "manual",
                    "steps": _valid_steps(),
                },
                headers={"X-API-Key": api_key},
            )
            wf_id = create_resp.json()["id"]

            resp = await client.put(
                f"/api/workflows/{wf_id}",
                json={"is_active": False},
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    async def test_update_no_auth_returns_401(self, patched_app):
        """PUT /api/workflows/:id without API key returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.put(
                "/api/workflows/00000000-0000-0000-0000-000000000000",
                json={"name": "No Auth"},
            )

        assert resp.status_code == 401
