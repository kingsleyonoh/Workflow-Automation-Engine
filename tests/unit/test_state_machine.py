"""Unit tests for execution and step state machine transitions.

Tests valid transitions, invalid transitions, and the ALLOWED_*_TRANSITIONS maps.
"""

import pytest

from src.lib.utils import AppError


class TestExecutionTransitions:
    """Tests for execution state transition validation."""

    def test_pending_to_running_is_valid(self):
        """Execution can transition from pending to running."""
        from src.engine.state import validate_execution_transition

        validate_execution_transition("pending", "running")

    def test_running_to_completed_is_valid(self):
        """Execution can transition from running to completed."""
        from src.engine.state import validate_execution_transition

        validate_execution_transition("running", "completed")

    def test_running_to_failed_is_valid(self):
        """Execution can transition from running to failed."""
        from src.engine.state import validate_execution_transition

        validate_execution_transition("running", "failed")

    def test_running_to_cancelled_is_valid(self):
        """Execution can transition from running to cancelled."""
        from src.engine.state import validate_execution_transition

        validate_execution_transition("running", "cancelled")

    def test_pending_to_completed_is_invalid(self):
        """Execution cannot skip from pending directly to completed."""
        from src.engine.state import validate_execution_transition

        with pytest.raises(AppError) as exc_info:
            validate_execution_transition("pending", "completed")
        assert exc_info.value.code == "INVALID_TRANSITION"

    def test_completed_to_running_is_invalid(self):
        """Completed execution cannot go back to running."""
        from src.engine.state import validate_execution_transition

        with pytest.raises(AppError) as exc_info:
            validate_execution_transition("completed", "running")
        assert exc_info.value.code == "INVALID_TRANSITION"

    def test_failed_to_running_is_invalid(self):
        """Failed execution cannot go back to running."""
        from src.engine.state import validate_execution_transition

        with pytest.raises(AppError) as exc_info:
            validate_execution_transition("failed", "running")
        assert exc_info.value.code == "INVALID_TRANSITION"

    def test_cancelled_to_running_is_invalid(self):
        """Cancelled execution cannot go back to running."""
        from src.engine.state import validate_execution_transition

        with pytest.raises(AppError) as exc_info:
            validate_execution_transition("cancelled", "running")
        assert exc_info.value.code == "INVALID_TRANSITION"

    def test_pending_to_cancelled_is_valid(self):
        """Execution can be cancelled from pending state."""
        from src.engine.state import validate_execution_transition

        validate_execution_transition("pending", "cancelled")

    def test_unknown_from_state_raises(self):
        """Unknown source state raises INVALID_TRANSITION."""
        from src.engine.state import validate_execution_transition

        with pytest.raises(AppError) as exc_info:
            validate_execution_transition("bogus", "running")
        assert exc_info.value.code == "INVALID_TRANSITION"


class TestStepTransitions:
    """Tests for step state transition validation."""

    def test_pending_to_queued_is_valid(self):
        """Step can transition from pending to queued."""
        from src.engine.state import validate_step_transition

        validate_step_transition("pending", "queued")

    def test_queued_to_running_is_valid(self):
        """Step can transition from queued to running."""
        from src.engine.state import validate_step_transition

        validate_step_transition("queued", "running")

    def test_running_to_completed_is_valid(self):
        """Step can transition from running to completed."""
        from src.engine.state import validate_step_transition

        validate_step_transition("running", "completed")

    def test_running_to_failed_is_valid(self):
        """Step can transition from running to failed."""
        from src.engine.state import validate_step_transition

        validate_step_transition("running", "failed")

    def test_pending_to_skipped_is_valid(self):
        """Step can be skipped directly from pending."""
        from src.engine.state import validate_step_transition

        validate_step_transition("pending", "skipped")

    def test_pending_to_completed_is_invalid(self):
        """Step cannot skip from pending directly to completed."""
        from src.engine.state import validate_step_transition

        with pytest.raises(AppError) as exc_info:
            validate_step_transition("pending", "completed")
        assert exc_info.value.code == "INVALID_TRANSITION"

    def test_completed_to_running_is_invalid(self):
        """Completed step cannot go back to running."""
        from src.engine.state import validate_step_transition

        with pytest.raises(AppError) as exc_info:
            validate_step_transition("completed", "running")
        assert exc_info.value.code == "INVALID_TRANSITION"

    def test_skipped_to_running_is_invalid(self):
        """Skipped step cannot go back to running."""
        from src.engine.state import validate_step_transition

        with pytest.raises(AppError) as exc_info:
            validate_step_transition("skipped", "running")
        assert exc_info.value.code == "INVALID_TRANSITION"

    def test_failed_to_queued_is_valid(self):
        """Failed step can be re-queued for retry."""
        from src.engine.state import validate_step_transition

        validate_step_transition("failed", "queued")

    def test_unknown_from_state_raises(self):
        """Unknown source state raises INVALID_TRANSITION."""
        from src.engine.state import validate_step_transition

        with pytest.raises(AppError) as exc_info:
            validate_step_transition("bogus", "running")
        assert exc_info.value.code == "INVALID_TRANSITION"


class TestTransitionExecution:
    """Tests for DB-level transition_execution function."""

    async def test_transition_execution_updates_status(self, db_session):
        """transition_execution updates the execution status in DB."""
        from src.db.models import Execution, Tenant, Workflow
        from src.engine.state import transition_execution

        tenant = Tenant(
            name="State Test Tenant",
            api_key_hash="hash",
            api_key_prefix="wae_live_state00001",
        )
        db_session.add(tenant)
        await db_session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="State WF",
            trigger_type="manual",
            steps=[{"id": "s1", "type": "http", "config": {}}],
        )
        db_session.add(workflow)
        await db_session.flush()

        execution = Execution(
            tenant_id=tenant.id,
            workflow_id=workflow.id,
            status="pending",
        )
        db_session.add(execution)
        await db_session.flush()

        await transition_execution(db_session, execution.id, "running")
        await db_session.refresh(execution)
        assert execution.status == "running"

    async def test_transition_execution_invalid_raises(self, db_session):
        """transition_execution raises AppError for invalid transitions."""
        from src.db.models import Execution, Tenant, Workflow
        from src.engine.state import transition_execution

        tenant = Tenant(
            name="State Test Tenant 2",
            api_key_hash="hash",
            api_key_prefix="wae_live_state00002",
        )
        db_session.add(tenant)
        await db_session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="State WF 2",
            trigger_type="manual",
            steps=[{"id": "s1", "type": "http", "config": {}}],
        )
        db_session.add(workflow)
        await db_session.flush()

        execution = Execution(
            tenant_id=tenant.id,
            workflow_id=workflow.id,
            status="completed",
        )
        db_session.add(execution)
        await db_session.flush()

        with pytest.raises(AppError) as exc_info:
            await transition_execution(db_session, execution.id, "running")
        assert exc_info.value.code == "INVALID_TRANSITION"

    async def test_transition_execution_not_found_raises(self, db_session):
        """transition_execution raises AppError when execution not found."""
        from src.engine.state import transition_execution
        from src.lib.utils import generate_uuid

        fake_id = generate_uuid()
        with pytest.raises(AppError) as exc_info:
            await transition_execution(db_session, fake_id, "running")
        assert exc_info.value.code == "NOT_FOUND"


class TestTransitionStep:
    """Tests for DB-level transition_step function."""

    async def test_transition_step_updates_status(self, db_session):
        """transition_step updates the step execution status in DB."""
        from src.db.models import Execution, StepExecution, Tenant, Workflow
        from src.engine.state import transition_step

        tenant = Tenant(
            name="Step State Tenant",
            api_key_hash="hash",
            api_key_prefix="wae_live_stepst001",
        )
        db_session.add(tenant)
        await db_session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="Step State WF",
            trigger_type="manual",
            steps=[{"id": "s1", "type": "http", "config": {}}],
        )
        db_session.add(workflow)
        await db_session.flush()

        execution = Execution(
            tenant_id=tenant.id,
            workflow_id=workflow.id,
            status="running",
        )
        db_session.add(execution)
        await db_session.flush()

        step_exec = StepExecution(
            tenant_id=tenant.id,
            execution_id=execution.id,
            step_id="s1",
            step_type="http",
            status="pending",
        )
        db_session.add(step_exec)
        await db_session.flush()

        await transition_step(db_session, step_exec.id, "queued")
        await db_session.refresh(step_exec)
        assert step_exec.status == "queued"

    async def test_transition_step_invalid_raises(self, db_session):
        """transition_step raises AppError for invalid transitions."""
        from src.db.models import Execution, StepExecution, Tenant, Workflow
        from src.engine.state import transition_step

        tenant = Tenant(
            name="Step State Tenant 2",
            api_key_hash="hash",
            api_key_prefix="wae_live_stepst002",
        )
        db_session.add(tenant)
        await db_session.flush()

        workflow = Workflow(
            tenant_id=tenant.id,
            name="Step State WF 2",
            trigger_type="manual",
            steps=[{"id": "s1", "type": "http", "config": {}}],
        )
        db_session.add(workflow)
        await db_session.flush()

        execution = Execution(
            tenant_id=tenant.id,
            workflow_id=workflow.id,
            status="running",
        )
        db_session.add(execution)
        await db_session.flush()

        step_exec = StepExecution(
            tenant_id=tenant.id,
            execution_id=execution.id,
            step_id="s1",
            step_type="http",
            status="completed",
        )
        db_session.add(step_exec)
        await db_session.flush()

        with pytest.raises(AppError) as exc_info:
            await transition_step(db_session, step_exec.id, "running")
        assert exc_info.value.code == "INVALID_TRANSITION"

    async def test_transition_step_not_found_raises(self, db_session):
        """transition_step raises AppError when step execution not found."""
        from src.engine.state import transition_step
        from src.lib.utils import generate_uuid

        fake_id = generate_uuid()
        with pytest.raises(AppError) as exc_info:
            await transition_step(db_session, fake_id, "queued")
        assert exc_info.value.code == "NOT_FOUND"
