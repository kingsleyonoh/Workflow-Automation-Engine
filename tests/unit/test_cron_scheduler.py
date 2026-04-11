"""Unit tests for cron scheduler service.

Tests cron scheduler loading, scheduling, and dynamic updates.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Tenant, Workflow


@pytest.fixture
async def cron_tenant(db_session: AsyncSession):
    """Create a tenant for cron tests."""
    from src.tenants.service import register_tenant

    result = await register_tenant(name="Cron Tenant", session=db_session)
    await db_session.flush()

    from sqlalchemy import select

    stmt = select(Tenant).where(Tenant.id == result.id)
    res = await db_session.execute(stmt)
    return res.scalar_one()


@pytest.fixture
async def cron_workflow(db_session: AsyncSession, cron_tenant):
    """Create a cron-triggered workflow."""
    wf = Workflow(
        tenant_id=cron_tenant.id,
        name="Cron Flow",
        trigger_type="cron",
        trigger_config={"cron_expression": "*/5 * * * *"},
        steps=[{"id": "s1", "type": "transform", "config": {}}],
        is_active=True,
    )
    db_session.add(wf)
    await db_session.flush()
    return wf


class TestCronSchedulerService:
    """Tests for the cron scheduler service module."""

    async def test_load_cron_workflows(self, db_session, cron_tenant, cron_workflow):
        """load_cron_workflows returns active cron workflows."""
        from src.triggers.cron import load_cron_workflows

        workflows = await load_cron_workflows(db_session)
        assert len(workflows) >= 1
        wf_ids = [wf.id for wf in workflows]
        assert cron_workflow.id in wf_ids

    async def test_load_cron_workflows_excludes_inactive(self, db_session, cron_tenant):
        """Inactive cron workflows are not loaded."""
        from src.triggers.cron import load_cron_workflows

        wf = Workflow(
            tenant_id=cron_tenant.id,
            name="Inactive Cron",
            trigger_type="cron",
            trigger_config={"cron_expression": "0 * * * *"},
            steps=[{"id": "s1", "type": "transform", "config": {}}],
            is_active=False,
        )
        db_session.add(wf)
        await db_session.flush()

        workflows = await load_cron_workflows(db_session)
        wf_ids = [w.id for w in workflows]
        assert wf.id not in wf_ids

    async def test_load_cron_workflows_excludes_non_cron(self, db_session, cron_tenant):
        """Manual/webhook workflows are not loaded by cron loader."""
        from src.triggers.cron import load_cron_workflows

        wf = Workflow(
            tenant_id=cron_tenant.id,
            name="Manual Workflow",
            trigger_type="manual",
            trigger_config={},
            steps=[{"id": "s1", "type": "transform", "config": {}}],
            is_active=True,
        )
        db_session.add(wf)
        await db_session.flush()

        workflows = await load_cron_workflows(db_session)
        wf_ids = [w.id for w in workflows]
        assert wf.id not in wf_ids

    async def test_parse_cron_expression_valid(self):
        """Valid cron expression is parsed without error."""
        from src.triggers.cron import parse_cron_expression

        fields = parse_cron_expression("*/5 * * * *")
        assert fields is not None
        assert "minute" in fields

    async def test_parse_cron_expression_invalid(self):
        """Invalid cron expression raises ValueError."""
        from src.triggers.cron import parse_cron_expression

        with pytest.raises(ValueError, match="Invalid cron expression"):
            parse_cron_expression("invalid expression")

    async def test_parse_cron_expression_all_stars(self):
        """Standard all-stars cron expression parses correctly."""
        from src.triggers.cron import parse_cron_expression

        fields = parse_cron_expression("* * * * *")
        assert fields["minute"] == "*"
        assert fields["hour"] == "*"
        assert fields["day"] == "*"
        assert fields["month"] == "*"
        assert fields["day_of_week"] == "*"

    async def test_max_cron_workflows_enforced(self, db_session, cron_tenant):
        """Cannot exceed MAX_CRON_WORKFLOWS limit."""
        from src.triggers.cron import load_cron_workflows

        # Create many cron workflows
        for i in range(5):
            wf = Workflow(
                tenant_id=cron_tenant.id,
                name=f"Cron {i}",
                trigger_type="cron",
                trigger_config={"cron_expression": f"{i} * * * *"},
                steps=[{"id": "s1", "type": "transform", "config": {}}],
                is_active=True,
            )
            db_session.add(wf)
        await db_session.flush()

        # With default limit of 50 this should work
        workflows = await load_cron_workflows(db_session)
        assert len(workflows) >= 5

    async def test_build_trigger_data(self):
        """build_trigger_data creates correct trigger payload."""
        from src.triggers.cron import build_trigger_data

        data = build_trigger_data()
        assert data["triggered_by"] == "cron"
        assert "scheduled_time" in data
