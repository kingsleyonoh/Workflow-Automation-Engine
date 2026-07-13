"""Unit tests for the HTTP step executor.

Tests the HttpExecutor that makes async HTTP calls via httpx, with
Jinja2 templating in URL/headers/body, response capture, non-2xx failure
handling, transport failures, and response size limits.
"""

import pytest
import respx
from httpx import Response

from src.lib.utils import AppError


class TestHttpExecutorHappyPath:
    """Tests for successful HTTP step execution."""

    async def test_simple_get_request(self):
        """HTTP step executes a GET request and captures response."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/data",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.example.com/data").mock(
                return_value=Response(200, json={"result": "ok"})
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 200
        assert "result" in result["body"]
        assert "ok" in result["body"]
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], (int, float))

    async def test_post_request_with_body(self):
        """HTTP step executes a POST request with JSON body."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/submit",
            "method": "POST",
            "body": '{"name": "test"}',
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.post("https://api.example.com/submit").mock(
                return_value=Response(201, json={"id": 1})
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 201

    async def test_custom_headers(self):
        """HTTP step sends custom headers from config."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/data",
            "method": "GET",
            "headers": {"Authorization": "Bearer mytoken"},
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            route = respx.get("https://api.example.com/data").mock(
                return_value=Response(200, text="ok")
            )
            await executor.execute(config, context)

        assert route.calls[0].request.headers["Authorization"] == "Bearer mytoken"

    async def test_response_captures_headers(self):
        """HTTP step captures response headers."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/data",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.example.com/data").mock(
                return_value=Response(
                    200,
                    text="ok",
                    headers={"X-Custom": "value"},
                )
            )
            result = await executor.execute(config, context)

        assert "headers" in result
        assert isinstance(result["headers"], dict)

    async def test_default_method_is_get(self):
        """HTTP step defaults to GET when method not specified."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/data",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            route = respx.get("https://api.example.com/data").mock(
                return_value=Response(200, text="ok")
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 200
        assert route.called


class TestHttpExecutorTemplating:
    """Tests for Jinja2 templating in HTTP step config."""

    async def test_jinja2_in_url(self):
        """HTTP step evaluates Jinja2 in URL."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/users/{{ trigger.payload.user_id }}",
            "method": "GET",
        }
        context = {"trigger": {"payload": {"user_id": "42"}}, "steps": {}}

        with respx.mock:
            route = respx.get("https://api.example.com/users/42").mock(
                return_value=Response(200, text="ok")
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 200
        assert route.called

    async def test_jinja2_in_headers(self):
        """HTTP step evaluates Jinja2 in header values."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/data",
            "method": "GET",
            "headers": {
                "Authorization": "Bearer {{ trigger.payload.token }}",
            },
        }
        context = {
            "trigger": {"payload": {"token": "secret123"}},
            "steps": {},
        }

        with respx.mock:
            route = respx.get("https://api.example.com/data").mock(
                return_value=Response(200, text="ok")
            )
            await executor.execute(config, context)

        assert route.calls[0].request.headers["Authorization"] == "Bearer secret123"

    async def test_jinja2_in_body(self):
        """HTTP step evaluates Jinja2 in request body."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/submit",
            "method": "POST",
            "body": '{"name": "{{ trigger.payload.name }}"}',
        }
        context = {
            "trigger": {"payload": {"name": "Alice"}},
            "steps": {},
        }

        with respx.mock:
            route = respx.post("https://api.example.com/submit").mock(
                return_value=Response(201, text="created")
            )
            await executor.execute(config, context)

        body = route.calls[0].request.content.decode()
        assert "Alice" in body

    async def test_jinja2_with_step_output(self):
        """HTTP step can reference previous step outputs in URL."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/items/{{ steps.lookup.output.item_id }}",
            "method": "GET",
        }
        context = {
            "trigger": {"payload": {}},
            "steps": {"lookup": {"output": {"item_id": "99"}}},
        }

        with respx.mock:
            route = respx.get("https://api.example.com/items/99").mock(
                return_value=Response(200, text="ok")
            )
            await executor.execute(config, context)

        assert route.called


class TestHttpExecutorRetry:
    """Tests for HTTP step retry policy."""

    async def test_5xx_raises_retryable_error(self):
        """HTTP step raises retryable error on 5xx status code."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/fail",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.example.com/fail").mock(
                return_value=Response(500, text="Internal Server Error")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_ERROR"
        assert exc_info.value.status_code == 502

    @pytest.mark.parametrize("status_code", [199, 300, 400, 404, 429])
    async def test_non_2xx_response_raises_step_error(self, status_code):
        """HTTP step rejects redirects and client errors as step failures."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/unsuccessful",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.example.com/unsuccessful").mock(
                return_value=Response(status_code, text="Request unsuccessful")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_ERROR"
        assert exc_info.value.details[0]["status_code"] == status_code

    async def test_timeout_raises_retryable_error(self):
        """HTTP step raises retryable error on timeout."""
        import httpx

        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/slow",
            "method": "GET",
            "timeout_seconds": 1,
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.example.com/slow").mock(
                side_effect=httpx.TimeoutException("Connection timed out")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_TIMEOUT"


class TestHttpExecutorValidation:
    """Tests for HTTP step config validation and edge cases."""

    async def test_missing_url_raises_error(self):
        """HTTP step raises error when URL is missing from config."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {"method": "GET"}
        context = {"trigger": {"payload": {}}, "steps": {}}

        with pytest.raises(AppError) as exc_info:
            await executor.execute(config, context)
        assert exc_info.value.code == "STEP_CONFIG_ERROR"

    async def test_response_body_truncated_when_too_large(self):
        """HTTP step truncates response body exceeding max size."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/large",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        large_body = "x" * 2_000_000  # 2MB, exceeds 1MB default
        with respx.mock:
            respx.get("https://api.example.com/large").mock(
                return_value=Response(200, text=large_body)
            )
            result = await executor.execute(config, context)

        # Body should be truncated to max_response_body_size
        # Small margin for truncation note
        assert len(result["body"]) <= 1_048_576 + 100

    async def test_connection_error_raises(self):
        """HTTP step raises error on connection failure."""
        import httpx

        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/down",
            "method": "GET",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.get("https://api.example.com/down").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            with pytest.raises(AppError) as exc_info:
                await executor.execute(config, context)

        assert exc_info.value.code == "HTTP_STEP_ERROR"

    async def test_put_method(self):
        """HTTP step supports PUT method."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/update",
            "method": "PUT",
            "body": '{"updated": true}',
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            route = respx.put("https://api.example.com/update").mock(
                return_value=Response(200, text="ok")
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 200
        assert route.called

    async def test_delete_method(self):
        """HTTP step supports DELETE method."""
        from src.steps.http import HttpExecutor

        executor = HttpExecutor()
        config = {
            "url": "https://api.example.com/resource/1",
            "method": "DELETE",
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with respx.mock:
            respx.delete("https://api.example.com/resource/1").mock(
                return_value=Response(204, text="")
            )
            result = await executor.execute(config, context)

        assert result["status_code"] == 204
