import asyncio
import time
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import numpy as np
from numpy.typing import NDArray

from app.cache.api.schemas import (
    CacheEntryListResponse,
    CacheEntryMetadata,
    CacheEntrySort,
    CacheStatsResponse,
)
from app.cache.domain.models import CacheCandidate, CacheEntry
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.cache.domain.protocols import CacheEventRecorder
from app.cache.domain.vector_validation import validated_cache_vector
from app.cache.infrastructure.backends.memory_records import (
    CacheCounters,
    StoredCacheItem,
    entry_metadata,
    sort_entry_metadata,
)
from app.core.exceptions import CacheStorageError


class InMemoryCacheBackend:
    """Single-process cosine vector store with TTL and LRU invalidation."""

    def __init__(
        self,
        max_size: int,
        ttl_seconds: float | None,
        *,
        dimensions: int,
        events: CacheEventRecorder | None = None,
    ) -> None:
        if (
            max_size < 1
            or dimensions < 1
            or (ttl_seconds is not None and ttl_seconds <= 0)
        ):
            raise ValueError("Invalid cache policy")
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._dimensions = dimensions
        self._events = events
        self._items: OrderedDict[str, StoredCacheItem] = OrderedDict()
        self._counters: dict[str, CacheCounters] = {}
        self._lock = asyncio.Lock()

    @property
    def default_ttl_seconds(self) -> float | None:
        return self._ttl_seconds

    def _purge(self, now_monotonic: float | None = None) -> None:
        now = time.monotonic() if now_monotonic is None else now_monotonic
        expired_keys = [
            key
            for key, item in self._items.items()
            if item.expires_at_monotonic is not None
            and item.expires_at_monotonic <= now
        ]
        for key in expired_keys:
            self._items.pop(key, None)
        if expired_keys and self._events is not None:
            self._events.record_expirations(len(expired_keys))

    async def find_nearest(
        self,
        embedding: Sequence[float],
        *,
        namespace: str,
    ) -> CacheCandidate | None:
        query = validated_cache_vector(
            embedding,
            dimensions=self._dimensions,
            description="Query",
        )
        async with self._lock:
            self._purge()
            items = [
                item
                for item in self._items.values()
                if item.entry.namespace == namespace
            ]
            if not items:
                return None
            matrix: NDArray[np.float64] = np.asarray(
                [item.entry.embedding for item in items], dtype=np.float64
            )
            norms = np.linalg.norm(matrix, axis=1)
            query_norm = float(np.linalg.norm(query))
            if np.any(norms <= np.finfo(np.float64).eps):
                raise CacheStorageError("Zero magnitude embedding")
            scores = (matrix @ query) / (norms * query_norm)
            index = int(np.argmax(scores))
            return CacheCandidate(
                entry=items[index].entry.model_copy(deep=True),
                similarity_score=max(-1.0, min(1.0, float(scores[index]))),
            )

    async def put(
        self,
        entry: CacheEntry,
        *,
        ttl_seconds: float | None = None,
    ) -> None:
        effective_ttl_seconds = (
            self._ttl_seconds if ttl_seconds is None else ttl_seconds
        )
        if effective_ttl_seconds is not None and effective_ttl_seconds <= 0:
            raise ValueError("Invalid cache policy")
        validated_cache_vector(
            entry.embedding,
            dimensions=self._dimensions,
            description="Stored",
        )
        async with self._lock:
            self._purge()
            latest_created_at = max(
                (item.entry.created_at for item in self._items.values()),
                default=None,
            )
            if latest_created_at is not None and entry.created_at <= latest_created_at:
                entry = entry.model_copy(
                    update={"created_at": latest_created_at + timedelta(microseconds=1)}
                )
            stored_at = datetime.now(UTC)
            expires_at_monotonic = None
            expires_at = None
            if effective_ttl_seconds is not None:
                expires_at_monotonic = time.monotonic() + effective_ttl_seconds
                expires_at = stored_at + timedelta(seconds=effective_ttl_seconds)
            self._items[entry.cache_key] = StoredCacheItem(
                entry=entry.model_copy(deep=True),
                expires_at_monotonic=expires_at_monotonic,
                expires_at=expires_at,
            )
            self._items.move_to_end(entry.cache_key)
            eviction_count = 0
            while len(self._items) > self._max_size:
                self._items.popitem(last=False)
                eviction_count += 1
            if eviction_count and self._events is not None:
                self._events.record_evictions(eviction_count)

    async def record_hit(
        self,
        cache_key: str,
        *,
        expected_created_at: datetime,
    ) -> bool:
        async with self._lock:
            self._purge()
            item = self._items.get(cache_key)
            if item is None or item.entry.created_at != expected_created_at:
                return False
            self._items.move_to_end(cache_key)
            counters = self._counters.setdefault(
                item.entry.namespace,
                CacheCounters(),
            )
            counters.hits += 1
            item.hit_count += 1
            item.last_accessed_at = datetime.now(UTC)
            return True

    async def record_miss(self, namespace: str) -> None:
        async with self._lock:
            self._purge()
            counters = self._counters.setdefault(
                namespace,
                CacheCounters(),
            )
            counters.misses += 1

    async def list_entries(
        self,
        *,
        offset: int,
        limit: int,
        namespace: str | None,
        search: str | None,
        sort: CacheEntrySort,
    ) -> CacheEntryListResponse:
        async with self._lock:
            now_monotonic = time.monotonic()
            self._purge(now_monotonic)
            filtered_items = [
                (cache_key, item)
                for cache_key, item in self._items.items()
                if namespace is None or item.entry.namespace == namespace
            ]
            recency_ranks = {
                cache_key: rank
                for rank, (cache_key, _) in enumerate(
                    reversed(filtered_items),
                    start=1,
                )
            }
            entries = [
                entry_metadata(
                    item,
                    now_monotonic=now_monotonic,
                    recency_rank=recency_ranks[cache_key],
                )
                for cache_key, item in filtered_items
            ]

            normalized_search = None if search is None else search.strip().casefold()
            if normalized_search:
                entries = [
                    item
                    for item in entries
                    if normalized_search in item.prompt.casefold()
                ]

            ordered_entries = sort_entry_metadata(entries, sort)
            total = len(ordered_entries)
            page = ordered_entries[offset : offset + limit]
            return CacheEntryListResponse(
                items=page,
                total=total,
                offset=offset,
                limit=limit,
                has_more=offset + len(page) < total,
            )

    async def get_entry(
        self,
        cache_key: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> CacheEntryMetadata | None:
        async with self._lock:
            now_monotonic = time.monotonic()
            self._purge(now_monotonic)
            item = self._items.get(cache_key)
            if item is None or (
                authorized_namespaces is not None
                and item.entry.namespace not in authorized_namespaces
            ):
                return None
            recency_rank = next(
                rank
                for rank, current_key in enumerate(reversed(self._items), start=1)
                if current_key == cache_key
            )
            return entry_metadata(
                item,
                include_response=True,
                now_monotonic=now_monotonic,
                recency_rank=recency_rank,
            )

    async def delete_entry(
        self,
        cache_key: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> bool:
        async with self._lock:
            self._purge()
            item = self._items.get(cache_key)
            if item is None or (
                authorized_namespaces is not None
                and item.entry.namespace not in authorized_namespaces
            ):
                return False
            del self._items[cache_key]
            return True

    async def clear(self, namespace: str | None) -> None:
        async with self._lock:
            if namespace is None:
                self._items.clear()
                self._counters.clear()
                return

            for cache_key in [
                key
                for key, item in self._items.items()
                if item.entry.namespace == namespace
            ]:
                del self._items[cache_key]
            self._counters.pop(namespace, None)

    async def stats(self, namespace: str | None) -> CacheStatsResponse:
        async with self._lock:
            self._purge()
            if namespace is None:
                size = len(self._items)
                hits = sum(item.hits for item in self._counters.values())
                misses = sum(item.misses for item in self._counters.values())
            else:
                size = sum(
                    item.entry.namespace == namespace for item in self._items.values()
                )
                counters = self._counters.get(namespace, CacheCounters())
                hits = counters.hits
                misses = counters.misses
            total = hits + misses
            return CacheStatsResponse(
                size=size,
                hits=hits,
                misses=misses,
                hit_rate=0.0 if total == 0 else hits / total,
            )
