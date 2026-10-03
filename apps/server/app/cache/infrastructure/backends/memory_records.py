from dataclasses import dataclass
from datetime import datetime

from app.cache.api.schemas import (
    CacheEntryMetadata,
    CacheEntrySort,
)
from app.cache.domain.metadata import (
    response_preview,
    response_preview_is_truncated,
)
from app.cache.domain.models import CacheEntry


@dataclass(slots=True)
class StoredCacheItem:
    entry: CacheEntry
    expires_at_monotonic: float | None
    expires_at: datetime | None
    hit_count: int = 0
    last_accessed_at: datetime | None = None


@dataclass(slots=True)
class CacheCounters:
    hits: int = 0
    misses: int = 0


def entry_metadata(
    item: StoredCacheItem,
    *,
    include_response: bool = False,
    now_monotonic: float,
    recency_rank: int,
) -> CacheEntryMetadata:
    remaining_ttl = (
        None
        if item.expires_at_monotonic is None
        else max(0.0, item.expires_at_monotonic - now_monotonic)
    )
    return CacheEntryMetadata(
        cache_key=item.entry.cache_key,
        namespace=item.entry.namespace,
        prompt=item.entry.prompt,
        response_preview=response_preview(item.entry.response),
        response_preview_truncated=response_preview_is_truncated(item.entry.response),
        response=item.entry.response if include_response else None,
        created_at=item.entry.created_at,
        expires_at=item.expires_at,
        remaining_ttl_seconds=remaining_ttl,
        hit_count=item.hit_count,
        last_accessed_at=item.last_accessed_at,
        recency_rank=recency_rank,
        is_expired=False,
    )


def sort_entry_metadata(
    entries: list[CacheEntryMetadata],
    sort: CacheEntrySort,
) -> list[CacheEntryMetadata]:
    if sort == "oldest":
        return sorted(entries, key=lambda item: (item.created_at, item.cache_key))
    if sort == "most_hit":
        return sorted(
            entries,
            key=lambda item: (
                -item.hit_count,
                -item.created_at.timestamp(),
                item.cache_key,
            ),
        )
    if sort == "nearest_expiry":
        return sorted(
            entries,
            key=lambda item: (
                item.expires_at is None,
                (
                    float("inf")
                    if item.expires_at is None
                    else item.expires_at.timestamp()
                ),
                -item.created_at.timestamp(),
                item.cache_key,
            ),
        )
    return sorted(
        entries,
        key=lambda item: (-item.created_at.timestamp(), item.cache_key),
    )
