"""Tests for in-memory LRU workflow definition cache.

Tests cache get/set/invalidation behavior, TTL expiry,
and lookup by both workflow_id and webhook_path.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from src.lib.cache import WorkflowCache


@pytest.fixture
def cache() -> WorkflowCache:
    """Create a fresh cache with small max size for testing."""
    return WorkflowCache(max_size=3, ttl_seconds=60)


def _make_workflow(
    workflow_id: uuid.UUID | None = None,
    webhook_path: str | None = None,
) -> MagicMock:
    """Create a mock workflow object for cache testing."""
    wf = MagicMock()
    wf.id = workflow_id or uuid.uuid4()
    wf.webhook_path = webhook_path
    wf.name = "test-workflow"
    wf.steps = [{"id": "step1", "type": "http", "config": {}}]
    return wf


class TestWorkflowCacheGetSet:
    """Test basic cache get/set operations."""

    def test_get_returns_none_for_empty_cache(self, cache: WorkflowCache) -> None:
        """Cache miss returns None for unknown key."""
        result = cache.get_by_id(uuid.uuid4())
        assert result is None

    def test_set_and_get_by_id(self, cache: WorkflowCache) -> None:
        """Cached workflow is retrievable by ID."""
        wf = _make_workflow()
        cache.set(wf)
        result = cache.get_by_id(wf.id)
        assert result is not None
        assert result.id == wf.id

    def test_set_and_get_by_webhook_path(self, cache: WorkflowCache) -> None:
        """Cached workflow is retrievable by webhook_path."""
        wf = _make_workflow(webhook_path="wh_test123")
        cache.set(wf)
        result = cache.get_by_webhook_path("wh_test123")
        assert result is not None
        assert result.id == wf.id

    def test_get_by_webhook_path_returns_none_for_no_path(
        self, cache: WorkflowCache
    ) -> None:
        """Workflow without webhook_path cannot be found by path."""
        wf = _make_workflow(webhook_path=None)
        cache.set(wf)
        result = cache.get_by_webhook_path("anything")
        assert result is None

    def test_overwrite_existing_entry(self, cache: WorkflowCache) -> None:
        """Setting a workflow with same ID overwrites the cached version."""
        wf_id = uuid.uuid4()
        wf1 = _make_workflow(workflow_id=wf_id, webhook_path="wh_old")
        wf1.name = "old"
        cache.set(wf1)

        wf2 = _make_workflow(workflow_id=wf_id, webhook_path="wh_new")
        wf2.name = "new"
        cache.set(wf2)

        result = cache.get_by_id(wf_id)
        assert result is not None
        assert result.name == "new"

        # Old webhook path should no longer work
        assert cache.get_by_webhook_path("wh_old") is None
        # New webhook path should work
        assert cache.get_by_webhook_path("wh_new") is not None


class TestWorkflowCacheInvalidation:
    """Test cache invalidation on update and delete."""

    def test_invalidate_by_id(self, cache: WorkflowCache) -> None:
        """Invalidating by ID removes the entry from both indexes."""
        wf = _make_workflow(webhook_path="wh_abc")
        cache.set(wf)

        cache.invalidate(wf.id)

        assert cache.get_by_id(wf.id) is None
        assert cache.get_by_webhook_path("wh_abc") is None

    def test_invalidate_nonexistent_key_is_noop(self, cache: WorkflowCache) -> None:
        """Invalidating a non-existent key does not raise."""
        cache.invalidate(uuid.uuid4())  # Should not raise

    def test_clear_removes_all_entries(self, cache: WorkflowCache) -> None:
        """Clear removes all cached entries."""
        for i in range(3):
            cache.set(_make_workflow(webhook_path=f"wh_{i}"))

        cache.clear()

        assert cache.get_by_webhook_path("wh_0") is None
        assert cache.get_by_webhook_path("wh_1") is None
        assert cache.get_by_webhook_path("wh_2") is None


class TestWorkflowCacheEviction:
    """Test LRU eviction when cache exceeds max_size."""

    def test_evicts_oldest_entry_when_full(self, cache: WorkflowCache) -> None:
        """Oldest entry is evicted when cache exceeds max_size."""
        wf1 = _make_workflow(webhook_path="wh_1")
        wf2 = _make_workflow(webhook_path="wh_2")
        wf3 = _make_workflow(webhook_path="wh_3")
        wf4 = _make_workflow(webhook_path="wh_4")

        cache.set(wf1)
        cache.set(wf2)
        cache.set(wf3)
        # Cache is now full (max_size=3)

        cache.set(wf4)
        # wf1 should be evicted

        assert cache.get_by_id(wf1.id) is None
        assert cache.get_by_webhook_path("wh_1") is None
        assert cache.get_by_id(wf4.id) is not None


class TestWorkflowCacheTTL:
    """Test TTL expiration of cached entries."""

    def test_expired_entry_returns_none(self) -> None:
        """Entries past TTL return None on get."""
        cache = WorkflowCache(max_size=10, ttl_seconds=0)
        wf = _make_workflow(webhook_path="wh_ttl")
        cache.set(wf)

        # With ttl_seconds=0, entry is immediately expired
        result = cache.get_by_id(wf.id)
        assert result is None

    def test_expired_webhook_path_returns_none(self) -> None:
        """Webhook path lookup returns None for expired entries."""
        cache = WorkflowCache(max_size=10, ttl_seconds=0)
        wf = _make_workflow(webhook_path="wh_expired")
        cache.set(wf)

        result = cache.get_by_webhook_path("wh_expired")
        assert result is None


class TestWorkflowCacheStats:
    """Test cache statistics reporting."""

    def test_stats_reports_size(self, cache: WorkflowCache) -> None:
        """Stats includes current cache size."""
        cache.set(_make_workflow())
        cache.set(_make_workflow())
        stats = cache.stats()
        assert stats["size"] == 2
        assert stats["max_size"] == 3
