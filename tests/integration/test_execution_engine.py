"""Integration tests for the execution engine with real PostgreSQL and Redis.

Tests the full execution pipeline: create workflow -> trigger execution ->
verify step completions -> check final state. Uses real PostgreSQL
(port 5435) and real Redis (port 6380) for full integration coverage.
"""

import uuid

import pytest
from sqlalchemy import select

from src.db.models import StepExecution, Tenant, Workflow
from src.engine.orchestrator import start_execution

pytestmark = pytest.mark.integration


async def _create_tenant(db_session, suffix: str = "001") -> Tenant:
    """Create a test tenant in the database."""
    tenant = Tenant(
        name=f"Engine Test Tenant {suffix}",
        api_key_hash="hash_placeholder",
        api_key_prefix=f"wae_live_eng{suffix}",
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _create_workflow(
    db_session, tenant_id: uuid.UUID, steps: list[dict], name: str = "Test Workflow"
) -> Workflow:
    """Create a test workflow in the database."""
    workflow = Workflow(
        tenant_id=tenant_id,
        name=name,
        trigger_type="manual",
        steps=steps,
        is_active=True,
    )
    db_session.add(workflow)
    await db_session.flush()
    return workflow


class TestFullExecutionPipeline:
    """Tests for the complete execution pipeline with real DB."""

    async def test_single_transform_step_completes(self, db_session):
        """Single transform step executes and completes successfully."""
        tenant = await _create_tenant(db_session, "pipe001")
        steps = [
            {
                "id": "greet",
                "type": "transform",
                "config": {"expression": "Hello {{ trigger.payload.name }}!"},
            }
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {"name": "World"}}, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "completed"
        assert execution.context["steps"]["greet"]["output"]["result"] == "Hello World!"

    async def test_multi_step_chain_executes_in_order(self, db_session):
        """Chain of transform steps executes in dependency order."""
        tenant = await _create_tenant(db_session, "pipe002")
        steps = [
            {
                "id": "step_a",
                "type": "transform",
                "config": {"expression": "{{ trigger.payload.value | upper }}"},
            },
            {
                "id": "step_b",
                "type": "transform",
                "config": {"expression": "processed: {{ steps.step_a.output.result }}"},
                "depends_on": ["step_a"],
            },
            {
                "id": "step_c",
                "type": "transform",
                "config": {"expression": "final: {{ steps.step_b.output.result }}"},
                "depends_on": ["step_b"],
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {"value": "hello"}}, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "completed"
        assert execution.context["steps"]["step_a"]["output"]["result"] == "HELLO"
        step_b_result = execution.context["steps"]["step_b"]["output"]["result"]
        assert "processed: HELLO" in step_b_result
        assert "final:" in execution.context["steps"]["step_c"]["output"]["result"]

    async def test_condition_step_true_branch(self, db_session):
        """Condition step evaluating true executes only the true branch."""
        tenant = await _create_tenant(db_session, "pipe003")
        steps = [
            {
                "id": "check",
                "type": "condition",
                "config": {
                    "expression": "{{ trigger.payload.enabled }}",
                    "true_branch": ["on_yes"],
                    "false_branch": ["on_no"],
                },
            },
            {
                "id": "on_yes",
                "type": "transform",
                "config": {"expression": "yes path"},
                "depends_on": ["check"],
            },
            {
                "id": "on_no",
                "type": "transform",
                "config": {"expression": "no path"},
                "depends_on": ["check"],
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {"enabled": "true"}}, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "completed"

        stmt = select(StepExecution).where(StepExecution.execution_id == execution.id)
        result = await db_session.execute(stmt)
        step_map = {se.step_id: se.status for se in result.scalars().all()}

        assert step_map["check"] == "completed"
        assert step_map["on_yes"] == "completed"
        assert step_map["on_no"] == "skipped"

    async def test_condition_step_false_branch(self, db_session):
        """Condition step evaluating false executes only the false branch."""
        tenant = await _create_tenant(db_session, "pipe004")
        steps = [
            {
                "id": "check",
                "type": "condition",
                "config": {
                    "expression": "{{ trigger.payload.enabled }}",
                    "true_branch": ["yes_step"],
                    "false_branch": ["no_step"],
                },
            },
            {
                "id": "yes_step",
                "type": "transform",
                "config": {"expression": "yes"},
                "depends_on": ["check"],
            },
            {
                "id": "no_step",
                "type": "transform",
                "config": {"expression": "no"},
                "depends_on": ["check"],
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {"enabled": ""}}, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "completed"

        stmt = select(StepExecution).where(StepExecution.execution_id == execution.id)
        result = await db_session.execute(stmt)
        step_map = {se.step_id: se.status for se in result.scalars().all()}

        assert step_map["check"] == "completed"
        assert step_map["yes_step"] == "skipped"
        assert step_map["no_step"] == "completed"


class TestStepExecutionRecords:
    """Tests for step execution record creation and state transitions."""

    async def test_step_executions_created_for_each_step(self, db_session):
        """Each workflow step gets a step_execution record."""
        tenant = await _create_tenant(db_session, "rec001")
        steps = [
            {
                "id": "s1",
                "type": "transform",
                "config": {"expression": "one"},
            },
            {
                "id": "s2",
                "type": "transform",
                "config": {"expression": "two"},
                "depends_on": ["s1"],
            },
            {
                "id": "s3",
                "type": "transform",
                "config": {"expression": "three"},
                "depends_on": ["s2"],
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        stmt = select(StepExecution).where(StepExecution.execution_id == execution.id)
        result = await db_session.execute(stmt)
        step_execs = list(result.scalars().all())

        assert len(step_execs) == 3
        step_ids = {se.step_id for se in step_execs}
        assert step_ids == {"s1", "s2", "s3"}

    async def test_all_steps_completed_after_success(self, db_session):
        """All step executions are marked completed on success."""
        tenant = await _create_tenant(db_session, "rec002")
        steps = [
            {
                "id": "a",
                "type": "transform",
                "config": {"expression": "a"},
            },
            {
                "id": "b",
                "type": "transform",
                "config": {"expression": "b"},
                "depends_on": ["a"],
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        stmt = select(StepExecution).where(StepExecution.execution_id == execution.id)
        result = await db_session.execute(stmt)
        for se in result.scalars().all():
            assert se.status == "completed"

    async def test_step_output_data_persisted(self, db_session):
        """Step execution output_data is persisted to DB."""
        tenant = await _create_tenant(db_session, "rec003")
        steps = [
            {
                "id": "calc",
                "type": "transform",
                "config": {"expression": "computed"},
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        stmt = select(StepExecution).where(
            StepExecution.execution_id == execution.id,
            StepExecution.step_id == "calc",
        )
        result = await db_session.execute(stmt)
        step_exec = result.scalar_one()

        assert step_exec.output_data is not None
        assert step_exec.output_data["result"] == "computed"

    async def test_step_tenant_id_matches_execution(self, db_session):
        """Step execution tenant_id matches the parent execution."""
        tenant = await _create_tenant(db_session, "rec004")
        steps = [
            {
                "id": "x",
                "type": "transform",
                "config": {"expression": "test"},
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        stmt = select(StepExecution).where(StepExecution.execution_id == execution.id)
        result = await db_session.execute(stmt)
        for se in result.scalars().all():
            assert se.tenant_id == tenant.id


class TestFailureAndRetry:
    """Tests for step failure and retry with real DB state transitions."""

    async def test_failed_step_marks_execution_failed(self, db_session):
        """Step failure after exhausting retries marks execution failed."""
        tenant = await _create_tenant(db_session, "fail001")
        steps = [
            {
                "id": "bad_step",
                "type": "transform",
                "config": {"expression": "{{ undefined_var.nested }}"},
                "retry": {"max_attempts": 1, "delay_seconds": 0},
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "failed"
        assert execution.error is not None

    async def test_retry_exhaustion_records_error_on_step(self, db_session):
        """Failed step has error message recorded after retry exhaustion."""
        tenant = await _create_tenant(db_session, "fail002")
        steps = [
            {
                "id": "flaky",
                "type": "transform",
                "config": {"expression": "{{ missing_context.value }}"},
                "retry": {"max_attempts": 2, "delay_seconds": 0},
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        stmt = select(StepExecution).where(
            StepExecution.execution_id == execution.id,
            StepExecution.step_id == "flaky",
        )
        result = await db_session.execute(stmt)
        step_exec = result.scalar_one()

        assert step_exec.status == "failed"
        assert step_exec.error is not None

    async def test_downstream_steps_not_executed_after_failure(self, db_session):
        """Steps after a failed step are not executed."""
        tenant = await _create_tenant(db_session, "fail003")
        steps = [
            {
                "id": "bad",
                "type": "transform",
                "config": {"expression": "{{ nope.value }}"},
                "retry": {"max_attempts": 1, "delay_seconds": 0},
            },
            {
                "id": "downstream",
                "type": "transform",
                "config": {"expression": "should not run"},
                "depends_on": ["bad"],
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.status == "failed"

        stmt = select(StepExecution).where(
            StepExecution.execution_id == execution.id,
            StepExecution.step_id == "downstream",
        )
        result = await db_session.execute(stmt)
        downstream = result.scalar_one()
        assert downstream.status == "pending"


class TestContextMerging:
    """Tests for execution context merging during pipeline execution."""

    async def test_trigger_data_in_context(self, db_session):
        """Trigger data is stored in execution context."""
        tenant = await _create_tenant(db_session, "ctx001")
        steps = [
            {
                "id": "s",
                "type": "transform",
                "config": {"expression": "{{ trigger.payload.key }}"},
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {"key": "value123"}}, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.context["trigger"]["payload"]["key"] == "value123"

    async def test_step_outputs_accumulated_in_context(self, db_session):
        """Multiple step outputs are accumulated in execution context."""
        tenant = await _create_tenant(db_session, "ctx002")
        steps = [
            {
                "id": "first",
                "type": "transform",
                "config": {"expression": "result_1"},
            },
            {
                "id": "second",
                "type": "transform",
                "config": {"expression": "result_2"},
                "depends_on": ["first"],
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        await db_session.refresh(execution)
        steps_ctx = execution.context["steps"]
        assert "first" in steps_ctx
        assert "second" in steps_ctx
        assert steps_ctx["first"]["output"]["result"] == "result_1"
        assert steps_ctx["second"]["output"]["result"] == "result_2"

    async def test_later_step_can_reference_earlier_output(self, db_session):
        """Later step can reference earlier step output via Jinja2."""
        tenant = await _create_tenant(db_session, "ctx003")
        steps = [
            {
                "id": "produce",
                "type": "transform",
                "config": {"expression": "DATA"},
            },
            {
                "id": "consume",
                "type": "transform",
                "config": {"expression": "got: {{ steps.produce.output.result }}"},
                "depends_on": ["produce"],
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        await db_session.refresh(execution)
        assert execution.context["steps"]["consume"]["output"]["result"] == "got: DATA"


class TestTenantIsolationInEngine:
    """Tests for tenant isolation in the execution engine."""

    async def test_execution_bound_to_correct_tenant(self, db_session):
        """Execution is bound to the tenant that created it."""
        tenant = await _create_tenant(db_session, "iso001")
        steps = [
            {
                "id": "s",
                "type": "transform",
                "config": {"expression": "test"},
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        assert execution.tenant_id == tenant.id

    async def test_two_tenants_independent_executions(self, db_session):
        """Two tenants can execute workflows independently."""
        tenant_a = await _create_tenant(db_session, "iso002a")
        tenant_b = await _create_tenant(db_session, "iso002b")

        steps = [
            {
                "id": "s",
                "type": "transform",
                "config": {"expression": "hello"},
            },
        ]

        wf_a = await _create_workflow(db_session, tenant_a.id, steps, name="WF A")
        wf_b = await _create_workflow(db_session, tenant_b.id, steps, name="WF B")

        exec_a = await start_execution(db_session, wf_a, {"payload": {}}, tenant_a.id)
        exec_b = await start_execution(db_session, wf_b, {"payload": {}}, tenant_b.id)

        assert exec_a.tenant_id == tenant_a.id
        assert exec_b.tenant_id == tenant_b.id
        assert exec_a.id != exec_b.id

        # Both should complete independently
        await db_session.refresh(exec_a)
        await db_session.refresh(exec_b)
        assert exec_a.status == "completed"
        assert exec_b.status == "completed"


class TestArqDispatch:
    """Tests for arq job dispatch with real Redis."""

    async def test_dispatch_step_enqueues_job(self, db_session, redis_client):
        """dispatch_step enqueues a job to the arq queue in Redis."""
        from src.queue.tasks import dispatch_step

        tenant = await _create_tenant(db_session, "arq001")
        steps = [
            {
                "id": "s",
                "type": "transform",
                "config": {"expression": "test"},
            },
        ]
        workflow = await _create_workflow(db_session, tenant.id, steps)

        execution = await start_execution(
            db_session, workflow, {"payload": {}}, tenant.id
        )

        stmt = select(StepExecution).where(StepExecution.execution_id == execution.id)
        result = await db_session.execute(stmt)
        step_exec = result.scalars().first()

        # Dispatch to arq queue
        await dispatch_step(
            redis_client,
            str(step_exec.id),
            str(execution.id),
            str(tenant.id),
        )

        # Verify job was enqueued in Redis
        # arq uses sorted set for queued jobs
        keys = await redis_client.keys("arq:*")
        assert len(keys) > 0
