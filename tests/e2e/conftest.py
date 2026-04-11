"""E2E test fixtures — start/stop real server."""

import pytest

from tests.e2e.helpers.server import (
    BASE_URL,
    start_server,
    stop_server,
    wait_for_healthy,
)


@pytest.fixture(scope="module")
def running_server():
    """Start the uvicorn server for E2E tests and stop it after."""
    proc = start_server()
    healthy = wait_for_healthy()
    if not healthy:
        stop_server(proc)
        pytest.skip("Server did not become healthy in time")
    yield BASE_URL
    stop_server(proc)
