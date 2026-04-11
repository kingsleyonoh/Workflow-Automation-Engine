"""Unit tests for replay service.

Tests execution replay logic: trigger data loading, override merging,
replayed_from linkage, and config guard.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.lib.utils import AppError


class TestReplayService:
    """Tests for replay.service.replay_execution."""

    async def test_replay_creates_execution_with_replayed_from(self):
        """Replayed execution is linked via replayed_from."""
        from src.replay.service import replay_execution

        original_exec_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        workflow_id = uuid.uuid4()

        # Mock original execution
        mock_execution = MagicMock()
        mock_execution.id = original_exec_id
        mock_execution.tenant_id = tenant_id
        mock_execution.workflow_id = workflow_id
        mock_execution.trigger_data = {"source": "manual", "data": {"key": "val"}}

        # Mock workflow
        mock_workflow = MagicMock()
        mock_workflow.id = workflow_id
        mock_workflow.is_active = True

        mock_session = AsyncMock()
        # First call returns execution, second returns workflow
        mock_result_exec = MagicMock()
        mock_result_exec.scalar_one_or_none.return_value = mock_execution
        mock_result_wf = MagicMock()
        mock_result_wf.scalar_one_or_none.return_value = mock_workflow
        mock_session.execute.side_effect = [mock_result_exec, mock_result_wf]

        mock_new_exec = MagicMock()
        mock_new_exec.id = uuid.uuid4()

        from unittest.mock import patch

        with patch(
            "src.replay.service.start_execution",
            new_callable=AsyncMock,
            return_value=mock_new_exec,
        ) as mock_start:
            result = await replay_execution(
                session=mock_session,
                execution_id=original_exec_id,
                tenant_id=tenant_id,
            )

        assert result == mock_new_exec
        # Verify start_execution was called with replayed_from
        mock_start.assert_called_once()
        call_kwargs = mock_start.call_args
        assert call_kwargs.kwargs.get("replayed_from") == original_exec_id

    async def test_replay_merges_override_data(self):
        """Replayed execution merges override_data into trigger data."""
        from src.replay.service import replay_execution

        original_exec_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        workflow_id = uuid.uuid4()

        mock_execution = MagicMock()
        mock_execution.id = original_exec_id
        mock_execution.tenant_id = tenant_id
        mock_execution.workflow_id = workflow_id
        mock_execution.trigger_data = {"source": "manual", "data": {"key": "val"}}

        mock_workflow = MagicMock()
        mock_workflow.id = workflow_id
        mock_workflow.is_active = True

        mock_session = AsyncMock()
        mock_result_exec = MagicMock()
        mock_result_exec.scalar_one_or_none.return_value = mock_execution
        mock_result_wf = MagicMock()
        mock_result_wf.scalar_one_or_none.return_value = mock_workflow
        mock_session.execute.side_effect = [mock_result_exec, mock_result_wf]

        mock_new_exec = MagicMock()
        mock_new_exec.id = uuid.uuid4()

        from unittest.mock import patch

        with patch(
            "src.replay.service.start_execution",
            new_callable=AsyncMock,
            return_value=mock_new_exec,
        ) as mock_start:
            await replay_execution(
                session=mock_session,
                execution_id=original_exec_id,
                tenant_id=tenant_id,
                override_data={"key": "overridden", "extra": "new"},
            )

        call_kwargs = mock_start.call_args
        trigger = call_kwargs.kwargs.get("trigger_data")
        # Original data merged with override
        assert trigger["data"]["key"] == "overridden"
        assert trigger["data"]["extra"] == "new"
        assert trigger["source"] == "manual"

    async def test_replay_not_found_raises_404(self):
        """Replay of nonexistent execution raises NOT_FOUND."""
        from src.replay.service import replay_execution

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(AppError, match="not found"):
            await replay_execution(
                session=mock_session,
                execution_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
            )

    async def test_replay_inactive_workflow_raises_error(self):
        """Replay with inactive workflow raises error."""
        from src.replay.service import replay_execution

        original_exec_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        workflow_id = uuid.uuid4()

        mock_execution = MagicMock()
        mock_execution.id = original_exec_id
        mock_execution.tenant_id = tenant_id
        mock_execution.workflow_id = workflow_id
        mock_execution.trigger_data = {"source": "test"}

        mock_workflow = MagicMock()
        mock_workflow.id = workflow_id
        mock_workflow.is_active = False

        mock_session = AsyncMock()
        mock_result_exec = MagicMock()
        mock_result_exec.scalar_one_or_none.return_value = mock_execution
        mock_result_wf = MagicMock()
        mock_result_wf.scalar_one_or_none.return_value = mock_workflow
        mock_session.execute.side_effect = [mock_result_exec, mock_result_wf]

        with pytest.raises(AppError, match="not active"):
            await replay_execution(
                session=mock_session,
                execution_id=original_exec_id,
                tenant_id=tenant_id,
            )
