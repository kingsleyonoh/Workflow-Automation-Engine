"""Unit tests for the transform step executor and base step executor.

Tests the BaseStepExecutor abstract interface and the TransformExecutor
that evaluates Jinja2 expressions against execution context.
"""

import pytest

from src.lib.utils import AppError


class TestBaseStepExecutor:
    """Tests for the abstract BaseStepExecutor."""

    def test_base_cannot_be_instantiated(self):
        """BaseStepExecutor cannot be instantiated directly."""
        from src.steps.base import BaseStepExecutor

        with pytest.raises(TypeError):
            BaseStepExecutor()

    def test_base_has_execute_method(self):
        """BaseStepExecutor defines an abstract execute method."""
        from src.steps.base import BaseStepExecutor

        assert hasattr(BaseStepExecutor, "execute")

    async def test_subclass_can_be_instantiated(self):
        """A concrete subclass of BaseStepExecutor can be instantiated."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        assert executor is not None


class TestTransformExecutor:
    """Tests for the TransformExecutor step executor."""

    async def test_simple_expression(self):
        """Transform evaluates a simple Jinja2 expression."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        config = {"expression": "{{ trigger.payload.name | upper }}"}
        context = {"trigger": {"payload": {"name": "alice"}}}
        result = await executor.execute(config, context)

        assert result["result"] == "ALICE"

    async def test_expression_with_step_output(self):
        """Transform can reference other steps' outputs."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        config = {"expression": "{{ steps.fetch.output.body }}"}
        context = {
            "steps": {"fetch": {"output": {"body": "response_data"}}},
            "trigger": {"payload": {}},
        }
        result = await executor.execute(config, context)

        assert result["result"] == "response_data"

    async def test_expression_with_list_operations(self):
        """Transform handles Jinja2 list operations."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        config = {
            "expression": "{{ trigger.payload.tags | join(', ') }}"
        }
        context = {
            "trigger": {"payload": {"tags": ["a", "b", "c"]}},
        }
        result = await executor.execute(config, context)

        assert result["result"] == "a, b, c"

    async def test_empty_expression_returns_empty(self):
        """Transform with empty expression returns empty string."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        config = {"expression": ""}
        context = {"trigger": {"payload": {}}}
        result = await executor.execute(config, context)

        assert result["result"] == ""

    async def test_missing_expression_key_raises(self):
        """Transform raises error when config has no expression key."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        config = {}
        context = {"trigger": {"payload": {}}}

        with pytest.raises(AppError) as exc_info:
            await executor.execute(config, context)
        assert exc_info.value.code == "STEP_CONFIG_ERROR"

    async def test_invalid_template_syntax_raises(self):
        """Transform raises error on Jinja2 syntax error."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        config = {"expression": "{{ invalid syntax {{"}
        context = {"trigger": {"payload": {}}}

        with pytest.raises(AppError) as exc_info:
            await executor.execute(config, context)
        assert exc_info.value.code == "EXPRESSION_ERROR"

    async def test_undefined_variable_raises(self):
        """Transform raises error on undefined variable reference."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        config = {"expression": "{{ nonexistent_var }}"}
        context = {"trigger": {"payload": {}}}

        with pytest.raises(AppError) as exc_info:
            await executor.execute(config, context)
        assert exc_info.value.code == "EXPRESSION_ERROR"

    async def test_result_is_dict_with_result_key(self):
        """Transform output is a dict with a 'result' key."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        config = {"expression": "hello"}
        context = {"trigger": {"payload": {}}}
        result = await executor.execute(config, context)

        assert isinstance(result, dict)
        assert "result" in result

    async def test_complex_expression(self):
        """Transform handles complex Jinja2 expressions."""
        from src.steps.transform import TransformExecutor

        executor = TransformExecutor()
        config = {
            "expression": (
                "Status: {{ trigger.payload.status }}"
                " - Count: {{ trigger.payload.count }}"
            ),
        }
        context = {
            "trigger": {"payload": {"status": "active", "count": 42}},
        }
        result = await executor.execute(config, context)

        assert result["result"] == "Status: active - Count: 42"
