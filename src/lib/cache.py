"""In-memory LRU cache for workflow definitions.

Avoids a database read on every webhook trigger by caching workflow
definitions in memory. Supports lookup by workflow_id and webhook_path.
Invalidated on workflow update (PUT) and delete (DELETE).

Thread-safe via OrderedDict access patterns. The cache is a singleton
module-level instance accessed by webhook handler and workflow CRUD.
"""

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from src.lib.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _CacheEntry:
    """A single cached workflow with expiry timestamp."""

    workflow: Any
    expires_at: float


class WorkflowCache:
    """LRU cache for workflow definitions with TTL expiry.

    Supports dual-index lookup: by workflow_id and by webhook_path.
    When the cache exceeds max_size, the least recently used entry
    is evicted. Entries expire after ttl_seconds.

    Args:
        max_size: Maximum number of cached workflows.
        ttl_seconds: Time-to-live for each entry in seconds.
    """

    def __init__(self, max_size: int = 256, ttl_seconds: int = 300) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[uuid.UUID, _CacheEntry] = OrderedDict()
        self._path_index: dict[str, uuid.UUID] = {}

    def get_by_id(self, workflow_id: uuid.UUID) -> Any | None:
        """Look up a cached workflow by its ID.

        Returns None on cache miss or if the entry has expired.
        Moves the entry to the end (most recently used) on hit.

        Args:
            workflow_id: The workflow UUID.

        Returns:
            The cached workflow object, or None.
        """
        entry = self._entries.get(workflow_id)
        if entry is None:
            return None

        if time.monotonic() >= entry.expires_at:
            self._remove(workflow_id)
            return None

        self._entries.move_to_end(workflow_id)
        return entry.workflow

    def get_by_webhook_path(self, webhook_path: str) -> Any | None:
        """Look up a cached workflow by its webhook_path.

        Uses a secondary index (webhook_path -> workflow_id) for
        O(1) lookup without scanning all entries.

        Args:
            webhook_path: The webhook path slug.

        Returns:
            The cached workflow object, or None.
        """
        workflow_id = self._path_index.get(webhook_path)
        if workflow_id is None:
            return None
        return self.get_by_id(workflow_id)

    def set(self, workflow: Any) -> None:
        """Cache a workflow definition.

        If the workflow already exists in the cache, it is updated.
        If the cache is full, the least recently used entry is evicted.

        Args:
            workflow: A workflow object with .id and optional .webhook_path.
        """
        workflow_id = workflow.id

        # Remove old entry if exists (cleans up old webhook_path index)
        if workflow_id in self._entries:
            self._remove(workflow_id)

        # Evict LRU if at capacity
        while len(self._entries) >= self._max_size:
            oldest_id, _ = self._entries.popitem(last=False)
            self._remove_path_index(oldest_id)

        # Insert new entry
        expires_at = time.monotonic() + self._ttl_seconds
        self._entries[workflow_id] = _CacheEntry(
            workflow=workflow,
            expires_at=expires_at,
        )
        self._entries.move_to_end(workflow_id)

        # Update webhook_path secondary index
        if workflow.webhook_path:
            self._path_index[workflow.webhook_path] = workflow_id

        logger.debug(
            "workflow_cache_set",
            workflow_id=str(workflow_id),
            webhook_path=workflow.webhook_path,
        )

    def invalidate(self, workflow_id: uuid.UUID) -> None:
        """Remove a workflow from the cache.

        Called on workflow update (PUT) and delete (DELETE) to
        ensure stale data is not served.

        Args:
            workflow_id: The workflow UUID to invalidate.
        """
        if workflow_id in self._entries:
            self._remove(workflow_id)
            logger.debug(
                "workflow_cache_invalidated",
                workflow_id=str(workflow_id),
            )

    def clear(self) -> None:
        """Remove all entries from the cache."""
        self._entries.clear()
        self._path_index.clear()
        logger.debug("workflow_cache_cleared")

    def stats(self) -> dict[str, int]:
        """Return cache statistics.

        Returns:
            Dict with size and max_size.
        """
        return {
            "size": len(self._entries),
            "max_size": self._max_size,
        }

    def _remove(self, workflow_id: uuid.UUID) -> None:
        """Remove an entry and clean up its path index."""
        self._remove_path_index(workflow_id)
        self._entries.pop(workflow_id, None)

    def _remove_path_index(self, workflow_id: uuid.UUID) -> None:
        """Remove the webhook_path index entry for a workflow."""
        entry = self._entries.get(workflow_id)
        if entry and entry.workflow.webhook_path:
            self._path_index.pop(entry.workflow.webhook_path, None)


# Module-level singleton instance
workflow_cache = WorkflowCache()
