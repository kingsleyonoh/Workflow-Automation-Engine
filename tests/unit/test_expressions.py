"""Unit tests for sandboxed Jinja2 expression evaluator.

Tests expression rendering with SandboxedEnvironment, step/trigger
context access, error handling, and SSTI prevention.
"""

import pytest

from src.lib.utils import AppError


class TestBasicExpressions:
    """Tests for basic Jinja2 expression evaluation."""

    def test_simple_string_passthrough(self):
        """Plain string without expressions returns unchanged."""
        from src.lib.expressions import evaluate_expression

        result = evaluate_expression("hello world", {})
        assert result == "hello world"

    def test_simple_variable_substitution(self):
        """Single variable expression renders correctly."""
        from src.lib.expressions import evaluate_expression

        result = evaluate_expression("{{ name }}", {"name": "Alice"})
        assert result == "Alice"

    def test_nested_field_access(self):
        """Dot-notation nested field access works."""
        from src.lib.expressions import evaluate_expression

        ctx = {"user": {"profile": {"email": "a@b.com"}}}
        result = evaluate_expression("{{ user.profile.email }}", ctx)
        assert result == "a@b.com"

    def test_multiple_expressions_in_string(self):
        """Multiple expressions in a single template render correctly."""
        from src.lib.expressions import evaluate_expression

        ctx = {"first": "John", "last": "Doe"}
        result = evaluate_expression("{{ first }} {{ last }}", ctx)
        assert result == "John Doe"

    def test_expression_with_default_filter(self):
        """Jinja2 default filter works for missing variables."""
        from src.lib.expressions import evaluate_expression

        result = evaluate_expression("{{ missing | default('fallback') }}", {})
        assert result == "fallback"


class TestStepContextExpressions:
    """Tests for steps.step_id.output.field syntax."""

    def test_step_output_field_access(self):
        """{{ steps.step_id.output.field }} resolves correctly."""
        from src.lib.expressions import evaluate_expression

        ctx = {
            "steps": {
                "fetch_user": {
                    "output": {"user_id": 42, "name": "Alice"},
                }
            }
        }
        result = evaluate_expression("{{ steps.fetch_user.output.user_id }}", ctx)
        assert result == "42"

    def test_step_output_nested_field(self):
        """Deeply nested step output fields resolve correctly."""
        from src.lib.expressions import evaluate_expression

        ctx = {
            "steps": {
                "api_call": {
                    "output": {
                        "body": {"status_code": 200, "message": "ok"},
                    }
                }
            }
        }
        result = evaluate_expression(
            "{{ steps.api_call.output.body.status_code }}", ctx
        )
        assert result == "200"

    def test_multiple_step_references(self):
        """Multiple step references in one template resolve correctly."""
        from src.lib.expressions import evaluate_expression

        ctx = {
            "steps": {
                "step_a": {"output": {"val": "X"}},
                "step_b": {"output": {"val": "Y"}},
            }
        }
        result = evaluate_expression(
            "{{ steps.step_a.output.val }}-{{ steps.step_b.output.val }}",
            ctx,
        )
        assert result == "X-Y"


class TestTriggerContextExpressions:
    """Tests for trigger.payload.field syntax."""

    def test_trigger_payload_field(self):
        """{{ trigger.payload.field }} resolves correctly."""
        from src.lib.expressions import evaluate_expression

        ctx = {
            "trigger": {
                "payload": {"event": "push", "repo": "my-repo"},
            }
        }
        result = evaluate_expression("{{ trigger.payload.event }}", ctx)
        assert result == "push"

    def test_trigger_payload_nested(self):
        """Nested trigger payload fields resolve correctly."""
        from src.lib.expressions import evaluate_expression

        ctx = {
            "trigger": {
                "payload": {
                    "sender": {"login": "octocat"},
                }
            }
        }
        result = evaluate_expression("{{ trigger.payload.sender.login }}", ctx)
        assert result == "octocat"


class TestExpressionErrors:
    """Tests for error handling in expression evaluation."""

    def test_invalid_template_syntax_raises_app_error(self):
        """Malformed Jinja2 syntax raises AppError."""
        from src.lib.expressions import evaluate_expression

        with pytest.raises(AppError) as exc_info:
            evaluate_expression("{{ unclosed", {})
        assert exc_info.value.code == "EXPRESSION_ERROR"

    def test_undefined_variable_raises_app_error(self):
        """Reference to undefined variable raises AppError."""
        from src.lib.expressions import evaluate_expression

        with pytest.raises(AppError) as exc_info:
            evaluate_expression("{{ nonexistent }}", {})
        assert exc_info.value.code == "EXPRESSION_ERROR"

    def test_empty_template_returns_empty_string(self):
        """Empty template returns empty string."""
        from src.lib.expressions import evaluate_expression

        result = evaluate_expression("", {})
        assert result == ""


class TestSSTIPrevention:
    """Tests that SandboxedEnvironment blocks dangerous operations."""

    def test_cannot_access_dunder_class(self):
        """__class__ attribute access is blocked."""
        from src.lib.expressions import evaluate_expression

        with pytest.raises(AppError) as exc_info:
            evaluate_expression("{{ ''.__class__.__mro__[1].__subclasses__() }}", {})
        assert exc_info.value.code == "EXPRESSION_ERROR"

    def test_cannot_access_os_module(self):
        """Accessing os module via template is blocked."""
        from src.lib.expressions import evaluate_expression

        # This should either raise or return a safe string, never execute
        with pytest.raises(AppError):
            evaluate_expression("{{ config.__class__.__init__.__globals__['os'] }}", {})

    def test_cannot_call_dangerous_builtins(self):
        """Built-in functions like eval are not available."""
        from src.lib.expressions import evaluate_expression

        with pytest.raises(AppError):
            evaluate_expression("{{ eval('1+1') }}", {})
