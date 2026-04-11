"""Unit tests for execution logging service.

Tests record_execution_log() function that inserts structured
log entries into the execution_logs table, tenant-scoped.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Execution, ExecutionLog, Tenant, Workflow


@pytest.fixture
async def logging_tenant(db_session: AsyncSession):
    """Create a tenant for logging tests."""
    from src.tenants.service import register_tenant

    result = await register_tenant(name="Log Tenant", session=db_session)
    await db_session.flush()

    stmt = select(Tenant).where(Tenant.id == result.id)
    res = await db_session.execute(stmt)
    return res.scalar_one()


@pytest.fixture
async def logging_workflow(db_session: AsyncSession, logging_tenant):
    """Create a workflow for logging tests."""
    wf = Workflow(
        tenant_id=logging_tenant.id,
        name="Log Workflow",
        trigger_type="manual",
        trigger_config={},
        steps=[{"id": "s1", "type": "transform", "config": {}}],
        is_active=True,
    )
    db_session.add(wf)
    await db_session.flush()
    return wf


@pytest.fixture
async def logging_execution(db_session: AsyncSession, logging_tenant, logging_workflow):
    """Create an execution for logging tests."""
    ex = Execution(
        tenant_id=logging_tenant.id,
        workflow_id=logging_workflow.id,
        status="running",
        trigger_data={},
        context={},
    )
    db_session.add(ex)
    await db_session.flush()
    return ex


class TestRecordExecutionLog:
    """Tests for the record_execution_log service function."""

    async def test_record_info_log(self, db_session, logging_tenant, logging_execution):
        """Record an info-level log entry."""
        from src.engine.logging import record_execution_log

        log = await record_execution_log(
            session=db_session,
            tenant_id=logging_tenant.id,
            execution_id=logging_execution.id,
            level="info",
            message="Step started",
        )

        assert log.id is not None
        assert log.tenant_id == logging_tenant.id
        assert log.execution_id == logging_execution.id
        assert log.level == "info"
        assert log.message == "Step started"
        assert log.step_id is None
        assert log.data == {}

    async def test_record_log_with_step_id(
        self, db_session, logging_tenant, logging_execution
    ):
        """Record a log entry with step_id."""
        from src.engine.logging import record_execution_log

        log = await record_execution_log(
            session=db_session,
            tenant_id=logging_tenant.id,
            execution_id=logging_execution.id,
            level="info",
            message="Transform completed",
            step_id="step_1",
        )

        assert log.step_id == "step_1"

    async def test_record_log_with_data(
        self, db_session, logging_tenant, logging_execution
    ):
        """Record a log with extra JSONB data."""
        from src.engine.logging import record_execution_log

        extra = {"duration_ms": 42, "retries": 1}
        log = await record_execution_log(
            session=db_session,
            tenant_id=logging_tenant.id,
            execution_id=logging_execution.id,
            level="warn",
            message="Slow step",
            data=extra,
        )

        assert log.data == extra

    async def test_record_error_log(
        self, db_session, logging_tenant, logging_execution
    ):
        """Record an error-level log entry."""
        from src.engine.logging import record_execution_log

        log = await record_execution_log(
            session=db_session,
            tenant_id=logging_tenant.id,
            execution_id=logging_execution.id,
            level="error",
            message="Connection timeout",
            step_id="http_call",
            data={"url": "https://api.example.com"},
        )

        assert log.level == "error"
        assert log.step_id == "http_call"

    async def test_record_debug_log(
        self, db_session, logging_tenant, logging_execution
    ):
        """Record a debug-level log entry."""
        from src.engine.logging import record_execution_log

        log = await record_execution_log(
            session=db_session,
            tenant_id=logging_tenant.id,
            execution_id=logging_execution.id,
            level="debug",
            message="Context snapshot",
        )

        assert log.level == "debug"

    async def test_invalid_level_rejected(
        self, db_session, logging_tenant, logging_execution
    ):
        """Invalid log level raises ValueError."""
        from src.engine.logging import record_execution_log

        with pytest.raises(ValueError, match="Invalid log level"):
            await record_execution_log(
                session=db_session,
                tenant_id=logging_tenant.id,
                execution_id=logging_execution.id,
                level="critical",
                message="Should fail",
            )

    async def test_log_persisted_in_db(
        self, db_session, logging_tenant, logging_execution
    ):
        """Verify log is retrievable from the database."""
        from src.engine.logging import record_execution_log

        log = await record_execution_log(
            session=db_session,
            tenant_id=logging_tenant.id,
            execution_id=logging_execution.id,
            level="info",
            message="Persisted",
        )

        stmt = select(ExecutionLog).where(ExecutionLog.id == log.id)
        result = await db_session.execute(stmt)
        fetched = result.scalar_one()
        assert fetched.message == "Persisted"

    async def test_multiple_logs_same_execution(
        self, db_session, logging_tenant, logging_execution
    ):
        """Multiple logs can be recorded for the same execution."""
        from src.engine.logging import record_execution_log

        log1 = await record_execution_log(
            session=db_session,
            tenant_id=logging_tenant.id,
            execution_id=logging_execution.id,
            level="info",
            message="First",
        )
        log2 = await record_execution_log(
            session=db_session,
            tenant_id=logging_tenant.id,
            execution_id=logging_execution.id,
            level="info",
            message="Second",
        )

        assert log1.id != log2.id
        stmt = select(ExecutionLog).where(
            ExecutionLog.execution_id == logging_execution.id
        )
        result = await db_session.execute(stmt)
        logs = result.scalars().all()
        assert len(logs) >= 2
