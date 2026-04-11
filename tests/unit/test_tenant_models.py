"""Unit tests for tenant Pydantic models.

Tests TenantCreate, TenantResponse, TenantWithKey, and TenantContext
validation, serialization, and edge cases.
"""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError


class TestTenantCreate:
    """Tests for TenantCreate request model."""

    def test_valid_name(self):
        """TenantCreate accepts a valid name string."""
        from src.tenants.models import TenantCreate

        model = TenantCreate(name="My Tenant")
        assert model.name == "My Tenant"

    def test_name_required(self):
        """TenantCreate rejects missing name field."""
        from src.tenants.models import TenantCreate

        with pytest.raises(ValidationError) as exc_info:
            TenantCreate()  # type: ignore[call-arg]
        assert "name" in str(exc_info.value)

    def test_name_empty_string_rejected(self):
        """TenantCreate rejects empty string name."""
        from src.tenants.models import TenantCreate

        with pytest.raises(ValidationError):
            TenantCreate(name="")

    def test_name_whitespace_only_rejected(self):
        """TenantCreate rejects whitespace-only name."""
        from src.tenants.models import TenantCreate

        with pytest.raises(ValidationError):
            TenantCreate(name="   ")

    def test_name_stripped(self):
        """TenantCreate strips leading/trailing whitespace from name."""
        from src.tenants.models import TenantCreate

        model = TenantCreate(name="  My Tenant  ")
        assert model.name == "My Tenant"

    def test_name_max_length(self):
        """TenantCreate rejects name longer than 100 characters."""
        from src.tenants.models import TenantCreate

        with pytest.raises(ValidationError):
            TenantCreate(name="x" * 101)

    def test_name_at_max_length(self):
        """TenantCreate accepts name exactly 100 characters."""
        from src.tenants.models import TenantCreate

        model = TenantCreate(name="x" * 100)
        assert len(model.name) == 100


class TestTenantResponse:
    """Tests for TenantResponse model."""

    def test_valid_response(self):
        """TenantResponse accepts all valid fields."""
        from src.tenants.models import TenantResponse

        tenant_id = uuid.uuid4()
        now = datetime.now(UTC)
        model = TenantResponse(
            id=tenant_id,
            name="My Tenant",
            is_active=True,
            created_at=now,
        )
        assert model.id == tenant_id
        assert model.name == "My Tenant"
        assert model.is_active is True
        assert model.created_at == now

    def test_id_required(self):
        """TenantResponse rejects missing id."""
        from src.tenants.models import TenantResponse

        with pytest.raises(ValidationError):
            TenantResponse(name="Test", is_active=True, created_at=datetime.now(UTC))  # type: ignore[call-arg]

    def test_name_required(self):
        """TenantResponse rejects missing name."""
        from src.tenants.models import TenantResponse

        with pytest.raises(ValidationError):
            TenantResponse(
                id=uuid.uuid4(), is_active=True, created_at=datetime.now(UTC)
            )  # type: ignore[call-arg]

    def test_is_active_required(self):
        """TenantResponse rejects missing is_active."""
        from src.tenants.models import TenantResponse

        with pytest.raises(ValidationError):
            TenantResponse(id=uuid.uuid4(), name="Test", created_at=datetime.now(UTC))  # type: ignore[call-arg]

    def test_created_at_required(self):
        """TenantResponse rejects missing created_at."""
        from src.tenants.models import TenantResponse

        with pytest.raises(ValidationError):
            TenantResponse(id=uuid.uuid4(), name="Test", is_active=True)  # type: ignore[call-arg]

    def test_serialization_to_dict(self):
        """TenantResponse serializes to dict with expected keys."""
        from src.tenants.models import TenantResponse

        tenant_id = uuid.uuid4()
        now = datetime.now(UTC)
        model = TenantResponse(
            id=tenant_id, name="Test", is_active=True, created_at=now
        )
        data = model.model_dump()
        assert set(data.keys()) == {"id", "name", "is_active", "created_at"}


class TestTenantWithKey:
    """Tests for TenantWithKey one-time response model."""

    def test_valid_with_key(self):
        """TenantWithKey accepts all fields including api_key."""
        from src.tenants.models import TenantWithKey

        tenant_id = uuid.uuid4()
        model = TenantWithKey(
            id=tenant_id,
            name="My Tenant",
            api_key="wae_live_abcdef1234567890abcdef1234567890",
        )
        assert model.id == tenant_id
        assert model.name == "My Tenant"
        assert model.api_key == "wae_live_abcdef1234567890abcdef1234567890"

    def test_api_key_required(self):
        """TenantWithKey rejects missing api_key."""
        from src.tenants.models import TenantWithKey

        with pytest.raises(ValidationError):
            TenantWithKey(id=uuid.uuid4(), name="Test")  # type: ignore[call-arg]

    def test_serialization_includes_api_key(self):
        """TenantWithKey serializes with api_key in output."""
        from src.tenants.models import TenantWithKey

        model = TenantWithKey(
            id=uuid.uuid4(),
            name="Test",
            api_key="wae_live_abcdef1234567890abcdef1234567890",
        )
        data = model.model_dump()
        assert "api_key" in data
        assert data["api_key"] == "wae_live_abcdef1234567890abcdef1234567890"


class TestTenantContext:
    """Tests for TenantContext injected by auth middleware."""

    def test_valid_context(self):
        """TenantContext accepts valid fields."""
        from src.tenants.models import TenantContext

        tenant_id = uuid.uuid4()
        ctx = TenantContext(id=tenant_id, name="My Tenant", is_active=True)
        assert ctx.id == tenant_id
        assert ctx.name == "My Tenant"
        assert ctx.is_active is True

    def test_id_required(self):
        """TenantContext rejects missing id."""
        from src.tenants.models import TenantContext

        with pytest.raises(ValidationError):
            TenantContext(name="Test", is_active=True)  # type: ignore[call-arg]

    def test_name_required(self):
        """TenantContext rejects missing name."""
        from src.tenants.models import TenantContext

        with pytest.raises(ValidationError):
            TenantContext(id=uuid.uuid4(), is_active=True)  # type: ignore[call-arg]

    def test_is_active_required(self):
        """TenantContext rejects missing is_active."""
        from src.tenants.models import TenantContext

        with pytest.raises(ValidationError):
            TenantContext(id=uuid.uuid4(), name="Test")  # type: ignore[call-arg]

    def test_immutable(self):
        """TenantContext should be frozen (immutable)."""
        from src.tenants.models import TenantContext

        ctx = TenantContext(id=uuid.uuid4(), name="Test", is_active=True)
        with pytest.raises(ValidationError):
            ctx.name = "Changed"  # type: ignore[misc]
