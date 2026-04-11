"""Tenant registration and API key validation service.

Handles tenant lifecycle: registration with bcrypt-hashed API keys,
key validation by prefix lookup + bcrypt verify, and tenant existence checks.
"""

import secrets

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Tenant
from src.lib.logger import get_logger
from src.lib.utils import AppError
from src.tenants.models import TenantContext, TenantWithKey

logger = get_logger(__name__)

API_KEY_PREFIX_LABEL = "wae_live_"
API_KEY_HEX_LENGTH = 32
# Store wae_live_ (9 chars) + first 8 hex chars = 17 chars for unique lookup
API_KEY_LOOKUP_PREFIX_LENGTH = 17


def _generate_api_key() -> str:
    """Generate a new API key in format wae_live_<32 hex chars>.

    Returns:
        A new random API key string.
    """
    hex_part = secrets.token_hex(API_KEY_HEX_LENGTH // 2)
    return f"{API_KEY_PREFIX_LABEL}{hex_part}"


async def register_tenant(
    name: str,
    session: AsyncSession,
) -> TenantWithKey:
    """Register a new tenant with a bcrypt-hashed API key.

    Generates a random API key, hashes it with bcrypt, stores the tenant
    record, and returns the full key (shown once).

    Args:
        name: Tenant display name.
        session: Async database session.

    Returns:
        TenantWithKey with the full API key for one-time display.
    """
    api_key = _generate_api_key()
    api_key_hash = bcrypt.hashpw(
        api_key.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")
    api_key_prefix = api_key[:API_KEY_LOOKUP_PREFIX_LENGTH]

    tenant = Tenant(
        name=name,
        api_key_hash=api_key_hash,
        api_key_prefix=api_key_prefix,
    )
    session.add(tenant)
    await session.flush()

    logger.info(
        "tenant_registered",
        tenant_id=str(tenant.id),
        tenant_name=name,
        api_key_prefix=api_key_prefix,
    )

    return TenantWithKey(
        id=tenant.id,
        name=tenant.name,
        api_key=api_key,
    )


async def validate_api_key(
    api_key: str,
    session: AsyncSession,
) -> TenantContext:
    """Validate an API key and return the tenant context.

    Extracts the prefix (first 8 chars) for fast DB lookup, then
    verifies the full key against the stored bcrypt hash.

    Args:
        api_key: The full API key from the X-API-Key header.
        session: Async database session.

    Returns:
        TenantContext for the authenticated tenant.

    Raises:
        AppError: INVALID_API_KEY (401) or TENANT_DISABLED (403).
    """
    if len(api_key) < API_KEY_LOOKUP_PREFIX_LENGTH:
        raise AppError(
            code="INVALID_API_KEY",
            message="Invalid or missing API key.",
            status_code=401,
        )

    prefix = api_key[:API_KEY_LOOKUP_PREFIX_LENGTH]

    stmt = select(Tenant).where(Tenant.api_key_prefix == prefix)
    result = await session.execute(stmt)
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise AppError(
            code="INVALID_API_KEY",
            message="Invalid or missing API key.",
            status_code=401,
        )

    if not bcrypt.checkpw(
        api_key.encode("utf-8"),
        tenant.api_key_hash.encode("utf-8"),
    ):
        raise AppError(
            code="INVALID_API_KEY",
            message="Invalid or missing API key.",
            status_code=401,
        )

    if not tenant.is_active:
        raise AppError(
            code="TENANT_DISABLED",
            message="Tenant account is disabled.",
            status_code=403,
        )

    return TenantContext(
        id=tenant.id,
        name=tenant.name,
        is_active=tenant.is_active,
    )


async def check_tenants_exist(session: AsyncSession) -> bool:
    """Check if any tenants exist in the database.

    Args:
        session: Async database session.

    Returns:
        True if at least one tenant exists, False otherwise.
    """
    stmt = select(func.count()).select_from(Tenant)
    result = await session.execute(stmt)
    count = result.scalar_one()
    return count > 0
