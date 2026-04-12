"""Tests for sample workflow seeding.

Tests that seed_sample_workflows creates valid DAG workflows
with proper step types, dependencies, and trigger configurations.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Tenant, Workflow


@pytest.fixture
async def tenant_in_db(db_session: AsyncSession) -> Tenant:
    """Create a tenant for seeding workflows."""
    tenant = Tenant(
        name="Seed Test Tenant",
        api_key_hash="$2b$12$fakehashvalue",
        api_key_prefix="wae_live_12345678",
    )
    db_session.add(tenant)
    await db_session.flush()
    return tenant


class TestSeedSampleWorkflows:
    """Test the sample workflow seeding function."""

    @pytest.mark.integration
    async def test_creates_sample_workflows(
        self, db_session: AsyncSession, tenant_in_db: Tenant
    ) -> None:
        """Seed creates at least one sample workflow."""
        from src.tenants.seed import seed_sample_workflows

        count = await seed_sample_workflows(
            session=db_session, tenant_id=tenant_in_db.id
        )
        assert count >= 1

    @pytest.mark.integration
    async def test_sample_workflow_has_webhook_trigger(
        self, db_session: AsyncSession, tenant_in_db: Tenant
    ) -> None:
        """At least one sample workflow is webhook-triggered."""
        from src.tenants.seed import seed_sample_workflows

        await seed_sample_workflows(session=db_session, tenant_id=tenant_in_db.id)

        stmt = select(Workflow).where(
            Workflow.tenant_id == tenant_in_db.id,
            Workflow.trigger_type == "webhook",
        )
        result = await db_session.execute(stmt)
        workflows = result.scalars().all()
        assert len(workflows) >= 1

    @pytest.mark.integration
    async def test_sample_workflow_has_multiple_step_types(
        self, db_session: AsyncSession, tenant_in_db: Tenant
    ) -> None:
        """Sample workflows use at least http, transform, and condition steps."""
        from src.tenants.seed import seed_sample_workflows

        await seed_sample_workflows(session=db_session, tenant_id=tenant_in_db.id)

        stmt = select(Workflow).where(Workflow.tenant_id == tenant_in_db.id)
        result = await db_session.execute(stmt)
        workflows = result.scalars().all()

        all_step_types: set[str] = set()
        for wf in workflows:
            for step in wf.steps:
                all_step_types.add(step["type"])

        assert "http" in all_step_types
        assert "transform" in all_step_types
        assert "condition" in all_step_types

    @pytest.mark.integration
    async def test_sample_workflow_has_step_dependencies(
        self, db_session: AsyncSession, tenant_in_db: Tenant
    ) -> None:
        """Sample workflows have steps with depends_on to form a DAG."""
        from src.tenants.seed import seed_sample_workflows

        await seed_sample_workflows(session=db_session, tenant_id=tenant_in_db.id)

        stmt = select(Workflow).where(Workflow.tenant_id == tenant_in_db.id)
        result = await db_session.execute(stmt)
        workflows = result.scalars().all()

        has_deps = False
        for wf in workflows:
            for step in wf.steps:
                if step.get("depends_on"):
                    has_deps = True
                    break

        assert has_deps, "Sample workflows should have steps with dependencies"

    @pytest.mark.integration
    async def test_sample_workflows_pass_parser_validation(
        self, db_session: AsyncSession, tenant_in_db: Tenant
    ) -> None:
        """All sample workflows pass the workflow parser validation."""
        from src.engine.parser import parse_workflow_definition
        from src.tenants.seed import seed_sample_workflows

        await seed_sample_workflows(session=db_session, tenant_id=tenant_in_db.id)

        stmt = select(Workflow).where(Workflow.tenant_id == tenant_in_db.id)
        result = await db_session.execute(stmt)
        workflows = result.scalars().all()

        for wf in workflows:
            # Should not raise
            parse_workflow_definition(
                {
                    "name": wf.name,
                    "trigger_type": wf.trigger_type,
                    "steps": wf.steps,
                }
            )

    @pytest.mark.integration
    async def test_sample_workflow_has_webhook_path(
        self, db_session: AsyncSession, tenant_in_db: Tenant
    ) -> None:
        """Webhook-triggered sample workflows have a webhook_path assigned."""
        from src.tenants.seed import seed_sample_workflows

        await seed_sample_workflows(session=db_session, tenant_id=tenant_in_db.id)

        stmt = select(Workflow).where(
            Workflow.tenant_id == tenant_in_db.id,
            Workflow.trigger_type == "webhook",
        )
        result = await db_session.execute(stmt)
        workflows = result.scalars().all()

        for wf in workflows:
            assert wf.webhook_path is not None
            assert wf.webhook_path.startswith("wh_")

    @pytest.mark.integration
    async def test_seed_is_idempotent(
        self, db_session: AsyncSession, tenant_in_db: Tenant
    ) -> None:
        """Running seed twice does not duplicate workflows."""
        from src.tenants.seed import seed_sample_workflows

        count1 = await seed_sample_workflows(
            session=db_session, tenant_id=tenant_in_db.id
        )
        count2 = await seed_sample_workflows(
            session=db_session, tenant_id=tenant_in_db.id
        )

        assert count2 == 0, "Second seed should create no new workflows"

        stmt = select(Workflow).where(Workflow.tenant_id == tenant_in_db.id)
        result = await db_session.execute(stmt)
        workflows = result.scalars().all()
        assert len(workflows) == count1
