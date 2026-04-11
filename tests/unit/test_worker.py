"""Unit tests for the arq worker configuration.

Tests WorkerSettings configuration including Redis connection,
function registration, concurrency settings, and startup/shutdown hooks.
"""

from unittest.mock import AsyncMock, patch


class TestWorkerSettings:
    """Tests for arq WorkerSettings configuration."""

    def test_worker_settings_importable(self):
        """WorkerSettings class can be imported from src.queue.worker."""
        from src.queue.worker import WorkerSettings

        assert WorkerSettings is not None

    def test_worker_has_redis_settings(self):
        """WorkerSettings defines redis_settings from app config."""
        from src.queue.worker import WorkerSettings

        assert hasattr(WorkerSettings, "redis_settings")
        settings = WorkerSettings.redis_settings
        assert settings is not None

    def test_worker_has_functions(self):
        """WorkerSettings registers at least one function."""
        from src.queue.worker import WorkerSettings

        assert hasattr(WorkerSettings, "functions")
        assert len(WorkerSettings.functions) >= 1

    def test_worker_has_concurrency(self):
        """WorkerSettings sets max_jobs from config."""
        from src.queue.worker import WorkerSettings

        assert hasattr(WorkerSettings, "max_jobs")
        assert isinstance(WorkerSettings.max_jobs, int)
        assert WorkerSettings.max_jobs > 0

    def test_worker_registers_execute_step(self):
        """WorkerSettings registers the execute_step function."""
        from src.queue.worker import WorkerSettings

        func_names = [
            f.name if hasattr(f, "name") else f.__name__
            for f in WorkerSettings.functions
        ]
        assert "execute_step" in func_names

    def test_worker_has_startup_handler(self):
        """WorkerSettings defines on_startup hook."""
        from src.queue.worker import WorkerSettings

        assert hasattr(WorkerSettings, "on_startup")
        assert WorkerSettings.on_startup is not None

    def test_worker_has_shutdown_handler(self):
        """WorkerSettings defines on_shutdown hook."""
        from src.queue.worker import WorkerSettings

        assert hasattr(WorkerSettings, "on_shutdown")
        assert WorkerSettings.on_shutdown is not None


class TestWorkerStartupShutdown:
    """Tests for worker startup and shutdown hooks."""

    async def test_startup_initializes_db(self):
        """Worker startup hook initializes database session factory."""
        from src.queue.worker import on_startup

        ctx = {}
        # on_startup should not raise — it imports get_redis from src.db.redis
        with patch("src.db.redis.get_redis") as mock_redis:
            mock_redis.return_value = AsyncMock()
            await on_startup(ctx)

        # Verify context was populated
        assert "db_session_factory" in ctx
        assert "redis" in ctx

    async def test_shutdown_cleans_up(self):
        """Worker shutdown hook closes connections."""
        from src.queue.worker import on_shutdown

        ctx = {"redis": AsyncMock()}
        # on_shutdown should not raise
        await on_shutdown(ctx)
