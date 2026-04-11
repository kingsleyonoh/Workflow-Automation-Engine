"""Tenant API routes for registration and profile access.

POST /api/tenants/register — public tenant registration (guarded by config).
GET /api/tenants/me — authenticated tenant profile endpoint.
"""

from fastapi import APIRouter, Request

from src.config import settings
from src.db.postgres import async_session_factory
from src.lib.logger import get_logger
from src.lib.utils import AppError
from src.tenants.models import TenantCreate, TenantResponse, TenantWithKey
from src.tenants.service import register_tenant

logger = get_logger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["tenants"])


@router.post("/register", response_model=TenantWithKey, status_code=201)
async def register_tenant_endpoint(body: TenantCreate) -> TenantWithKey:
    """Register a new tenant and return a one-time API key.

    Public endpoint — no authentication required. Guarded by the
    SELF_REGISTRATION_ENABLED configuration setting.

    Args:
        body: Tenant registration request with name.

    Returns:
        TenantWithKey with id, name, and the full API key (shown once).

    Raises:
        AppError: REGISTRATION_DISABLED (403) if self-registration is off.
    """
    if not settings.self_registration_enabled:
        raise AppError(
            code="REGISTRATION_DISABLED",
            message="Tenant self-registration is disabled.",
            status_code=403,
        )

    async with async_session_factory() as session:
        result = await register_tenant(name=body.name, session=session)
        await session.commit()

    logger.info(
        "tenant_registered_via_api",
        tenant_id=str(result.id),
        tenant_name=result.name,
    )
    return result


@router.get("/me", response_model=TenantResponse)
async def get_current_tenant(request: Request) -> TenantResponse:
    """Return the current authenticated tenant's profile.

    Reads the tenant context injected by auth middleware from
    request.state.tenant. Does NOT expose the API key.

    Args:
        request: The incoming HTTP request with tenant state.

    Returns:
        TenantResponse with id, name, is_active, and created_at.
    """
    tenant_ctx = request.state.tenant

    # Fetch full tenant data including created_at from database
    from sqlalchemy import select

    from src.db.models import Tenant

    async with async_session_factory() as session:
        stmt = select(Tenant).where(Tenant.id == tenant_ctx.id)
        result = await session.execute(stmt)
        tenant = result.scalar_one()

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
    )
