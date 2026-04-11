"""Unit tests for the condition step executor.

Tests the ConditionExecutor that evaluates Jinja2 expressions as boolean
values and returns which branch (true/false) to take.
"""

import pytest

from src.lib.utils import AppError


class TestConditionExecutorTrueBranch:
    """Tests for condition step evaluating to true."""

    async def test_truthy_expression_returns_true_branch(self):
        """Condition step returns true branch when expression is truthy."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.active }}",
            "true_branch": ["step_a", "step_b"],
            "false_branch": ["step_c"],
        }
        context = {"trigger": {"payload": {"active": "yes"}}, "steps": {}}
        result = await executor.execute(config, context)

        assert result["result"] is True
        assert result["branch"] == "true"
        assert result["branch_steps"] == ["step_a", "step_b"]

    async def test_numeric_truthy(self):
        """Condition step treats non-zero number string as truthy."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.count }}",
            "true_branch": ["step_a"],
            "false_branch": ["step_b"],
        }
        context = {"trigger": {"payload": {"count": 5}}, "steps": {}}
        result = await executor.execute(config, context)

        assert result["result"] is True
        assert result["branch"] == "true"

    async def test_non_empty_string_truthy(self):
        """Condition step treats non-empty string as truthy."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.name }}",
            "true_branch": ["step_a"],
            "false_branch": ["step_b"],
        }
        context = {"trigger": {"payload": {"name": "Alice"}}, "steps": {}}
        result = await executor.execute(config, context)

        assert result["result"] is True
        assert result["branch"] == "true"


class TestConditionExecutorFalseBranch:
    """Tests for condition step evaluating to false."""

    async def test_falsy_expression_returns_false_branch(self):
        """Condition step returns false branch when expression is falsy."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.active }}",
            "true_branch": ["step_a"],
            "false_branch": ["step_b", "step_c"],
        }
        context = {"trigger": {"payload": {"active": ""}}, "steps": {}}
        result = await executor.execute(config, context)

        assert result["result"] is False
        assert result["branch"] == "false"
        assert result["branch_steps"] == ["step_b", "step_c"]

    async def test_false_string_is_falsy(self):
        """Condition step treats 'false' string as falsy."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.flag }}",
            "true_branch": ["step_a"],
            "false_branch": ["step_b"],
        }
        context = {"trigger": {"payload": {"flag": "false"}}, "steps": {}}
        result = await executor.execute(config, context)

        assert result["result"] is False
        assert result["branch"] == "false"

    async def test_zero_string_is_falsy(self):
        """Condition step treats '0' string as falsy."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.count }}",
            "true_branch": ["step_a"],
            "false_branch": ["step_b"],
        }
        context = {"trigger": {"payload": {"count": 0}}, "steps": {}}
        result = await executor.execute(config, context)

        assert result["result"] is False
        assert result["branch"] == "false"

    async def test_none_string_is_falsy(self):
        """Condition step treats 'None' string as falsy."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.value }}",
            "true_branch": ["step_a"],
            "false_branch": ["step_b"],
        }
        context = {"trigger": {"payload": {"value": "None"}}, "steps": {}}
        result = await executor.execute(config, context)

        assert result["result"] is False
        assert result["branch"] == "false"


class TestConditionExecutorValidation:
    """Tests for condition step error handling."""

    async def test_missing_expression_raises(self):
        """Condition step raises error when expression is missing."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "true_branch": ["step_a"],
            "false_branch": ["step_b"],
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with pytest.raises(AppError) as exc_info:
            await executor.execute(config, context)
        assert exc_info.value.code == "STEP_CONFIG_ERROR"

    async def test_undefined_variable_raises(self):
        """Condition step raises error when expression references undefined var."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ nonexistent }}",
            "true_branch": ["step_a"],
            "false_branch": ["step_b"],
        }
        context = {"trigger": {"payload": {}}, "steps": {}}

        with pytest.raises(AppError) as exc_info:
            await executor.execute(config, context)
        assert exc_info.value.code == "EXPRESSION_ERROR"

    async def test_empty_branches_default(self):
        """Condition step works with empty branch lists."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.flag }}",
        }
        context = {"trigger": {"payload": {"flag": "yes"}}, "steps": {}}
        result = await executor.execute(config, context)

        assert result["result"] is True
        assert result["branch"] == "true"
        assert result["branch_steps"] == []

    async def test_output_has_correct_shape(self):
        """Condition step output contains result, branch, and branch_steps."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.x }}",
            "true_branch": ["a"],
            "false_branch": ["b"],
        }
        context = {"trigger": {"payload": {"x": "yes"}}, "steps": {}}
        result = await executor.execute(config, context)

        assert "result" in result
        assert "branch" in result
        assert "branch_steps" in result
        assert isinstance(result["result"], bool)
        assert result["branch"] in ("true", "false")
        assert isinstance(result["branch_steps"], list)

    async def test_complex_expression(self):
        """Condition step evaluates complex Jinja2 comparison."""
        from src.steps.condition import ConditionExecutor

        executor = ConditionExecutor()
        config = {
            "expression": "{{ trigger.payload.count > 10 }}",
            "true_branch": ["step_a"],
            "false_branch": ["step_b"],
        }
        context = {"trigger": {"payload": {"count": 15}}, "steps": {}}
        result = await executor.execute(config, context)

        assert result["result"] is True
        assert result["branch"] == "true"
