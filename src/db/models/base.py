"""SQLAlchemy declarative base for the Workflow Automation Engine.

All ORM models inherit from this Base class.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy models."""
