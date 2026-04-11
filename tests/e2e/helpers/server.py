"""Start/stop utilities for the E2E test server."""

import os
import subprocess
import time

import httpx

E2E_PORT = 8099
BASE_URL = f"http://127.0.0.1:{E2E_PORT}"
HEALTH_URL = f"{BASE_URL}/api/health"
STARTUP_TIMEOUT = 15


def start_server() -> subprocess.Popen:
    """Start the uvicorn server as a subprocess.

    Returns:
        The Popen process handle.
    """
    env = os.environ.copy()
    env["ENV"] = "testing"

    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    venv_python = os.path.join(project_root, "venv", "Scripts", "python.exe")

    proc = subprocess.Popen(
        [
            venv_python,
            "-m",
            "uvicorn",
            "src.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(E2E_PORT),
        ],
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def wait_for_healthy(timeout: int = STARTUP_TIMEOUT) -> bool:
    """Wait until the health endpoint responds 200.

    Args:
        timeout: Maximum seconds to wait.

    Returns:
        True if server became healthy, False on timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(HEALTH_URL, timeout=2)
            if resp.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.ReadError):
            pass
        time.sleep(0.5)
    return False


def stop_server(proc: subprocess.Popen) -> None:
    """Stop the server subprocess reliably."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
