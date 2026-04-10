"""ExecutionLog ORM model for structured logs per execution/step.

Stores structured log entries with level, message, and optional
JSONB data for each execution and step combination.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models.base import Base


class ExecutionLog(Base):
    """Structured logs per execution/step."""

    __tablename__ = "execution_logs"

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
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    level: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # Relationships
    execution: Mapped["Execution"] = relationship(  # noqa: F821
        back_populates="execution_logs"
    )

    __table_args__ = (
        Index(
            "ix_execution_logs_tenant_execution_created",
            "tenant_id",
            "execution_id",
            "created_at",
        ),
    )

    def __repr__(self) -> str:
        return f"<ExecutionLog id={self.id} level={self.level!r}>"
