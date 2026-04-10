"""Unit tests for async SQLAlchemy PostgreSQL connection pool."""

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


async def test_engine_creation():
    """Engine factory creates an AsyncEngine with correct URL."""
    from src.db.postgres import engine

    assert isinstance(engine, AsyncEngine)
    assert "asyncpg" in str(engine.url)


async def test_engine_pool_size():
    """Engine uses pool size from settings (default 5)."""
    from src.db.postgres import engine

    assert engine.pool.size() == 5


async def test_session_factory_returns_async_session():
    """Session factory creates AsyncSession instances."""
    from src.db.postgres import async_session_factory

    assert isinstance(async_session_factory, async_sessionmaker)


async def test_get_session_yields_session():
    """get_session yields a working AsyncSession."""
    from src.db.postgres import get_session

    async for session in get_session():
        assert isinstance(session, AsyncSession)
        break


async def test_engine_disposal():
    """Engine can be disposed cleanly."""
    from src.db.postgres import dispose_engine, engine

    # Should not raise
    await dispose_engine()
    # Recreate for other tests - engine is module-level
    assert engine is not None
