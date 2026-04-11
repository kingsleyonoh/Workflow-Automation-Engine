"""Unit tests for the workflow definition parser.

Tests validation of workflow JSON definitions, step types, dependency graphs,
cycle detection, depth limits, and Jinja2 expression validation.
"""

import pytest

from src.config import settings


def _make_step(
    step_id: str = "step_1",
    step_type: str = "http",
    config: dict | None = None,
    depends_on: list[str] | None = None,
    retry: dict | None = None,
) -> dict:
    """Create a step definition dict for testing."""
    step: dict = {
        "id": step_id,
        "type": step_type,
        "config": config or {"url": "https://example.com"},
    }
    if depends_on is not None:
        step["depends_on"] = depends_on
    if retry is not None:
        step["retry"] = retry
    return step


def _make_workflow(
    steps: list[dict] | None = None,
    name: str = "Test Workflow",
    trigger_type: str = "webhook",
) -> dict:
    """Create a workflow definition dict for testing."""
    return {
        "name": name,
        "trigger_type": trigger_type,
        "steps": steps if steps is not None else [_make_step()],
    }


class TestParserValidWorkflow:
    """Tests for parsing valid workflow definitions."""

    def test_parse_single_step_workflow(self):
        """A workflow with one valid step should parse successfully."""
        from src.engine.parser import parse_workflow_definition

        raw = _make_workflow()
        result = parse_workflow_definition(raw)
        assert result.name == "Test Workflow"
        assert len(result.steps) == 1
        assert result.steps[0].id == "step_1"
        assert result.steps[0].type == "http"

    def test_parse_multi_step_linear_chain(self):
        """A linear chain of steps should parse successfully."""
        from src.engine.parser import parse_workflow_definition

        steps = [
            _make_step("a", "http"),
            _make_step(
                "b",
                "transform",
                config={"expression": "{{ steps.a.output }}"},
                depends_on=["a"],
            ),
            _make_step("c", "delay", config={"seconds": 5}, depends_on=["b"]),
        ]
        result = parse_workflow_definition(_make_workflow(steps=steps))
        assert len(result.steps) == 3
        assert result.steps[1].depends_on == ["a"]

    def test_parse_all_step_types(self):
        """All valid step types should be accepted."""
        from src.engine.parser import parse_workflow_definition

        step_types = ["http", "transform", "condition", "delay", "sub_workflow"]
        steps = []
        for i, st in enumerate(step_types):
            config = (
                {"url": "https://example.com"}
                if st == "http"
                else {"expression": "x"}
                if st in ("transform", "condition")
                else {"seconds": 1}
                if st == "delay"
                else {"workflow_id": "abc"}
            )
            deps = [steps[-1]["id"]] if steps else []
            steps.append(
                _make_step(
                    f"step_{i}", st, config=config, depends_on=deps if deps else None
                )
            )
        result = parse_workflow_definition(_make_workflow(steps=steps))
        assert len(result.steps) == 5

    def test_parse_step_with_retry_config(self):
        """A step with retry config should parse successfully."""
        from src.engine.parser import parse_workflow_definition

        steps = [
            _make_step("a", "http", retry={"max_attempts": 5, "delay_seconds": 10}),
        ]
        result = parse_workflow_definition(_make_workflow(steps=steps))
        assert result.steps[0].retry is not None
        assert result.steps[0].retry.max_attempts == 5
        assert result.steps[0].retry.delay_seconds == 10

    def test_parse_step_without_retry_defaults_to_none(self):
        """A step without retry config should have retry=None."""
        from src.engine.parser import parse_workflow_definition

        steps = [_make_step("a", "http")]
        result = parse_workflow_definition(_make_workflow(steps=steps))
        assert result.steps[0].retry is None

    def test_parse_diamond_dependency(self):
        """A diamond-shaped dependency graph (fan-out + fan-in) should parse."""
        from src.engine.parser import parse_workflow_definition

        steps = [
            _make_step("root", "http"),
            _make_step(
                "left", "transform", config={"expression": "x"}, depends_on=["root"]
            ),
            _make_step("right", "delay", config={"seconds": 1}, depends_on=["root"]),
            _make_step("merge", "http", depends_on=["left", "right"]),
        ]
        result = parse_workflow_definition(_make_workflow(steps=steps))
        assert len(result.steps) == 4

    def test_parse_returns_dependency_graph(self):
        """The parse result should include the dependency graph."""
        from src.engine.parser import parse_workflow_definition

        steps = [
            _make_step("a", "http"),
            _make_step("b", "transform", config={"expression": "x"}, depends_on=["a"]),
        ]
        result = parse_workflow_definition(_make_workflow(steps=steps))
        assert result.dependency_graph == {"a": [], "b": ["a"]}

    def test_parse_identifies_root_steps(self):
        """Root steps (no dependencies) should be identifiable from the graph."""
        from src.engine.parser import parse_workflow_definition

        steps = [
            _make_step("a", "http"),
            _make_step("b", "http"),
            _make_step(
                "c", "transform", config={"expression": "x"}, depends_on=["a", "b"]
            ),
        ]
        result = parse_workflow_definition(_make_workflow(steps=steps))
        root_steps = [s.id for s in result.steps if not s.depends_on]
        assert sorted(root_steps) == ["a", "b"]


class TestParserCycleDetection:
    """Tests for cycle detection in workflow dependency graphs."""

    def test_direct_cycle_detected(self):
        """A step depending on itself should raise CYCLE_DETECTED."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [_make_step("a", "http", depends_on=["a"])]
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_two_node_cycle_detected(self):
        """A mutual dependency between two steps should raise CYCLE_DETECTED."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [
            _make_step("a", "http", depends_on=["b"]),
            _make_step("b", "http", depends_on=["a"]),
        ]
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "CYCLE_DETECTED"

    def test_three_node_cycle_detected(self):
        """A→B→C→A cycle should raise CYCLE_DETECTED with cycle path."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [
            _make_step("a", "http", depends_on=["c"]),
            _make_step("b", "http", depends_on=["a"]),
            _make_step("c", "http", depends_on=["b"]),
        ]
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "CYCLE_DETECTED"
        # Error should contain cycle path info
        assert len(exc_info.value.details) > 0

    def test_cycle_in_subtree_detected(self):
        """A cycle in a sub-tree should be detected even with valid root steps."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [
            _make_step("root", "http"),
            _make_step("a", "http", depends_on=["root", "c"]),
            _make_step("b", "http", depends_on=["a"]),
            _make_step("c", "http", depends_on=["b"]),
        ]
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "CYCLE_DETECTED"


class TestParserErrorCases:
    """Tests for parser validation errors."""

    def test_no_steps_raises_error(self):
        """An empty steps array should raise NO_STEPS."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=[]))
        assert exc_info.value.code == "NO_STEPS"

    def test_too_many_steps_raises_error(self):
        """Exceeding MAX_STEPS_PER_WORKFLOW should raise TOO_MANY_STEPS."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        max_steps = settings.max_steps_per_workflow
        steps = [_make_step(f"step_{i}", "http") for i in range(max_steps + 1)]
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "TOO_MANY_STEPS"

    def test_unknown_step_type_raises_error(self):
        """An unrecognized step type should raise UNKNOWN_STEP_TYPE."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [_make_step("a", "magic_step")]
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "UNKNOWN_STEP_TYPE"

    def test_invalid_dependency_raises_error(self):
        """Non-existent depends_on reference raises INVALID_DEPENDENCY."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [_make_step("a", "http", depends_on=["nonexistent"])]
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "INVALID_DEPENDENCY"

    def test_duplicate_step_ids_raises_error(self):
        """Duplicate step IDs should raise a validation error."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [
            _make_step("a", "http"),
            _make_step("a", "transform", config={"expression": "x"}),
        ]
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "DUPLICATE_STEP_ID"

    def test_max_depth_exceeded_raises_error(self):
        """A linear chain exceeding MAX_DEPTH (20) should raise MAX_DEPTH_EXCEEDED."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        max_depth = 20
        steps = [_make_step("step_0", "http")]
        for i in range(1, max_depth + 1):
            steps.append(_make_step(f"step_{i}", "http", depends_on=[f"step_{i - 1}"]))
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "MAX_DEPTH_EXCEEDED"

    def test_missing_step_id_raises_validation_error(self):
        """A step without an id field should raise a validation error."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [{"type": "http", "config": {"url": "https://example.com"}}]
        with pytest.raises(AppError):
            parse_workflow_definition(_make_workflow(steps=steps))

    def test_missing_step_type_raises_validation_error(self):
        """A step without a type field should raise a validation error."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [{"id": "a", "config": {"url": "https://example.com"}}]
        with pytest.raises(AppError):
            parse_workflow_definition(_make_workflow(steps=steps))


class TestParserJinja2Validation:
    """Tests for Jinja2 expression validation in step configs."""

    def test_valid_jinja2_expression_passes(self):
        """A valid Jinja2 expression in config should pass validation."""
        from src.engine.parser import parse_workflow_definition

        steps = [
            _make_step("a", "http"),
            _make_step(
                "b",
                "transform",
                config={"expression": "{{ steps.a.output.data }}"},
                depends_on=["a"],
            ),
        ]
        result = parse_workflow_definition(_make_workflow(steps=steps))
        assert len(result.steps) == 2

    def test_invalid_jinja2_syntax_raises_error(self):
        """A Jinja2 syntax error in config should raise EXPRESSION_ERROR."""
        from src.engine.parser import parse_workflow_definition
        from src.lib.utils import AppError

        steps = [
            _make_step(
                "a",
                "transform",
                config={"expression": "{{ invalid syntax ++ }}"},
            ),
        ]
        with pytest.raises(AppError) as exc_info:
            parse_workflow_definition(_make_workflow(steps=steps))
        assert exc_info.value.code == "EXPRESSION_ERROR"
