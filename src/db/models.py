"""SQLAlchemy ORM models for the Workflow Automation Engine.

Defines the declarative base and all database table models.
Every table includes tenant_id for multi-tenant isolation.
Models use UUID primary keys and timezone-aware timestamps.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""


class Tenant(Base):
    """Tenant accounts with API key authentication.

    Each tenant has a unique API key prefix for fast lookups
    and a bcrypt hash of the full key for secure verification.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_prefix: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # Relationships
    workflows: Mapped[list["Workflow"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_tenants_is_active", "is_active"),)

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} name={self.name!r}>"


class Workflow(Base):
    """DAG workflow definitions with trigger configuration.

    Each workflow belongs to a tenant and contains a JSONB array
    of step definitions that form the directed acyclic graph.
    """

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    steps: Mapped[list] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    webhook_path: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="workflows")

    __table_args__ = (
        Index("ix_workflows_tenant_is_active", "tenant_id", "is_active"),
        Index("ix_workflows_tenant_trigger_type", "tenant_id", "trigger_type"),
        Index("ix_workflows_webhook_path", "webhook_path"),
    )

    def __repr__(self) -> str:
        return f"<Workflow id={self.id} name={self.name!r}>"
