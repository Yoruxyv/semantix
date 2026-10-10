"""Define server application ports around authoritative package storage.

CacheBackend includes HTTP inspection, management and server counters beyond
the embedded CacheStore engine port. OfficialStoreBackend adapts package stores
to it; the interfaces serve different boundaries without duplicating entry
authority. CacheEventRecorder observes application events, and ThresholdStore
optionally supplies shared global threshold state. Implementations are borrowed;
these protocols define no resource construction, ownership transfer or cleanup.
"""

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

    Nearest candidates are provisional until record_hit confirms namespace and
    created_at revision; rejection returns False rather than successful reuse.
    Inspection is observational and must not stand in for hit confirmation.
    get_entry/delete_entry receive an already-authorized set: None is unrestricted,
    an empty set grants no namespace. Callers authorize namespace/global listings,
    clearing and stats before delegation. Aggregate counters and entry mutations
    need not share an atomic transaction.
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
        namespace: str,
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
    """Observe hit/miss and eviction/expiration events, not authoritative entries.

    Callbacks are synchronous; their scope/durability belongs to the recorder.
    """

    def record_cache_hit(self) -> None: ...
    def record_cache_miss(self) -> None: ...
    def record_evictions(self, count: int) -> None: ...
    def record_expirations(self, count: int) -> None: ...


class ThresholdStore(Protocol):
    """Supply async shared global threshold reads/writes to SemanticCache.

    The HTTP layer authorizes changes. Storage implementations own persistence and
    failure behavior; this port does not synchronize the service's local property.
    """

    async def read_threshold(self) -> float: ...
    async def write_threshold(self, threshold: float) -> float: ...
