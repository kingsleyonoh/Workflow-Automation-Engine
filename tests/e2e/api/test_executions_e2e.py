"""E2E tests for execution cancel, logs, and SSE stream endpoints.

Hits a running server over HTTP to validate the new execution
API endpoints added in batch 009.
"""

import httpx
import pytest

pytestmark = pytest.mark.e2e

REQUEST_TIMEOUT = 60


@pytest.fixture(scope="module")
def api_key(running_server):
    """Register a tenant and return its API key for E2E tests."""
    resp = httpx.post(
        f"{running_server}/api/tenants/register",
        json={"name": "E2E Exec Tenant"},
        timeout=REQUEST_TIMEOUT,
    )
    assert resp.status_code == 201
    data = resp.json()
    yield data["api_key"]


@pytest.fixture(scope="module")
def manual_workflow(running_server, api_key):
    """Create a manual-triggered workflow for E2E tests."""
    resp = httpx.post(
        f"{running_server}/api/workflows",
        json={
            "name": "E2E Exec Flow",
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


class TestCancelE2E:
    """E2E tests for POST /api/executions/:id/cancel."""

    def test_cancel_completed_returns_409(
        self, running_server, api_key, manual_workflow
    ):
        """Cancel a completed execution returns 409."""
        wf_id = manual_workflow["id"]

        # Execute first (will complete since it's a simple transform)
        resp = httpx.post(
            f"{running_server}/api/workflows/{wf_id}/execute",
            json={"trigger_data": {"test": True}},
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 202
        exec_id = resp.json()["execution_id"]

        # Try to cancel a completed execution
        resp = httpx.post(
            f"{running_server}/api/executions/{exec_id}/cancel",
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        # The execution likely completed already, so 409
        assert resp.status_code == 409

    def test_cancel_nonexistent_returns_404(self, running_server, api_key):
        """Cancel nonexistent execution returns 404."""
        import uuid

        resp = httpx.post(
            f"{running_server}/api/executions/{uuid.uuid4()}/cancel",
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 404

    def test_cancel_requires_auth(self, running_server):
        """Cancel without API key returns 401."""
        import uuid

        resp = httpx.post(
            f"{running_server}/api/executions/{uuid.uuid4()}/cancel",
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 401


class TestLogsE2E:
    """E2E tests for GET /api/executions/:id/logs."""

    def test_get_logs_returns_200(self, running_server, api_key, manual_workflow):
        """GET /api/executions/:id/logs returns 200."""
        wf_id = manual_workflow["id"]

        # Execute
        resp = httpx.post(
            f"{running_server}/api/workflows/{wf_id}/execute",
            json={"trigger_data": {"test": True}},
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 202
        exec_id = resp.json()["execution_id"]

        # Get logs
        resp = httpx.get(
            f"{running_server}/api/executions/{exec_id}/logs",
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "logs" in body
        assert isinstance(body["logs"], list)

    def test_get_logs_nonexistent_returns_404(self, running_server, api_key):
        """GET /api/executions/:id/logs for nonexistent returns 404."""
        import uuid

        resp = httpx.get(
            f"{running_server}/api/executions/{uuid.uuid4()}/logs",
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 404

    def test_get_logs_requires_auth(self, running_server):
        """GET /api/executions/:id/logs without API key returns 401."""
        import uuid

        resp = httpx.get(
            f"{running_server}/api/executions/{uuid.uuid4()}/logs",
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 401


class TestSSEStreamE2E:
    """E2E tests for GET /api/executions/:id/stream."""

    def test_stream_nonexistent_returns_404(self, running_server, api_key):
        """GET /api/executions/:id/stream for nonexistent returns 404."""
        import uuid

        resp = httpx.get(
            f"{running_server}/api/executions/{uuid.uuid4()}/stream",
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 404

    def test_stream_requires_auth(self, running_server):
        """GET /api/executions/:id/stream without API key returns 401."""
        import uuid

        resp = httpx.get(
            f"{running_server}/api/executions/{uuid.uuid4()}/stream",
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 401

    def test_stream_returns_event_stream(
        self, running_server, api_key, manual_workflow
    ):
        """GET /api/executions/:id/stream returns event-stream content."""
        wf_id = manual_workflow["id"]

        # Execute
        resp = httpx.post(
            f"{running_server}/api/workflows/{wf_id}/execute",
            json={"trigger_data": {"test": True}},
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 202
        exec_id = resp.json()["execution_id"]

        # Stream (use a short timeout since execution is likely done)
        with httpx.stream(
            "GET",
            f"{running_server}/api/executions/{exec_id}/stream",
            headers={"X-API-Key": api_key},
            timeout=5.0,
        ) as resp:
            assert resp.status_code == 200
            ct = resp.headers.get("content-type", "")
            assert "text/event-stream" in ct
