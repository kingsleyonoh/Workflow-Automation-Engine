"""Unit tests for background cleanup and pruning jobs.

Tests stale execution cleanup, execution log pruning, and webhook
delivery pruning — all hitting real PostgreSQL via db_session.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    Execution,
    ExecutionLog,
    StepExecution,
    Tenant,
    WebhookDelivery,
    Workflow,
)


@pytest.fixture
async def bg_tenant(db_session: AsyncSession) -> Tenant:
    """Create a tenant for background job tests."""
    tenant = Tenant(
        name="BG Job Tenant",
        api_key_hash="bg_hash_000",
        api_key_prefix="wae_bg_",
        is_active=True,
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


@pytest.fixture
async def bg_workflow(db_session: AsyncSession, bg_tenant: Tenant) -> Workflow:
    """Create a workflow for background job tests."""
    workflow = Workflow(
        tenant_id=bg_tenant.id,
        name="BG Test Workflow",
        trigger_type="webhook",
        steps=[{"id": "step1", "type": "http", "config": {}}],
    )
    db_session.add(workflow)
    await db_session.flush()
    return workflow


class TestCleanupStaleExecutions:
    """Tests for the stale execution cleanup job."""

    async def test_marks_stale_running_execution_as_failed(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Execution running for >1h is marked as failed."""
        from src.queue.jobs import cleanup_stale_executions

        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="running",
            started_at=two_hours_ago,
        )
        db_session.add(execution)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await cleanup_stale_executions(ctx)

        await db_session.refresh(execution)
        assert execution.status == "failed"
        assert "timed out" in execution.error.lower()

    async def test_does_not_touch_recent_running_execution(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Execution running for <1h is not affected."""
        from src.queue.jobs import cleanup_stale_executions

        ten_minutes_ago = datetime.now(UTC) - timedelta(minutes=10)
        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="running",
            started_at=ten_minutes_ago,
        )
        db_session.add(execution)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await cleanup_stale_executions(ctx)

        await db_session.refresh(execution)
        assert execution.status == "running"

    async def test_does_not_touch_completed_execution(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Completed execution is not affected even if old."""
        from src.queue.jobs import cleanup_stale_executions

        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="completed",
            started_at=two_hours_ago,
            completed_at=two_hours_ago + timedelta(minutes=5),
        )
        db_session.add(execution)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await cleanup_stale_executions(ctx)

        await db_session.refresh(execution)
        assert execution.status == "completed"

    async def test_marks_pending_steps_of_stale_execution_as_failed(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Pending steps belonging to stale execution are marked failed."""
        from src.queue.jobs import cleanup_stale_executions

        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="running",
            started_at=two_hours_ago,
        )
        db_session.add(execution)
        await db_session.flush()

        step = StepExecution(
            tenant_id=bg_tenant.id,
            execution_id=execution.id,
            step_id="step1",
            step_type="http",
            status="pending",
        )
        db_session.add(step)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await cleanup_stale_executions(ctx)

        await db_session.refresh(step)
        assert step.status == "failed"
        assert "stale" in step.error.lower()

    async def test_marks_running_steps_of_stale_execution_as_failed(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Running steps belonging to stale execution are marked failed."""
        from src.queue.jobs import cleanup_stale_executions

        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="running",
            started_at=two_hours_ago,
        )
        db_session.add(execution)
        await db_session.flush()

        step = StepExecution(
            tenant_id=bg_tenant.id,
            execution_id=execution.id,
            step_id="step1",
            step_type="http",
            status="running",
            started_at=two_hours_ago,
        )
        db_session.add(step)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await cleanup_stale_executions(ctx)

        await db_session.refresh(step)
        assert step.status == "failed"
        assert "stale" in step.error.lower()

    async def test_does_not_touch_completed_steps(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Completed steps of stale execution are not modified."""
        from src.queue.jobs import cleanup_stale_executions

        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="running",
            started_at=two_hours_ago,
        )
        db_session.add(execution)
        await db_session.flush()

        step = StepExecution(
            tenant_id=bg_tenant.id,
            execution_id=execution.id,
            step_id="step1",
            step_type="http",
            status="completed",
            started_at=two_hours_ago,
            completed_at=two_hours_ago + timedelta(minutes=1),
        )
        db_session.add(step)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await cleanup_stale_executions(ctx)

        await db_session.refresh(step)
        assert step.status == "completed"

    async def test_processes_multiple_stale_executions(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Multiple stale executions are all marked failed."""
        from src.queue.jobs import cleanup_stale_executions

        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        execs = []
        for _ in range(3):
            ex = Execution(
                tenant_id=bg_tenant.id,
                workflow_id=bg_workflow.id,
                status="running",
                started_at=two_hours_ago,
            )
            db_session.add(ex)
            execs.append(ex)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await cleanup_stale_executions(ctx)

        for ex in execs:
            await db_session.refresh(ex)
            assert ex.status == "failed"

    async def test_sets_completed_at_on_stale_execution(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Stale execution gets completed_at set when marked failed."""
        from src.queue.jobs import cleanup_stale_executions

        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="running",
            started_at=two_hours_ago,
        )
        db_session.add(execution)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await cleanup_stale_executions(ctx)

        await db_session.refresh(execution)
        assert execution.completed_at is not None


class TestPruneExecutionLogs:
    """Tests for execution log pruning job."""

    async def test_deletes_logs_older_than_30_days(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Execution logs older than 30 days are deleted."""
        from src.queue.jobs import prune_execution_logs

        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="completed",
        )
        db_session.add(execution)
        await db_session.flush()

        # Create an old log (45 days ago)
        old_log = ExecutionLog(
            tenant_id=bg_tenant.id,
            execution_id=execution.id,
            level="info",
            message="old log entry",
        )
        db_session.add(old_log)
        await db_session.flush()

        # Manually backdate using raw SQL
        await db_session.execute(
            text("UPDATE execution_logs SET created_at = :dt WHERE id = :id"),
            {"dt": datetime.now(UTC) - timedelta(days=45), "id": old_log.id},
        )
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await prune_execution_logs(ctx)

        result = await db_session.execute(
            select(ExecutionLog).where(ExecutionLog.id == old_log.id)
        )
        assert result.scalar_one_or_none() is None

    async def test_keeps_recent_logs(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Execution logs younger than 30 days are kept."""
        from src.queue.jobs import prune_execution_logs

        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="completed",
        )
        db_session.add(execution)
        await db_session.flush()

        recent_log = ExecutionLog(
            tenant_id=bg_tenant.id,
            execution_id=execution.id,
            level="info",
            message="recent log entry",
        )
        db_session.add(recent_log)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await prune_execution_logs(ctx)

        result = await db_session.execute(
            select(ExecutionLog).where(ExecutionLog.id == recent_log.id)
        )
        assert result.scalar_one_or_none() is not None

    async def test_deletes_multiple_old_logs(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Multiple old logs are all deleted in one pass."""
        from src.queue.jobs import prune_execution_logs

        execution = Execution(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            status="completed",
        )
        db_session.add(execution)
        await db_session.flush()

        log_ids = []
        for i in range(5):
            log = ExecutionLog(
                tenant_id=bg_tenant.id,
                execution_id=execution.id,
                level="info",
                message=f"old log {i}",
            )
            db_session.add(log)
            await db_session.flush()
            log_ids.append(log.id)

        # Backdate all logs
        for log_id in log_ids:
            await db_session.execute(
                text("UPDATE execution_logs SET created_at = :dt WHERE id = :id"),
                {"dt": datetime.now(UTC) - timedelta(days=40), "id": log_id},
            )
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await prune_execution_logs(ctx)

        result = await db_session.execute(
            select(ExecutionLog).where(ExecutionLog.id.in_(log_ids))
        )
        assert len(result.scalars().all()) == 0


class TestPruneWebhookDeliveries:
    """Tests for webhook delivery pruning job."""

    async def test_deletes_deliveries_older_than_7_days(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Webhook deliveries older than 7 days are deleted."""
        from src.queue.jobs import prune_webhook_deliveries

        delivery = WebhookDelivery(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            method="POST",
            headers={},
            payload={"test": True},
        )
        db_session.add(delivery)
        await db_session.flush()

        # Backdate to 10 days ago
        await db_session.execute(
            text("UPDATE webhook_deliveries SET created_at = :dt WHERE id = :id"),
            {"dt": datetime.now(UTC) - timedelta(days=10), "id": delivery.id},
        )
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await prune_webhook_deliveries(ctx)

        result = await db_session.execute(
            select(WebhookDelivery).where(WebhookDelivery.id == delivery.id)
        )
        assert result.scalar_one_or_none() is None

    async def test_keeps_recent_deliveries(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Webhook deliveries younger than 7 days are kept."""
        from src.queue.jobs import prune_webhook_deliveries

        delivery = WebhookDelivery(
            tenant_id=bg_tenant.id,
            workflow_id=bg_workflow.id,
            method="POST",
            headers={},
            payload={"test": True},
        )
        db_session.add(delivery)
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await prune_webhook_deliveries(ctx)

        result = await db_session.execute(
            select(WebhookDelivery).where(WebhookDelivery.id == delivery.id)
        )
        assert result.scalar_one_or_none() is not None

    async def test_deletes_multiple_old_deliveries(
        self, db_session: AsyncSession, bg_tenant: Tenant, bg_workflow: Workflow
    ):
        """Multiple old deliveries are all deleted in one pass."""
        from src.queue.jobs import prune_webhook_deliveries

        delivery_ids = []
        for i in range(4):
            d = WebhookDelivery(
                tenant_id=bg_tenant.id,
                workflow_id=bg_workflow.id,
                method="POST",
                headers={},
                payload={"n": i},
            )
            db_session.add(d)
            await db_session.flush()
            delivery_ids.append(d.id)

        for d_id in delivery_ids:
            await db_session.execute(
                text("UPDATE webhook_deliveries SET created_at = :dt WHERE id = :id"),
                {"dt": datetime.now(UTC) - timedelta(days=14), "id": d_id},
            )
        await db_session.flush()

        ctx = {"db_session_factory": lambda: SessionCtx(db_session)}
        await prune_webhook_deliveries(ctx)

        result = await db_session.execute(
            select(WebhookDelivery).where(WebhookDelivery.id.in_(delivery_ids))
        )
        assert len(result.scalars().all()) == 0


class TestCronJobRegistration:
    """Tests that background jobs are registered in WorkerSettings."""

    def test_worker_has_cron_jobs(self):
        """WorkerSettings has a cron_jobs list."""
        from src.queue.worker import WorkerSettings

        assert hasattr(WorkerSettings, "cron_jobs")
        assert isinstance(WorkerSettings.cron_jobs, list)

    def test_cron_jobs_include_stale_cleanup(self):
        """Stale execution cleanup is registered as a cron job."""
        from src.queue.worker import WorkerSettings

        names = [j.name for j in WorkerSettings.cron_jobs]
        assert any("cleanup_stale_executions" in n for n in names)

    def test_cron_jobs_include_log_pruning(self):
        """Execution log pruning is registered as a cron job."""
        from src.queue.worker import WorkerSettings

        names = [j.name for j in WorkerSettings.cron_jobs]
        assert any("prune_execution_logs" in n for n in names)

    def test_cron_jobs_include_webhook_pruning(self):
        """Webhook delivery pruning is registered as a cron job."""
        from src.queue.worker import WorkerSettings

        names = [j.name for j in WorkerSettings.cron_jobs]
        assert any("prune_webhook_deliveries" in n for n in names)

    def test_stale_cleanup_runs_hourly(self):
        """Stale execution cleanup runs every hour."""
        from src.queue.worker import WorkerSettings

        for job in WorkerSettings.cron_jobs:
            if "cleanup_stale_executions" in job.name:
                # Hourly = minute=0, hour unrestricted (None)
                assert job.minute == 0
                assert job.hour is None
                return
        pytest.fail("cleanup_stale_executions not found")

    def test_log_pruning_runs_daily_2am(self):
        """Execution log pruning runs daily at 2am UTC."""
        from src.queue.worker import WorkerSettings

        for job in WorkerSettings.cron_jobs:
            if "prune_execution_logs" in job.name:
                assert job.hour == 2
                assert job.minute == 0
                return
        pytest.fail("prune_execution_logs not found")

    def test_webhook_pruning_runs_daily_3am(self):
        """Webhook delivery pruning runs daily at 3am UTC."""
        from src.queue.worker import WorkerSettings

        for job in WorkerSettings.cron_jobs:
            if "prune_webhook_deliveries" in job.name:
                assert job.hour == 3
                assert job.minute == 0
                return
        pytest.fail("prune_webhook_deliveries not found")


# Helper: context manager adapter for passing db_session to jobs
class SessionCtx:  # noqa: N801
    """Async context manager wrapping an existing session for job tests."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *args):
        pass
