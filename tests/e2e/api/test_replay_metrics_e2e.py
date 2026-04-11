"""E2E tests for execution replay and metrics endpoints.

Hits a running server over HTTP to validate the replay and metrics
API endpoints added in batch 010. Tests are ordered to avoid
blocking the single-threaded server with concurrent replay executions.
"""

import uuid

import httpx
import pytest

pytestmark = pytest.mark.e2e

REQUEST_TIMEOUT = 30


@pytest.fixture(scope="module")
def api_key(running_server):
    """Register a tenant and return its API key for E2E tests."""
    resp = httpx.post(
        f"{running_server}/api/tenants/register",
        json={"name": "E2E Replay Metrics Tenant"},
        timeout=REQUEST_TIMEOUT,
    )
    assert resp.status_code == 201
    data = resp.json()
    yield data["api_key"]


@pytest.fixture(scope="module")
def manual_workflow(running_server, api_key):
    """Create a manual-triggered workflow with a simple step."""
    resp = httpx.post(
        f"{running_server}/api/workflows",
        json={
            "name": "E2E Replay Flow",
            "trigger_type": "manual",
            "steps": [
                {
                    "id": "step_1",
                    "type": "transform",
                    "config": {"expression": "hello"},
                }
            ],
        },
        headers={"X-API-Key": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture(scope="module")
def executed_workflow(running_server, api_key, manual_workflow):
    """Execute a workflow and return the execution_id."""
    wf_id = manual_workflow["id"]
    resp = httpx.post(
        f"{running_server}/api/workflows/{wf_id}/execute",
        json={"trigger_data": {"key": "value"}},
        headers={"X-API-Key": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    assert resp.status_code == 202
    return resp.json()["execution_id"]


class TestReplayAndMetricsE2E:
    """E2E tests for replay and metrics endpoints.

    Tests are consolidated to minimize blocking the event loop.
    Fast tests (auth checks, 404s) run first, then slow replay.
    """

    def test_replay_requires_auth(self, running_server):
        """POST /api/executions/:id/replay without API key returns 401."""
        resp = httpx.post(
            f"{running_server}/api/executions/{uuid.uuid4()}/replay",
            json={},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 401

    def test_metrics_requires_auth(self, running_server):
        """GET /api/metrics/executions without API key returns 401."""
        resp = httpx.get(
            f"{running_server}/api/metrics/executions",
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 401

    def test_replay_nonexistent_returns_404(self, running_server, api_key):
        """POST /api/executions/:id/replay for nonexistent returns 404."""
        resp = httpx.post(
            f"{running_server}/api/executions/{uuid.uuid4()}/replay",
            json={},
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 404

    def test_metrics_returns_200(
        self, running_server, api_key, executed_workflow
    ):
        """GET /api/metrics/executions returns 200 with correct shape."""
        resp = httpx.get(
            f"{running_server}/api/metrics/executions",
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "by_status" in body
        assert "avg_duration_ms" in body
        assert "by_workflow" in body
        assert "step_failure_rates" in body
        assert "webhook_delivery_stats" in body
        assert body["total"] >= 1

    def test_replay_returns_202(
        self, running_server, api_key, executed_workflow
    ):
        """POST /api/executions/:id/replay returns 202."""
        exec_id = executed_workflow

        resp = httpx.post(
            f"{running_server}/api/executions/{exec_id}/replay",
            json={},
            headers={"X-API-Key": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "execution_id" in body
        assert body["execution_id"] != exec_id
