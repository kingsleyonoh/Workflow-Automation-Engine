"""Integration tests for HTTP step executor with mocked external APIs.

Tests the HttpExecutor against various HTTP response scenarios using
respx to mock external API calls. Validates response handling, error
classification, body truncation, and Jinja2 templating with real
execution context patterns.

Unlike unit tests (tests/unit/test_http_step.py) which test individual
methods, these integration tests exercise the full executor pipeline
with realistic configurations and context structures.
"""

import httpx
import pytest
import respx
from httpx import Response

from src.lib.utils import AppError
from src.steps.http import HttpExecutor

pytestmark = pytest.mark.integration


class TestHttpStepSuccessResponses:
    """Integration tests for successful HTTP response scenarios."""

    async def test_get_200_json_response(self):
        """HTTP step captures JSON response with status 200."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/users",
            "method": "GET",
            "headers": {"Accept": "application/json"},
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/users").mock(
                return_value=Response(
                    200,
                    json={"users": [{"id": 1, "name": "Alice"}]},
                    headers={"Content-Type": "application/json"},
                )
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 200
        assert '"users"' in result["body"]
        assert '"Alice"' in result["body"]
        assert result["duration_ms"] >= 0
        assert isinstance(result["headers"], dict)

    async def test_post_201_created(self):
        """HTTP step handles 201 Created responses correctly."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/orders",
            "method": "POST",
            "body": '{"item": "widget", "quantity": 5}',
            "headers": {"Content-Type": "application/json"},
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.post("https://api.external.com/v1/orders").mock(
                return_value=Response(
                    201,
                    json={"order_id": "ord_123", "status": "created"},
                )
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 201
        assert "ord_123" in result["body"]

    async def test_204_no_content(self):
        """HTTP step handles 204 No Content responses."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/cache",
            "method": "DELETE",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.delete("https://api.external.com/v1/cache").mock(
                return_value=Response(204, text="")
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 204
        assert result["body"] == ""


class TestHttpStep4xxResponses:
    """Integration tests for 4xx client error responses."""

    async def test_400_bad_request_raises(self):
        """HTTP step raises a step error for 400 Bad Request."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/validate",
            "method": "POST",
            "body": '{"invalid": true}',
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.post("https://api.external.com/v1/validate").mock(
                return_value=Response(
                    400,
                    json={"error": "validation_failed", "fields": ["email"]},
                )
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_ERROR"
        assert exc_info.value.details[0]["status_code"] == 400
        assert "validation_failed" in exc_info.value.details[0]["body"]

    async def test_401_unauthorized_raises(self):
        """HTTP step raises a step error for 401 Unauthorized."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/protected",
            "method": "GET",
            "headers": {"Authorization": "Bearer expired_token"},
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/protected").mock(
                return_value=Response(401, json={"error": "unauthorized"})
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.details[0]["status_code"] == 401

    async def test_403_forbidden_raises(self):
        """HTTP step raises a step error for 403 Forbidden."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/admin",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/admin").mock(
                return_value=Response(403, json={"error": "forbidden"})
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.details[0]["status_code"] == 403

    async def test_404_not_found_raises(self):
        """HTTP step raises a step error for 404 Not Found."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/missing",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/missing").mock(
                return_value=Response(404, text="Not Found")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.details[0]["status_code"] == 404

    async def test_429_rate_limited_raises(self):
        """HTTP step raises a step error for 429 Too Many Requests."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/data",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/data").mock(
                return_value=Response(
                    429,
                    json={"error": "rate_limited"},
                    headers={"Retry-After": "60"},
                )
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.details[0]["status_code"] == 429


class TestHttpStep5xxResponses:
    """Integration tests for 5xx server error responses (retryable)."""

    async def test_500_raises_retryable_error(self):
        """HTTP step raises retryable AppError on 500."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/unstable",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/unstable").mock(
                return_value=Response(500, text="Internal Server Error")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_ERROR"
        assert exc_info.value.status_code == 502

    async def test_502_bad_gateway_raises(self):
        """HTTP step raises retryable AppError on 502."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/proxy",
            "method": "POST",
            "body": '{"data": "test"}',
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.post("https://api.external.com/v1/proxy").mock(
                return_value=Response(502, text="Bad Gateway")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_ERROR"

    async def test_503_service_unavailable_raises(self):
        """HTTP step raises retryable AppError on 503."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/maintenance",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/maintenance").mock(
                return_value=Response(503, text="Service Unavailable")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_ERROR"

    async def test_5xx_error_includes_response_details(self):
        """5xx error includes status code and body excerpt in details."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/error",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/error").mock(
                return_value=Response(500, json={"error": "database_connection_lost"})
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.details is not None
        assert exc_info.value.details[0]["status_code"] == 500


class TestHttpStepTimeoutAndConnection:
    """Integration tests for timeout and connection failure scenarios."""

    async def test_timeout_raises_timeout_error(self):
        """HTTP step raises HTTP_STEP_TIMEOUT on request timeout."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/slow",
            "method": "GET",
            "timeout_seconds": 1,
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/slow").mock(
                side_effect=httpx.ReadTimeout("Read timed out")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_TIMEOUT"
        assert exc_info.value.status_code == 504

    async def test_connect_timeout_raises_timeout_error(self):
        """HTTP step raises HTTP_STEP_TIMEOUT on connect timeout."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/unreachable",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/unreachable").mock(
                side_effect=httpx.ConnectTimeout("Connect timed out")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_TIMEOUT"

    async def test_connection_error_raises_http_error(self):
        """HTTP step raises HTTP_STEP_ERROR on connection failure."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/down",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.external.com/v1/down").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_ERROR"
        assert exc_info.value.status_code == 502

    async def test_network_error_raises_http_error(self):
        """HTTP step raises HTTP_STEP_ERROR on generic network error."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/unstable",
            "method": "POST",
            "body": '{"key": "value"}',
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.post("https://api.external.com/v1/unstable").mock(
                side_effect=httpx.RemoteProtocolError("Connection reset")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_ERROR"


class TestHttpStepResponseBodyLimits:
    """Integration tests for response body size truncation."""

    async def test_large_response_truncated(self):
        """Response body exceeding MAX_RESPONSE_BODY_SIZE is truncated."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/large",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        # 2MB body exceeds default 1MB limit
        large_body = "A" * 2_000_000
        with respx.mock:
            respx.get("https://api.external.com/v1/large").mock(
                return_value=Response(200, text=large_body)
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 200
        # Body truncated to ~1MB + truncation marker
        assert len(result["body"]) < 1_100_000
        assert "truncated" in result["body"].lower()

    async def test_body_at_limit_not_truncated(self):
        """Response body exactly at limit is not truncated."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/exact",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        # Exactly 1MB body should not be truncated
        exact_body = "B" * 1_048_576
        with respx.mock:
            respx.get("https://api.external.com/v1/exact").mock(
                return_value=Response(200, text=exact_body)
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 200
        assert "truncated" not in result["body"].lower()

    async def test_small_response_not_truncated(self):
        """Small response body passes through without truncation."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/small",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        small_body = '{"status": "ok", "data": [1, 2, 3]}'
        with respx.mock:
            respx.get("https://api.external.com/v1/small").mock(
                return_value=Response(200, text=small_body)
            )
            result = await executor.execute(config, context)

        assert result["body"] == small_body


class TestHttpStepWithExecutionContext:
    """Integration tests for HTTP step with realistic execution context."""

    async def test_url_templated_from_previous_step(self):
        """HTTP step URL references previous step output via Jinja2."""
        executor = HttpExecutor()
        config = {
            "url": (
                "https://api.external.com/v1/users/"
                "{{ steps.fetch_user.output.user_id }}/profile"
            ),
            "method": "GET",
        }
        context = {
            "trigger": {"payload": {"request_type": "profile"}},
            "steps": {"fetch_user": {"output": {"user_id": "usr_789"}}},
        }

        with respx.mock:
            route = respx.get("https://api.external.com/v1/users/usr_789/profile").mock(
                return_value=Response(200, json={"name": "Test User"})
            )
            result = await executor.execute(config, context)

        assert route.called
        assert result["status_code"] == 200

    async def test_headers_templated_from_trigger(self):
        """HTTP step headers reference trigger data via Jinja2."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/secure",
            "method": "GET",
            "headers": {
                "Authorization": "Bearer {{ trigger.payload.api_token }}",
                "X-Request-ID": "{{ trigger.payload.request_id }}",
            },
        }
        context = {
            "trigger": {
                "payload": {
                    "api_token": "tok_abc123",
                    "request_id": "req_456",
                }
            },
            "steps": {},
        }

        with respx.mock:
            route = respx.get("https://api.external.com/v1/secure").mock(
                return_value=Response(200, text="ok")
            )
            await executor.execute(config, context)

        sent_headers = route.calls[0].request.headers
        assert sent_headers["Authorization"] == "Bearer tok_abc123"
        assert sent_headers["X-Request-ID"] == "req_456"

    async def test_body_templated_from_multi_step_context(self):
        """HTTP step body references multiple step outputs."""
        executor = HttpExecutor()
        config = {
            "url": "https://api.external.com/v1/submit",
            "method": "POST",
            "body": (
                '{"user": "{{ steps.lookup.output.name }}", '
                '"amount": "{{ steps.calc.output.total }}"}'
            ),
        }
        context = {
            "trigger": {"payload": {}},
            "steps": {
                "lookup": {"output": {"name": "Alice"}},
                "calc": {"output": {"total": "99.50"}},
            },
        }

        with respx.mock:
            route = respx.post("https://api.external.com/v1/submit").mock(
                return_value=Response(200, text="ok")
            )
            await executor.execute(config, context)

        body = route.calls[0].request.content.decode()
        assert "Alice" in body
        assert "99.50" in body
