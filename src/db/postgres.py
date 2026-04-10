"""Async SQLAlchemy PostgreSQL connection pool.

Provides a shared async engine and session factory for all database access.
Uses connection pooling with configurable pool size. All database interactions
in the application MUST use get_session() for proper session lifecycle.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import settings
from src.lib.logger import get_logger

logger = get_logger(__name__)

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async database session with automatic cleanup.

    Use as an async generator dependency in FastAPI routes or directly
    with ``async for session in get_session()``.

    Yields:
        AsyncSession bound to the shared engine.
    """
    async with async_session_factory() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the connection pool, closing all connections.

    Call during application shutdown to release database resources.
    """
    logger.info("disposing_engine")
    await engine.dispose()
