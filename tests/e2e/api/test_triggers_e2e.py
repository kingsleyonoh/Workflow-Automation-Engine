"""E2E tests for webhook and execution API endpoints.

Hits a running server over HTTP to validate the webhook receiver,
manual execution trigger, and execution listing endpoints.
"""

import httpx
import pytest

pytestmark = pytest.mark.e2e

# Generous timeout for E2E tests hitting real DB
REQUEST_TIMEOUT = 60


@pytest.fixture(scope="module")
def api_key(running_server):
    """Register a tenant and return its API key for E2E tests."""
    resp = httpx.post(
        f"{running_server}/api/tenants/register",
        json={"name": "E2E Trigger Tenant"},
        timeout=REQUEST_TIMEOUT,
    )
    assert resp.status_code == 201
    data = resp.json()
    yield data["api_key"]


@pytest.fixture(scope="module")
def webhook_workflow(running_server, api_key):
    """Create a webhook-triggered workflow."""
    resp = httpx.post(
        f"{running_server}/api/workflows",
        json={
            "name": "E2E Webhook Flow",
            "trigger_type": "webhook",
            "steps": [
                {
                    "id": "step_1",
                    "type": "transform",
                    "config": {"expression": "{{ trigger.payload }}"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture(scope="module")
def manual_workflow(running_server, api_key):
    """Create a manual-triggered workflow."""
    resp = httpx.post(
        f"{running_server}/api/workflows",
        json={
            "name": "E2E Manual Flow",
            "trigger_type": "manual",
            "steps": [
                {
                    "id": "step_1",
                    "type": "transform",
                    "config": {"expression": "{{ trigger.data }}"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    assert resp.status_code == 201
    return resp.json()


class TestWebhookE2E:
    """E2E tests for POST /webhooks/:path."""

    def test_webhook_returns_202(self, running_server, webhook_workflow):
        """POST /webhooks/:path returns 202 with execution_id."""
        path = webhook_workflow["webhook_path"]
        resp = httpx.post(
            f"{running_server}/webhooks/{path}",
            json={"event": "push"},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "execution_id" in body

    def test_webhook_unknown_path_returns_404(self, running_server):
        """POST /webhooks/:path with unknown path returns 404."""
        resp = httpx.post(
            f"{running_server}/webhooks/nonexistent_path",
            json={"event": "push"},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 404


class TestManualExecuteAndQueryE2E:
    """E2E tests for manual execute, list executions, and get detail."""

    def test_manual_execute_and_query_flow(
        self, running_server, api_key, manual_workflow
    ):
        """Full flow: execute manually, list executions, get detail."""
        wf_id = manual_workflow["id"]

        # Step 1: Manual execute returns 202
        resp = httpx.post(
            f"{running_server}/api/workflows/{wf_id}/execute",
            json={"trigger_data": {"source": "e2e"}},
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "execution_id" in body
        exec_id = body["execution_id"]

        # Step 2: List executions shows at least 1
        resp = httpx.get(
            f"{running_server}/api/executions",
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "executions" in body
        assert len(body["executions"]) >= 1

        # Step 3: Get execution detail includes steps
        resp = httpx.get(
            f"{running_server}/api/executions/{exec_id}",
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "execution" in body
        assert "steps" in body
        assert body["execution"]["id"] == exec_id

    def test_manual_execute_no_auth_returns_401(
        self, running_server, manual_workflow
    ):
        """Manual execution without API key returns 401."""
        wf_id = manual_workflow["id"]
        resp = httpx.post(
            f"{running_server}/api/workflows/{wf_id}/execute",
            json={},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 401
