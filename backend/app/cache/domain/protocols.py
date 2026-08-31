from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.cache.api.schemas import (
    CacheEntryListResponse,
    CacheEntryMetadata,
    CacheEntrySort,
    CacheStatsResponse,
)
from app.cache.domain.models import CacheCandidate, CacheEntry
from app.cache.domain.namespaces import AuthorizedNamespaceScope


class CacheBackend(Protocol):
    """Cache port for vectors produced by one model and dimension count.

    Persistent implementations must partition incompatible embedding spaces.
    """

    @property
    def default_ttl_seconds(self) -> float | None: ...

    async def find_nearest(
        self,
        embedding: Sequence[float],
        *,
        namespace: str,
    ) -> CacheCandidate | None: ...

    async def put(
        self,
        entry: CacheEntry,
        *,
        ttl_seconds: float | None = None,
    ) -> None: ...
    async def record_hit(
        self,
        cache_key: str,
        *,
        expected_created_at: datetime,
    ) -> bool: ...
    async def record_miss(self, namespace: str) -> None: ...

    async def list_entries(
        self,
        *,
        offset: int,
        limit: int,
        namespace: str | None,
        search: str | None,
        sort: CacheEntrySort,
    ) -> CacheEntryListResponse: ...

    async def get_entry(
        self,
        cache_key: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> CacheEntryMetadata | None: ...
    async def delete_entry(
        self,
        cache_key: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> bool: ...
    async def clear(self, namespace: str | None) -> None: ...
    async def stats(self, namespace: str | None) -> CacheStatsResponse: ...


class CacheEventRecorder(Protocol):
    def record_cache_hit(self) -> None: ...
    def record_cache_miss(self) -> None: ...
    def record_evictions(self, count: int) -> None: ...
    def record_expirations(self, count: int) -> None: ...
