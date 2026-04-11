"""Unit tests for sub_workflow step executor.

Tests sub_workflow execution with depth limits, tenant isolation,
missing workflow, input mapping, and step registry.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.lib.utils import AppError


class TestSubWorkflowExecutor:
    """Tests for SubWorkflowExecutor.execute."""

    async def test_missing_workflow_id_raises_config_error(self):
        """Sub_workflow step requires workflow_id in config."""
        from src.steps.sub_workflow import SubWorkflowExecutor

        executor = SubWorkflowExecutor()
        with pytest.raises(AppError, match="workflow_id"):
            await executor.execute(config={}, context={})

    async def test_depth_exceeded_raises_error(self):
        """Sub_workflow exceeding MAX_SUB_WORKFLOW_DEPTH raises error."""
        from src.steps.sub_workflow import SubWorkflowExecutor

        executor = SubWorkflowExecutor()
        context = {"_depth": 3}  # At max depth
        config = {"workflow_id": str(uuid.uuid4())}

        with pytest.raises(AppError, match="depth"):
            await executor.execute(config=config, context=context)

    async def test_depth_zero_allowed(self):
        """Sub_workflow at depth 0 is allowed."""
        from src.steps.sub_workflow import SubWorkflowExecutor

        executor = SubWorkflowExecutor()
        workflow_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        context = {
            "_depth": 0,
            "_tenant_id": str(tenant_id),
            "_session": mock_session,
        }
        config = {"workflow_id": str(workflow_id)}

        with pytest.raises(AppError, match="not found"):
            await executor.execute(config=config, context=context)

    async def test_workflow_not_found_raises_error(self):
        """Sub_workflow with invalid workflow_id raises NOT_FOUND."""
        from src.steps.sub_workflow import SubWorkflowExecutor

        executor = SubWorkflowExecutor()
        workflow_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        context = {
            "_depth": 0,
            "_tenant_id": str(tenant_id),
            "_session": mock_session,
        }
        config = {"workflow_id": str(workflow_id)}

        with pytest.raises(AppError, match="not found"):
            await executor.execute(config=config, context=context)

    async def test_input_mapping_applied(self):
        """Sub_workflow applies input_mapping to trigger data."""
        from src.steps.sub_workflow import SubWorkflowExecutor

        executor = SubWorkflowExecutor()
        workflow_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Create a mock workflow
        mock_workflow = MagicMock()
        mock_workflow.id = workflow_id
        mock_workflow.tenant_id = tenant_id
        mock_workflow.is_active = True
        mock_workflow.name = "Sub Workflow"
        mock_workflow.trigger_type = "manual"
        mock_workflow.steps = [
            {
                "id": "s1",
                "type": "transform",
                "config": {"expression": "{{ trigger.data.name }}"},
            }
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_workflow
        mock_session.execute.return_value = mock_result

        # Mock start_execution
        mock_execution = MagicMock()
        mock_execution.context = {"steps": {"s1": {"output": {"result": "ALICE"}}}}
        mock_execution.status = "completed"

        context = {
            "_depth": 0,
            "_tenant_id": str(tenant_id),
            "_session": mock_session,
            "trigger": {"data": {"name": "Alice"}},
            "steps": {},
        }
        config = {
            "workflow_id": str(workflow_id),
            "input_mapping": {"name": "{{ trigger.data.name }}"},
        }

        with patch(
            "src.engine.orchestrator.start_execution",
            new_callable=AsyncMock,
            return_value=mock_execution,
        ):
            result = await executor.execute(config=config, context=context)

        assert "context" in result
        assert result["status"] == "completed"

    async def test_registered_in_step_registry(self):
        """SubWorkflowExecutor is registered in STEP_REGISTRY."""
        from src.engine.models import StepType
        from src.queue.tasks import STEP_REGISTRY
        from src.steps.sub_workflow import SubWorkflowExecutor

        assert StepType.SUB_WORKFLOW in STEP_REGISTRY
        assert STEP_REGISTRY[StepType.SUB_WORKFLOW] is SubWorkflowExecutor

    async def test_cross_tenant_blocked(self):
        """Sub_workflow cannot reference workflow from different tenant."""
        from src.steps.sub_workflow import SubWorkflowExecutor

        executor = SubWorkflowExecutor()
        workflow_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        # Workflow belongs to a different tenant
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # tenant-scoped query
        mock_session.execute.return_value = mock_result

        context = {
            "_depth": 0,
            "_tenant_id": str(tenant_id),
            "_session": mock_session,
        }
        config = {"workflow_id": str(workflow_id)}

        with pytest.raises(AppError, match="not found"):
            await executor.execute(config=config, context=context)

    async def test_inactive_workflow_raises_error(self):
        """Sub_workflow with inactive workflow raises error."""
        from src.steps.sub_workflow import SubWorkflowExecutor

        executor = SubWorkflowExecutor()
        workflow_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        mock_workflow = MagicMock()
        mock_workflow.id = workflow_id
        mock_workflow.tenant_id = tenant_id
        mock_workflow.is_active = False

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_workflow
        mock_session.execute.return_value = mock_result

        context = {
            "_depth": 0,
            "_tenant_id": str(tenant_id),
            "_session": mock_session,
        }
        config = {"workflow_id": str(workflow_id)}

        with pytest.raises(AppError, match="not active"):
            await executor.execute(config=config, context=context)
