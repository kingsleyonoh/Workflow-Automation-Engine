"""First-run seed script for creating the default tenant and sample workflows.

Usage: python -m src.tenants.seed

Checks if any tenants exist. If none, creates a default tenant
and prints the one-time API key. Optionally seeds sample workflows
for demonstration. Idempotent — safe to run multiple times.
Respects SELF_REGISTRATION_ENABLED setting.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.workflow_models import generate_webhook_path
from src.db.models import Workflow
from src.lib.logger import get_logger
from src.tenants.models import TenantWithKey
from src.tenants.service import check_tenants_exist, register_tenant

logger = get_logger(__name__)


async def seed_default_tenant(
    session: AsyncSession,
    tenant_name: str | None = None,
    registration_enabled: bool | None = None,
) -> TenantWithKey | None:
    """Create the default tenant if none exist.

    Args:
        session: Async database session.
        tenant_name: Override for the default tenant name.
            Falls back to settings.default_tenant_name if None.
        registration_enabled: Override for self-registration flag.
            Falls back to settings.self_registration_enabled if None.

    Returns:
        TenantWithKey if a tenant was created, None if skipped.
    """
    from src.config import settings

    if registration_enabled is None:
        registration_enabled = settings.self_registration_enabled

    if not registration_enabled:
        logger.info("seed_skipped", reason="self_registration_disabled")
        return None

    if tenant_name is None:
        tenant_name = settings.default_tenant_name

    if await check_tenants_exist(session=session):
        logger.info("seed_skipped", reason="tenants_already_exist")
        return None

    result = await register_tenant(name=tenant_name, session=session)
    await session.commit()

    logger.info(
        "seed_tenant_created",
        tenant_id=str(result.id),
        tenant_name=result.name,
    )

    return result


def _sample_webhook_workflow() -> dict:
    """Build a sample webhook-triggered workflow definition.

    DAG: fetch_data (http) → transform_response (transform)
         → check_status (condition)

    Demonstrates webhook trigger, HTTP call, Jinja2 transform,
    and conditional branching with step dependencies.
    """
    return {
        "name": "Sample: Webhook → HTTP → Transform → Condition",
        "description": (
            "Demo workflow: receives a webhook, calls an external API, "
            "transforms the response, and branches based on status."
        ),
        "trigger_type": "webhook",
        "trigger_config": {},
        "steps": [
            {
                "id": "fetch_data",
                "type": "http",
                "config": {
                    "url": "https://httpbin.org/post",
                    "method": "POST",
                    "headers": {"Content-Type": "application/json"},
                    "body": '{"source": "webhook"}',
                    "timeout_seconds": 10,
                },
                "depends_on": [],
            },
            {
                "id": "transform_response",
                "type": "transform",
                "config": {
                    "expression": ("{{ steps.fetch_data.output.status_code }}"),
                },
                "depends_on": ["fetch_data"],
            },
            {
                "id": "check_status",
                "type": "condition",
                "config": {
                    "expression": ("{{ steps.fetch_data.output.status_code == 200 }}"),
                    "true_branch": [],
                    "false_branch": [],
                },
                "depends_on": ["transform_response"],
            },
        ],
        "is_active": True,
    }


async def seed_sample_workflows(
    session: AsyncSession,
    tenant_id: uuid.UUID,
) -> int:
    """Seed sample workflows for a tenant. Idempotent.

    Creates demonstration workflows if none exist for the given
    tenant. Skips if workflows already exist.

    Args:
        session: Async database session.
        tenant_id: The tenant to seed workflows for.

    Returns:
        Number of workflows created.
    """
    stmt = (
        select(func.count())
        .select_from(Workflow)
        .where(Workflow.tenant_id == tenant_id)
    )
    result = await session.execute(stmt)
    count = result.scalar_one()

    if count > 0:
        logger.info(
            "seed_workflows_skipped",
            tenant_id=str(tenant_id),
            reason="workflows_already_exist",
        )
        return 0

    sample_defs = [_sample_webhook_workflow()]
    created = 0

    for defn in sample_defs:
        webhook_path = (
            generate_webhook_path() if defn["trigger_type"] == "webhook" else None
        )
        workflow = Workflow(
            tenant_id=tenant_id,
            name=defn["name"],
            description=defn.get("description"),
            trigger_type=defn["trigger_type"],
            trigger_config=defn.get("trigger_config", {}),
            steps=defn["steps"],
            is_active=defn.get("is_active", True),
            webhook_path=webhook_path,
        )
        session.add(workflow)
        created += 1

    await session.flush()

    logger.info(
        "seed_workflows_created",
        tenant_id=str(tenant_id),
        count=created,
    )

    return created


async def _main() -> None:
    """Entry point for python -m src.tenants.seed."""
    from src.db.postgres import async_session_factory, dispose_engine
    from src.lib.logger import configure_logging

    configure_logging()

    async with async_session_factory() as session:
        result = await seed_default_tenant(session=session)

        if result is not None:
            print(f"\nDefault tenant created: {result.name}")  # noqa: T201
            print(  # noqa: T201
                f"API Key (save this — shown only once): {result.api_key}"
            )
            wf_count = await seed_sample_workflows(session=session, tenant_id=result.id)
            if wf_count > 0:
                await session.commit()
                print(f"Sample workflows created: {wf_count}")  # noqa: T201
        else:
            print("Already initialized — no action taken.")  # noqa: T201

    await dispose_engine()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
