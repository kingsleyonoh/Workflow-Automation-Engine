"""Unit tests for webhook trigger API endpoint.

Tests POST /webhooks/:path against real PostgreSQL via
httpx.AsyncClient with the FastAPI app.
"""

import hashlib
import hmac
import json
import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Execution, StepExecution, Tenant, WebhookDelivery, Workflow

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


def _compute_hmac(secret: str, payload: bytes) -> str:
    """Compute HMAC-SHA256 signature for a payload."""
    mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


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
    """FastAPI app with test DB and Redis for webhook tests."""
    with (
        patch(
            "src.api.middleware.auth.async_session_factory",
            test_session_factory,
        ),
        patch(
            "src.api.webhooks.async_session_factory",
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
async def webhook_workflow(test_session_factory):
    """Create a webhook-triggered workflow and return it."""
    import secrets

    import bcrypt

    async with test_session_factory() as session:
        api_key = f"wae_live_{secrets.token_hex(16)}"
        api_key_hash = bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()

        tenant = Tenant(
            name="Webhook Test Tenant",
            api_key_hash=api_key_hash,
            api_key_prefix=api_key[:17],
        )
        session.add(tenant)
        await session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="Webhook Flow",
            trigger_type="webhook",
            trigger_config={},
            steps=_valid_steps(),
            is_active=True,
            webhook_path="wh_test123",
        )
        session.add(workflow)
        await session.commit()
        await session.refresh(workflow)
        await session.refresh(tenant)

    yield {
        "workflow": workflow,
        "tenant": tenant,
        "api_key": api_key,
    }

    # Cleanup
    async with test_session_factory() as session:
        await session.execute(delete(WebhookDelivery))
        await session.execute(delete(StepExecution))
        await session.execute(delete(Execution))
        await session.execute(delete(Workflow).where(Workflow.id == workflow.id))
        await session.execute(delete(Tenant).where(Tenant.id == tenant.id))
        await session.commit()


@pytest.fixture
async def webhook_workflow_with_secret(test_session_factory):
    """Create a webhook workflow with HMAC secret."""
    import secrets

    import bcrypt

    async with test_session_factory() as session:
        api_key = f"wae_live_{secrets.token_hex(16)}"
        api_key_hash = bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()

        tenant = Tenant(
            name="HMAC Tenant",
            api_key_hash=api_key_hash,
            api_key_prefix=api_key[:17],
        )
        session.add(tenant)
        await session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="HMAC Flow",
            trigger_type="webhook",
            trigger_config={},
            steps=_valid_steps(),
            is_active=True,
            webhook_path="wh_hmac_test",
            webhook_secret="my_super_secret",
        )
        session.add(workflow)
        await session.commit()
        await session.refresh(workflow)
        await session.refresh(tenant)

    yield {
        "workflow": workflow,
        "tenant": tenant,
        "api_key": api_key,
    }

    async with test_session_factory() as session:
        await session.execute(delete(WebhookDelivery))
        await session.execute(delete(StepExecution))
        await session.execute(delete(Execution))
        await session.execute(delete(Workflow).where(Workflow.id == workflow.id))
        await session.execute(delete(Tenant).where(Tenant.id == tenant.id))
        await session.commit()


class TestWebhookReceive:
    """Tests for POST /webhooks/:path — happy path."""

    async def test_webhook_returns_202_with_execution_id(
        self, patched_app, webhook_workflow, test_session_factory
    ):
        """POST /webhooks/:path returns 202 with execution_id."""
        wf = webhook_workflow["workflow"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/webhooks/{wf.webhook_path}",
                json={"event": "push", "data": "test"},
            )

        assert resp.status_code == 202
        body = resp.json()
        assert "execution_id" in body

    async def test_webhook_logs_delivery(
        self, patched_app, webhook_workflow, test_session_factory
    ):
        """POST /webhooks/:path logs the delivery in webhook_deliveries."""
        wf = webhook_workflow["workflow"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            await client.post(
                f"/webhooks/{wf.webhook_path}",
                json={"event": "push"},
            )

        # Verify delivery was logged
        async with test_session_factory() as session:
            stmt = select(WebhookDelivery).where(WebhookDelivery.workflow_id == wf.id)
            result = await session.execute(stmt)
            delivery = result.scalar_one_or_none()

        assert delivery is not None
        assert delivery.status == "accepted"
        assert delivery.method == "POST"

    async def test_webhook_passes_payload_as_trigger_data(
        self, patched_app, webhook_workflow, test_session_factory
    ):
        """Webhook stores the payload in the execution trigger_data."""
        wf = webhook_workflow["workflow"]
        payload = {"event": "push", "ref": "main"}

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/webhooks/{wf.webhook_path}",
                json=payload,
            )

        assert resp.status_code == 202
        exec_id = resp.json()["execution_id"]

        # Verify execution has the payload as trigger_data
        async with test_session_factory() as session:
            stmt = select(Execution).where(Execution.id == exec_id)
            result = await session.execute(stmt)
            execution = result.scalar_one_or_none()

        assert execution is not None
        assert execution.trigger_data["payload"] == payload


class TestWebhookNotFound:
    """Tests for POST /webhooks/:path — workflow not found."""

    async def test_unknown_path_returns_404(self, patched_app):
        """POST /webhooks/:path with unknown path returns 404."""
        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/webhooks/nonexistent_path",
                json={"event": "push"},
            )

        assert resp.status_code == 404


class TestWebhookInactive:
    """Tests for POST /webhooks/:path — inactive workflow."""

    async def test_inactive_workflow_returns_404(
        self, patched_app, test_session_factory
    ):
        """POST /webhooks/:path for inactive workflow returns 404."""
        import secrets

        import bcrypt

        async with test_session_factory() as session:
            api_key = f"wae_live_{secrets.token_hex(16)}"
            api_key_hash = bcrypt.hashpw(api_key.encode(), bcrypt.gensalt()).decode()

            tenant = Tenant(
                name="Inactive Tenant",
                api_key_hash=api_key_hash,
                api_key_prefix=api_key[:17],
            )
            session.add(tenant)
            await session.flush()

            workflow = Workflow(
                tenant_id=tenant.id,
                name="Inactive Flow",
                trigger_type="webhook",
                trigger_config={},
                steps=_valid_steps(),
                is_active=False,
                webhook_path="wh_inactive",
            )
            session.add(workflow)
            await session.commit()

        try:
            async with AsyncClient(
                transport=ASGITransport(app=patched_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/webhooks/wh_inactive",
                    json={"event": "push"},
                )

            assert resp.status_code == 404
        finally:
            async with test_session_factory() as session:
                await session.execute(delete(WebhookDelivery))
                await session.execute(
                    delete(Workflow).where(Workflow.id == workflow.id)
                )
                await session.execute(delete(Tenant).where(Tenant.id == tenant.id))
                await session.commit()


class TestWebhookHMAC:
    """Tests for HMAC-SHA256 signature validation."""

    async def test_valid_hmac_accepted(
        self,
        patched_app,
        webhook_workflow_with_secret,
        test_session_factory,
    ):
        """Valid HMAC signature is accepted, returns 202."""
        wf = webhook_workflow_with_secret["workflow"]

        payload = json.dumps({"event": "push"}).encode()
        signature = _compute_hmac("my_super_secret", payload)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/webhooks/{wf.webhook_path}",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": signature,
                },
            )

        assert resp.status_code == 202

    async def test_invalid_hmac_returns_401(
        self, patched_app, webhook_workflow_with_secret, test_session_factory
    ):
        """Invalid HMAC signature returns 401."""
        wf = webhook_workflow_with_secret["workflow"]

        payload = json.dumps({"event": "push"}).encode()
        bad_signature = "sha256=invalid_signature"

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/webhooks/{wf.webhook_path}",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": bad_signature,
                },
            )

        assert resp.status_code == 401

    async def test_missing_hmac_when_required_returns_401(
        self, patched_app, webhook_workflow_with_secret, test_session_factory
    ):
        """Missing signature when secret is set returns 401."""
        wf = webhook_workflow_with_secret["workflow"]

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/webhooks/{wf.webhook_path}",
                json={"event": "push"},
            )

        assert resp.status_code == 401

    async def test_hmac_rejection_logs_delivery(
        self, patched_app, webhook_workflow_with_secret, test_session_factory
    ):
        """Invalid HMAC logs delivery with 'rejected' status."""
        wf = webhook_workflow_with_secret["workflow"]

        payload = json.dumps({"event": "push"}).encode()

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            await client.post(
                f"/webhooks/{wf.webhook_path}",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": "sha256=bad",
                },
            )

        async with test_session_factory() as session:
            stmt = select(WebhookDelivery).where(WebhookDelivery.workflow_id == wf.id)
            result = await session.execute(stmt)
            delivery = result.scalar_one_or_none()

        assert delivery is not None
        assert delivery.status == "rejected"


class TestWebhookPayloadSize:
    """Tests for payload size limits."""

    async def test_oversized_payload_returns_413(self, patched_app):
        """Payload exceeding MAX_PAYLOAD_SIZE returns 413."""
        # Default MAX_PAYLOAD_SIZE is 1MB; send >1MB
        large_payload = "x" * (1_048_576 + 1)

        async with AsyncClient(
            transport=ASGITransport(app=patched_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/webhooks/wh_test123",
                content=large_payload.encode(),
                headers={"Content-Type": "application/json"},
            )

        assert resp.status_code == 413
