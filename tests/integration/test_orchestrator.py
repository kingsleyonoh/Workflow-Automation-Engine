"""Integration tests for the execution orchestrator.

Tests start_execution, on_step_complete, and on_step_failed against
real PostgreSQL to verify execution lifecycle management.
"""

from sqlalchemy import select

from src.db.models import StepExecution, Tenant, Workflow


def _simple_workflow_steps() -> list[dict]:
    """Single transform step for simple orchestrator tests."""
    return [
        {
            "id": "transform_1",
            "type": "transform",
            "config": {"expression": "{{ trigger.payload.name | upper }}"},
        }
    ]


def _two_step_workflow() -> list[dict]:
    """Two steps: transform_1 -> transform_2 (depends on transform_1)."""
    return [
        {
            "id": "transform_1",
            "type": "transform",
            "config": {"expression": "{{ trigger.payload.name | upper }}"},
        },
        {
            "id": "transform_2",
            "type": "transform",
            "config": {
                "expression": "Result: {{ steps.transform_1.output.result }}"
            },
            "depends_on": ["transform_1"],
        },
    ]


def _condition_workflow_steps() -> list[dict]:
    """Condition step with true/false branches."""
    return [
        {
            "id": "check",
            "type": "condition",
            "config": {
                "expression": "{{ trigger.payload.go }}",
                "true_branch": ["on_true"],
                "false_branch": ["on_false"],
            },
        },
        {
            "id": "on_true",
            "type": "transform",
            "config": {"expression": "true path"},
            "depends_on": ["check"],
        },
        {
            "id": "on_false",
            "type": "transform",
            "config": {"expression": "false path"},
            "depends_on": ["check"],
        },
    ]


def _retry_workflow_steps() -> list[dict]:
    """Single step with retry configuration."""
    return [
        {
            "id": "flaky",
            "type": "transform",
            "config": {"expression": "{{ nonexistent }}"},
            "retry": {"max_attempts": 2, "delay_seconds": 0},
        }
    ]


async def _create_test_tenant_and_workflow(
    db_session, steps, name="Orch Test Tenant", prefix_suffix="001"
):
    """Helper to create tenant + workflow in DB."""
    tenant = Tenant(
        name=name,
        api_key_hash="hash",
        api_key_prefix=f"wae_live_orch{prefix_suffix}",
    )
    db_session.add(tenant)
    await db_session.flush()

    workflow = Workflow(
        tenant_id=tenant.id,
        name="Orch Workflow",
        trigger_type="webhook",
        steps=steps,
    )
    db_session.add(workflow)
    await db_session.flush()

    return tenant, workflow


class TestStartExecution:
    """Tests for orchestrator.start_execution."""

    async def test_creates_execution_record(self, db_session):
        """start_execution creates an execution record for the workflow."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _simple_workflow_steps(), prefix_suffix="se001"
        )
        trigger_data = {"payload": {"name": "alice"}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        # After synchronous execution the simple workflow completes
        assert execution.status in ("running", "completed")
        assert execution.tenant_id == tenant.id
        assert execution.workflow_id == workflow.id

    async def test_creates_step_execution_records(self, db_session):
        """start_execution creates step_execution records for each step."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _two_step_workflow(), prefix_suffix="se002"
        )
        trigger_data = {"payload": {"name": "bob"}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        stmt = select(StepExecution).where(
            StepExecution.execution_id == execution.id
        )
        result = await db_session.execute(stmt)
        step_execs = list(result.scalars().all())

        assert len(step_execs) == 2
        step_ids = {se.step_id for se in step_execs}
        assert step_ids == {"transform_1", "transform_2"}

    async def test_sets_trigger_data_in_context(self, db_session):
        """start_execution stores trigger data in execution context."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _simple_workflow_steps(), prefix_suffix="se003"
        )
        trigger_data = {"payload": {"name": "charlie"}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        assert "trigger" in execution.context
        assert execution.context["trigger"]["payload"]["name"] == "charlie"

    async def test_executes_simple_workflow_to_completion(self, db_session):
        """start_execution runs a simple workflow to completed status."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _simple_workflow_steps(), prefix_suffix="se004"
        )
        trigger_data = {"payload": {"name": "diana"}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "completed"

    async def test_executes_chain_workflow_in_order(self, db_session):
        """start_execution runs a two-step chain in dependency order."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _two_step_workflow(), prefix_suffix="se005"
        )
        trigger_data = {"payload": {"name": "eve"}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "completed"

        # Verify step outputs merged into context
        assert "steps" in execution.context
        assert "transform_1" in execution.context["steps"]
        assert "transform_2" in execution.context["steps"]
        assert execution.context["steps"]["transform_1"]["output"]["result"] == "EVE"

    async def test_step_execution_statuses_after_completion(self, db_session):
        """All step executions are marked completed after successful run."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _two_step_workflow(), prefix_suffix="se006"
        )
        trigger_data = {"payload": {"name": "frank"}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        stmt = select(StepExecution).where(
            StepExecution.execution_id == execution.id
        )
        result = await db_session.execute(stmt)
        step_execs = list(result.scalars().all())

        for se in step_execs:
            assert se.status == "completed"


class TestConditionStep:
    """Tests for condition step handling in the orchestrator."""

    async def test_true_branch_executes(self, db_session):
        """Condition step evaluating to true runs the true branch."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _condition_workflow_steps(), prefix_suffix="cs001"
        )
        trigger_data = {"payload": {"go": "true"}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "completed"

        stmt = select(StepExecution).where(
            StepExecution.execution_id == execution.id
        )
        result = await db_session.execute(stmt)
        step_execs = {se.step_id: se.status for se in result.scalars().all()}

        assert step_execs["check"] == "completed"
        assert step_execs["on_true"] == "completed"
        assert step_execs["on_false"] == "skipped"

    async def test_false_branch_skips_true(self, db_session):
        """Condition step evaluating to false skips the true branch."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _condition_workflow_steps(), prefix_suffix="cs002"
        )
        trigger_data = {"payload": {"go": ""}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "completed"

        stmt = select(StepExecution).where(
            StepExecution.execution_id == execution.id
        )
        result = await db_session.execute(stmt)
        step_execs = {se.step_id: se.status for se in result.scalars().all()}

        assert step_execs["check"] == "completed"
        assert step_execs["on_true"] == "skipped"
        assert step_execs["on_false"] == "completed"


class TestStepFailure:
    """Tests for step failure and retry handling."""

    async def test_failed_step_marks_execution_failed(self, db_session):
        """When a step exhausts retries, execution is marked failed."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _retry_workflow_steps(), prefix_suffix="sf001"
        )
        trigger_data = {"payload": {}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "failed"

    async def test_failed_step_has_error_recorded(self, db_session):
        """Failed step execution has an error message recorded."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _retry_workflow_steps(), prefix_suffix="sf002"
        )
        trigger_data = {"payload": {}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        stmt = select(StepExecution).where(
            StepExecution.execution_id == execution.id,
            StepExecution.step_id == "flaky",
        )
        result = await db_session.execute(stmt)
        step_exec = result.scalar_one()

        assert step_exec.status == "failed"
        assert step_exec.error is not None


class TestTenantIsolation:
    """Tests for tenant isolation in execution orchestrator."""

    async def test_execution_has_correct_tenant_id(self, db_session):
        """Execution record is scoped to the correct tenant."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _simple_workflow_steps(), prefix_suffix="ti001"
        )
        trigger_data = {"payload": {"name": "test"}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        assert execution.tenant_id == tenant.id

    async def test_step_executions_have_correct_tenant_id(self, db_session):
        """Step execution records are scoped to the correct tenant."""
        from src.engine.orchestrator import start_execution

        tenant, workflow = await _create_test_tenant_and_workflow(
            db_session, _simple_workflow_steps(), prefix_suffix="ti002"
        )
        trigger_data = {"payload": {"name": "test"}}

        execution = await start_execution(
            db_session, workflow, trigger_data, tenant.id
        )

        stmt = select(StepExecution).where(
            StepExecution.execution_id == execution.id
        )
        result = await db_session.execute(stmt)
        for se in result.scalars().all():
            assert se.tenant_id == tenant.id
