"""Unit tests for queue task definitions.

Tests dispatch_step for enqueuing arq jobs and the step registry
that maps StepType to executor classes.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine.models import StepType


class TestStepRegistry:
    """Tests for the step type to executor class registry."""

    def test_registry_importable(self):
        """STEP_REGISTRY can be imported from src.queue.tasks."""
        from src.queue.tasks import STEP_REGISTRY

        assert isinstance(STEP_REGISTRY, dict)

    def test_registry_contains_http(self):
        """Registry maps StepType.HTTP to HttpExecutor."""
        from src.queue.tasks import STEP_REGISTRY

        assert StepType.HTTP in STEP_REGISTRY

    def test_registry_contains_transform(self):
        """Registry maps StepType.TRANSFORM to TransformExecutor."""
        from src.queue.tasks import STEP_REGISTRY

        assert StepType.TRANSFORM in STEP_REGISTRY

    def test_registry_contains_condition(self):
        """Registry maps StepType.CONDITION to ConditionExecutor."""
        from src.queue.tasks import STEP_REGISTRY

        assert StepType.CONDITION in STEP_REGISTRY

    def test_registry_contains_delay(self):
        """Registry maps StepType.DELAY to DelayExecutor."""
        from src.queue.tasks import STEP_REGISTRY

        assert StepType.DELAY in STEP_REGISTRY

    def test_registry_executors_are_base_subclasses(self):
        """All registry values are subclasses of BaseStepExecutor."""
        from src.queue.tasks import STEP_REGISTRY
        from src.steps.base import BaseStepExecutor

        for step_type, executor_class in STEP_REGISTRY.items():
            assert issubclass(executor_class, BaseStepExecutor), (
                f"{step_type} maps to {executor_class} which is not a "
                f"BaseStepExecutor subclass"
            )


class TestDispatchStep:
    """Tests for dispatching steps as arq jobs."""

    async def test_dispatch_step_enqueues_job(self):
        """dispatch_step enqueues an arq job with correct arguments."""
        from src.queue.tasks import dispatch_step

        mock_redis = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="job123"))

        with patch("src.queue.tasks.create_pool", return_value=mock_pool):
            await dispatch_step(
                redis=mock_redis,
                step_execution_id="se-123",
                execution_id="ex-456",
                tenant_id="t-789",
            )

        mock_pool.enqueue_job.assert_called_once()
        call_args = mock_pool.enqueue_job.call_args
        assert call_args[0][0] == "execute_step"

    async def test_dispatch_step_passes_ids(self):
        """dispatch_step passes step_execution_id, execution_id, tenant_id."""
        from src.queue.tasks import dispatch_step

        mock_redis = AsyncMock()
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=MagicMock(job_id="job123"))

        with patch("src.queue.tasks.create_pool", return_value=mock_pool):
            await dispatch_step(
                redis=mock_redis,
                step_execution_id="se-123",
                execution_id="ex-456",
                tenant_id="t-789",
            )

        call_args = mock_pool.enqueue_job.call_args
        # IDs should be passed as keyword arguments
        assert "se-123" in str(call_args)
        assert "ex-456" in str(call_args)
        assert "t-789" in str(call_args)


class TestExecuteStepTask:
    """Tests for the execute_step arq task function."""

    def test_execute_step_importable(self):
        """execute_step can be imported from src.queue.tasks."""
        from src.queue.tasks import execute_step

        assert callable(execute_step)

    def test_execute_step_is_async(self):
        """execute_step is an async function."""
        import asyncio

        from src.queue.tasks import execute_step

        assert asyncio.iscoroutinefunction(execute_step)
