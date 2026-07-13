"""DB-backed regression test for HTTP retry exhaustion."""

import pytest
import respx
from httpx import Response
from sqlalchemy import select

from src.db.models import StepExecution, Tenant, Workflow
from src.engine.orchestrator import start_execution

pytestmark = pytest.mark.integration

MAX_ATTEMPTS = 3
PROTECTED_URL = "https://api.external.test/protected"
HTTP_STEPS = [
    {
        "id": "protected_request",
        "type": "http",
        "config": {"url": PROTECTED_URL, "method": "GET"},
        "retry": {"max_attempts": MAX_ATTEMPTS, "delay_seconds": 0},
    }
]


class TestHttpExecutionRetryExhaustion:
    """HTTP failures must fail both the persisted step and execution."""

    async def test_unauthorized_response_exhausts_attempts_and_fails_execution(
        self, db_session
    ):
        """A persistent 401 exhausts retries instead of completing the workflow."""
        tenant = Tenant(
            name="HTTP Retry Regression Tenant",
            api_key_hash="hash_placeholder",
            api_key_prefix="wae_live_http_retry_regression",
        )
        db_session.add(tenant)
        await db_session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="HTTP 401 Retry Regression",
            trigger_type="manual",
            steps=HTTP_STEPS,
            is_active=True,
        )
        db_session.add(workflow)
        await db_session.flush()

        with respx.mock:
            route = respx.get(PROTECTED_URL).mock(
                return_value=Response(401, json={"error": "unauthorized"})
            )
            execution = await start_execution(
                db_session, workflow, {"payload": {}}, tenant.id
            )

        step_result = await db_session.execute(
            select(StepExecution).where(
                StepExecution.execution_id == execution.id,
                StepExecution.step_id == "protected_request",
            )
        )
        step_execution = step_result.scalar_one()
        await db_session.refresh(execution)

        assert route.call_count == MAX_ATTEMPTS
        assert step_execution.status == "failed"
        assert step_execution.attempt == MAX_ATTEMPTS
        assert step_execution.max_attempts == MAX_ATTEMPTS
        assert "401" in step_execution.error
        assert execution.status == "failed"
        assert execution.status != "completed"
