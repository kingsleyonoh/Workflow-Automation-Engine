"""Unit tests for shared execution context management.

Tests merge_step_output and get_step_input functions for
correct context structure and thread-safe JSONB merging.
"""

import pytest

from src.lib.utils import AppError


class TestMergeStepOutput:
    """Tests for merging step output into execution context."""

    async def test_merge_output_creates_steps_key(self, db_session):
        """Merging output creates the steps key in context if absent."""
        from src.db.models import Execution, Tenant, Workflow
        from src.engine.context import merge_step_output

        tenant = Tenant(
            name="Ctx Tenant 1",
            api_key_hash="hash",
            api_key_prefix="wae_live_ctx000001",
        )
        db_session.add(tenant)
        await db_session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="Ctx WF",
            trigger_type="manual",
            steps=[{"id": "s1", "type": "transform", "config": {}}],
        )
        db_session.add(workflow)
        await db_session.flush()

        execution = Execution(
            tenant_id=tenant.id,
            workflow_id=workflow.id,
            status="running",
            context={},
        )
        db_session.add(execution)
        await db_session.flush()

        await merge_step_output(
            db_session, execution.id, "s1", {"result": "hello"}
        )
        await db_session.refresh(execution)

        assert "steps" in execution.context
        assert "s1" in execution.context["steps"]
        assert execution.context["steps"]["s1"]["output"] == {"result": "hello"}

    async def test_merge_output_preserves_existing_steps(self, db_session):
        """Merging output preserves other steps' outputs."""
        from src.db.models import Execution, Tenant, Workflow
        from src.engine.context import merge_step_output

        tenant = Tenant(
            name="Ctx Tenant 2",
            api_key_hash="hash",
            api_key_prefix="wae_live_ctx000002",
        )
        db_session.add(tenant)
        await db_session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="Ctx WF 2",
            trigger_type="manual",
            steps=[
                {"id": "s1", "type": "transform", "config": {}},
                {"id": "s2", "type": "transform", "config": {}},
            ],
        )
        db_session.add(workflow)
        await db_session.flush()

        execution = Execution(
            tenant_id=tenant.id,
            workflow_id=workflow.id,
            status="running",
            context={"steps": {"s1": {"output": {"a": 1}}}},
        )
        db_session.add(execution)
        await db_session.flush()

        await merge_step_output(
            db_session, execution.id, "s2", {"b": 2}
        )
        await db_session.refresh(execution)

        assert execution.context["steps"]["s1"]["output"] == {"a": 1}
        assert execution.context["steps"]["s2"]["output"] == {"b": 2}

    async def test_merge_output_preserves_trigger_data(self, db_session):
        """Merging step output does not overwrite trigger data in context."""
        from src.db.models import Execution, Tenant, Workflow
        from src.engine.context import merge_step_output

        tenant = Tenant(
            name="Ctx Tenant 3",
            api_key_hash="hash",
            api_key_prefix="wae_live_ctx000003",
        )
        db_session.add(tenant)
        await db_session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="Ctx WF 3",
            trigger_type="webhook",
            steps=[{"id": "s1", "type": "transform", "config": {}}],
        )
        db_session.add(workflow)
        await db_session.flush()

        execution = Execution(
            tenant_id=tenant.id,
            workflow_id=workflow.id,
            status="running",
            context={"trigger": {"payload": {"name": "test"}}},
        )
        db_session.add(execution)
        await db_session.flush()

        await merge_step_output(
            db_session, execution.id, "s1", {"val": 42}
        )
        await db_session.refresh(execution)

        assert execution.context["trigger"]["payload"]["name"] == "test"
        assert execution.context["steps"]["s1"]["output"] == {"val": 42}

    async def test_merge_output_not_found_raises(self, db_session):
        """merge_step_output raises AppError when execution not found."""
        from src.engine.context import merge_step_output
        from src.lib.utils import generate_uuid

        fake_id = generate_uuid()
        with pytest.raises(AppError) as exc_info:
            await merge_step_output(db_session, fake_id, "s1", {"x": 1})
        assert exc_info.value.code == "NOT_FOUND"


class TestGetStepInput:
    """Tests for assembling step input from execution context."""

    def test_get_step_input_with_trigger_and_steps(self):
        """get_step_input returns context with steps and trigger data."""
        from src.engine.context import get_step_input

        context = {
            "steps": {"s1": {"output": {"status_code": 200}}},
            "trigger": {"payload": {"name": "test"}},
        }
        config = {"expression": "{{ trigger.payload.name }}"}
        result = get_step_input(context, "s2", config)

        assert "steps" in result
        assert "trigger" in result
        assert result["steps"]["s1"]["output"]["status_code"] == 200
        assert result["trigger"]["payload"]["name"] == "test"

    def test_get_step_input_empty_context(self):
        """get_step_input handles empty execution context gracefully."""
        from src.engine.context import get_step_input

        context = {}
        result = get_step_input(context, "s1", {"expression": "test"})

        assert "steps" in result
        assert "trigger" in result
        assert result["steps"] == {}
        assert result["trigger"] == {}

    def test_get_step_input_includes_config(self):
        """get_step_input includes step config in the result."""
        from src.engine.context import get_step_input

        context = {"trigger": {"payload": {"x": 1}}}
        config = {"expression": "{{ trigger.payload.x }}"}
        result = get_step_input(context, "s1", config)

        assert result["trigger"]["payload"]["x"] == 1
