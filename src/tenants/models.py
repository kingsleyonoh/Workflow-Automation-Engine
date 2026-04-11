"""Pydantic models for tenant management.

Defines request/response schemas for tenant registration, API responses,
and the auth context injected by middleware into request state.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TenantCreate(BaseModel):
    """Request model for tenant registration.

    Accepts a tenant name, validates it is non-empty and within length limits.
    """

    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        """Strip leading/trailing whitespace from name."""
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        """Reject whitespace-only names after stripping."""
        if not v:
            msg = "Name must not be blank"
            raise ValueError(msg)
        return v


class TenantResponse(BaseModel):
    """Response model for tenant profile data.

    Returned by GET /api/tenants/me and similar endpoints.
    Does NOT include the API key.
    """

    id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime


class TenantWithKey(BaseModel):
    """One-time response model returned after tenant registration.

    Includes the full API key, which is shown only once.
    """

    id: uuid.UUID
    name: str
    api_key: str


class TenantContext(BaseModel):
    """Tenant context injected by auth middleware into request state.

    Immutable after creation. Downstream code reads tenant_id from here.
    """

    model_config = {"frozen": True}

    id: uuid.UUID
    name: str
    is_active: bool
