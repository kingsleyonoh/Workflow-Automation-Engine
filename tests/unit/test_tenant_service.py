"""Unit tests for tenant registration and key validation service.

Tests register_tenant, validate_api_key, and check_tenants_exist
against real local PostgreSQL with transactional rollback.
"""

import uuid

import bcrypt
import pytest

from src.lib.utils import AppError


class TestRegisterTenant:
    """Tests for register_tenant service function."""

    async def test_register_returns_tenant_with_key(self, db_session):
        """register_tenant returns a TenantWithKey with all required fields."""
        from src.tenants.service import register_tenant

        result = await register_tenant(name="Test Corp", session=db_session)
        assert result.name == "Test Corp"
        assert result.id is not None
        assert isinstance(result.id, uuid.UUID)
        assert result.api_key.startswith("wae_live_")

    async def test_register_api_key_format(self, db_session):
        """Generated API key follows format wae_live_<32 hex chars>."""
        from src.tenants.service import register_tenant

        result = await register_tenant(name="Test Corp", session=db_session)
        key = result.api_key
        assert key.startswith("wae_live_")
        hex_part = key[len("wae_live_") :]
        assert len(hex_part) == 32
        # Verify it's valid hex
        int(hex_part, 16)

    async def test_register_stores_bcrypt_hash(self, db_session):
        """Stored api_key_hash is a valid bcrypt hash of the full key."""
        from sqlalchemy import select

        from src.db.models import Tenant
        from src.tenants.service import register_tenant

        result = await register_tenant(name="Hash Check", session=db_session)

        # Query the stored tenant
        stmt = select(Tenant).where(Tenant.id == result.id)
        row = (await db_session.execute(stmt)).scalar_one()

        # Verify bcrypt hash matches the key
        assert bcrypt.checkpw(
            result.api_key.encode("utf-8"),
            row.api_key_hash.encode("utf-8"),
        )

    async def test_register_stores_prefix(self, db_session):
        """Stored api_key_prefix is the first 17 chars of the full key."""
        from sqlalchemy import select

        from src.db.models import Tenant
        from src.tenants.service import register_tenant

        result = await register_tenant(name="Prefix Check", session=db_session)

        stmt = select(Tenant).where(Tenant.id == result.id)
        row = (await db_session.execute(stmt)).scalar_one()

        # Prefix = wae_live_ (9 chars) + first 8 hex chars = 17 chars
        assert row.api_key_prefix == result.api_key[:17]
        assert row.api_key_prefix.startswith("wae_live_")

    async def test_register_tenant_is_active_by_default(self, db_session):
        """Newly registered tenant is active by default."""
        from sqlalchemy import select

        from src.db.models import Tenant
        from src.tenants.service import register_tenant

        result = await register_tenant(name="Active Test", session=db_session)

        stmt = select(Tenant).where(Tenant.id == result.id)
        row = (await db_session.execute(stmt)).scalar_one()

        assert row.is_active is True

    async def test_register_unique_keys_per_call(self, db_session):
        """Each registration generates a unique API key."""
        from src.tenants.service import register_tenant

        result1 = await register_tenant(name="Tenant A", session=db_session)
        result2 = await register_tenant(name="Tenant B", session=db_session)

        assert result1.api_key != result2.api_key
        assert result1.id != result2.id


class TestValidateApiKey:
    """Tests for validate_api_key service function."""

    async def test_validate_valid_key_returns_context(self, db_session):
        """Valid API key returns a TenantContext with correct fields."""
        from src.tenants.models import TenantContext
        from src.tenants.service import register_tenant, validate_api_key

        reg = await register_tenant(name="Valid Key Corp", session=db_session)
        ctx = await validate_api_key(api_key=reg.api_key, session=db_session)

        assert isinstance(ctx, TenantContext)
        assert ctx.id == reg.id
        assert ctx.name == "Valid Key Corp"
        assert ctx.is_active is True

    async def test_validate_invalid_key_raises_401(self, db_session):
        """Invalid API key raises AppError with INVALID_API_KEY and 401."""
        from src.tenants.service import validate_api_key

        with pytest.raises(AppError) as exc_info:
            await validate_api_key(
                api_key="wae_live_0000000000000000000000000000dead",
                session=db_session,
            )
        assert exc_info.value.code == "INVALID_API_KEY"
        assert exc_info.value.status_code == 401

    async def test_validate_wrong_key_same_prefix_raises_401(self, db_session):
        """Wrong key with same prefix as valid tenant raises 401."""
        from src.tenants.service import register_tenant, validate_api_key

        reg = await register_tenant(name="Prefix Test", session=db_session)

        # Construct a fake key with same 17-char prefix but different hex tail
        prefix = reg.api_key[:17]
        fake_key = prefix + "ff" * 12  # Same prefix, different tail

        with pytest.raises(AppError) as exc_info:
            await validate_api_key(api_key=fake_key, session=db_session)
        assert exc_info.value.code == "INVALID_API_KEY"
        assert exc_info.value.status_code == 401

    async def test_validate_inactive_tenant_raises_403(self, db_session):
        """Inactive tenant's valid key raises AppError TENANT_DISABLED 403."""
        from sqlalchemy import update

        from src.db.models import Tenant
        from src.tenants.service import register_tenant, validate_api_key

        reg = await register_tenant(name="Disabled Corp", session=db_session)

        # Deactivate the tenant
        await db_session.execute(
            update(Tenant).where(Tenant.id == reg.id).values(is_active=False)
        )
        await db_session.flush()

        with pytest.raises(AppError) as exc_info:
            await validate_api_key(api_key=reg.api_key, session=db_session)
        assert exc_info.value.code == "TENANT_DISABLED"
        assert exc_info.value.status_code == 403

    async def test_validate_empty_key_raises_401(self, db_session):
        """Empty API key raises 401."""
        from src.tenants.service import validate_api_key

        with pytest.raises(AppError) as exc_info:
            await validate_api_key(api_key="", session=db_session)
        assert exc_info.value.code == "INVALID_API_KEY"
        assert exc_info.value.status_code == 401

    async def test_validate_short_key_raises_401(self, db_session):
        """API key shorter than prefix length raises 401."""
        from src.tenants.service import validate_api_key

        with pytest.raises(AppError) as exc_info:
            await validate_api_key(api_key="wae", session=db_session)
        assert exc_info.value.code == "INVALID_API_KEY"
        assert exc_info.value.status_code == 401


class TestCheckTenantsExist:
    """Tests for check_tenants_exist helper."""

    async def test_no_tenants_returns_false(self, db_session):
        """Returns False when no tenants exist."""
        from src.tenants.service import check_tenants_exist

        result = await check_tenants_exist(session=db_session)
        assert result is False

    async def test_with_tenant_returns_true(self, db_session):
        """Returns True when at least one tenant exists."""
        from src.tenants.service import check_tenants_exist, register_tenant

        await register_tenant(name="Existing Tenant", session=db_session)
        result = await check_tenants_exist(session=db_session)
        assert result is True
