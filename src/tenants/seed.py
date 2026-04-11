"""First-run seed script for creating the default tenant.

Usage: python -m src.tenants.seed

Checks if any tenants exist. If none, creates a default tenant
and prints the one-time API key. Idempotent — safe to run multiple times.
Respects SELF_REGISTRATION_ENABLED setting.
"""

from sqlalchemy.ext.asyncio import AsyncSession

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


async def _main() -> None:
    """Entry point for python -m src.tenants.seed."""
    from src.db.postgres import async_session_factory, dispose_engine
    from src.lib.logger import configure_logging

    configure_logging()

    async with async_session_factory() as session:
        result = await seed_default_tenant(session=session)

    if result is not None:
        print(f"\nDefault tenant created: {result.name}")  # noqa: T201
        print(f"API Key (save this — shown only once): {result.api_key}")  # noqa: T201
    else:
        print("Already initialized — no action taken.")  # noqa: T201

    await dispose_engine()


if __name__ == "__main__":
    import asyncio

    asyncio.run(_main())
