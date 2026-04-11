"""Unit tests for the tenant seed script.

Tests seed_default_tenant core function for idempotency,
respect for configuration settings, and correct behavior.
"""


class TestSeedDefaultTenant:
    """Tests for seed_default_tenant function."""

    async def test_seed_creates_tenant_when_none_exist(self, db_session):
        """Seed creates a default tenant when no tenants exist."""
        from src.tenants.seed import seed_default_tenant

        result = await seed_default_tenant(session=db_session)
        assert result is not None
        assert result.name == "Default"
        assert result.api_key.startswith("wae_live_")

    async def test_seed_idempotent_returns_none(self, db_session):
        """Seed returns None when tenants already exist (idempotent)."""
        from src.tenants.seed import seed_default_tenant
        from src.tenants.service import register_tenant

        # Create a tenant first
        await register_tenant(name="Existing", session=db_session)

        result = await seed_default_tenant(session=db_session)
        assert result is None

    async def test_seed_uses_default_tenant_name(self, db_session):
        """Seed uses DEFAULT_TENANT_NAME from settings."""
        from src.tenants.seed import seed_default_tenant

        result = await seed_default_tenant(
            session=db_session, tenant_name="Custom Corp"
        )
        assert result is not None
        assert result.name == "Custom Corp"

    async def test_seed_returns_tenant_with_key(self, db_session):
        """Seed returns TenantWithKey with full API key."""
        from src.tenants.models import TenantWithKey
        from src.tenants.seed import seed_default_tenant

        result = await seed_default_tenant(session=db_session)
        assert result is not None
        assert isinstance(result, TenantWithKey)
        assert result.api_key.startswith("wae_live_")

    async def test_seed_disabled_when_registration_off(self, db_session):
        """Seed returns None when self_registration is disabled."""
        from src.tenants.seed import seed_default_tenant

        result = await seed_default_tenant(
            session=db_session,
            registration_enabled=False,
        )
        assert result is None
