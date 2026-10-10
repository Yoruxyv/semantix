"""HTTP presentation over the authoritative official store, not another cache.

Only request counters are server-owned telemetry. No entry, vector, revision,
expiry or access-order index is retained here.

The store owns hit confirmation and entry lifecycle. This adapter converts
models, delegates already-authorized inspection/deletion and translates expected
storage failures. Counters use process memory unless a counter pool is supplied;
PostgreSQL telemetry uses its own server table/scope. Entry effects and counter
updates are separate operations, not one transaction or a rollback guarantee.
Memory eviction/expiration deltas are forwarded to the optional event recorder;
the same mechanism is not supplied for PostgreSQL or Redis stores.
"""

import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, TypeAlias

import asyncpg
from asyncpg.pool import Pool

from app.cache.api.schemas import (
    CacheEntryListResponse,
    CacheEntryMetadata,
    CacheEntrySort,
    CacheStatsResponse,
)
from app.cache.domain.metadata import TRUNCATED_RESPONSE_PREVIEW_MESSAGE
from app.cache.domain.models import CacheCandidate, CacheEntry
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.cache.domain.protocols import CacheEventRecorder
from app.core.exceptions import CacheStorageError
from semantix_cache import CacheEntry as OfficialEntry
from semantix_cache import MemoryStore, SemantixCacheError
from semantix_cache.inspection import InspectionEntry

if TYPE_CHECKING:
    from semantix_cache.stores.pgvector import PgVectorStore
    from semantix_cache.stores.redis import RedisStore

OfficialStore: TypeAlias = "MemoryStore | PgVectorStore | RedisStore"


@dataclass(slots=True)
class CacheCounters:
    """Process-local server hit/miss totals for one namespace.

    These counters do not own entries, expiry, LRU or authoritative store hit metadata.
    """

    hits: int = 0
    misses: int = 0


class OfficialStoreBackend:
    """Adapt a borrowed concrete package store to the server CacheBackend port.

    The composing lifespan closes the store; this wrapper has no separate storage
    engine or resource close API. Inspection stays separate from revision-aware
    hit confirmation. Callers provide authorized namespaces; the adapter does not
    authenticate principals or make telemetry an entry-storage authority.
    """

    def __init__(
        self,
        store: OfficialStore,
        *,
        events: CacheEventRecorder | None = None,
        counter_pool: Pool | None = None,
        counter_scope: str | None = None,
        operation_timeout_seconds: float | None = None,
    ) -> None:
        """Bind borrowed storage, optional telemetry pool and operation deadline.

        Args:
            store: Authoritative MemoryStore, PgVectorStore or RedisStore to delegate to.
            events: Optional synchronous recorder for observed MemoryStore event deltas.
            counter_pool: Borrowed PostgreSQL pool for server counters, or None for local.
            counter_scope: Telemetry partition; defaults to the store embedding identity.
            operation_timeout_seconds: Shared operation/telemetry deadline, or None.
        """
        self.store = store
        self._events = events
        self._counter_pool = counter_pool
        self._operation_timeout_seconds = operation_timeout_seconds
        self._counter_scope = counter_scope or store.embedding_space.identity
        self._counters: dict[str, CacheCounters] = {}
        self._observed_events = (0, 0)

    @property
    def default_ttl_seconds(self) -> float | None:
        return self.store.default_ttl_seconds

    @asynccontextmanager
    async def _operation(self) -> AsyncGenerator[None, None]:
        """Cover native storage and server telemetry with one optional deadline.

        Expected package, OS (including deadline timeout) and asyncpg failures become
        CacheStorageError without raw cause text. Cancellation propagates. Finally
        forwards newly observed MemoryStore eviction/expiration deltas when configured;
        it does not make the store mutation and telemetry update atomic.
        """
        try:
            # The same deadline covers native storage and shared-pool telemetry.
            async with asyncio.timeout(self._operation_timeout_seconds):
                yield
        except (
            SemantixCacheError,
            OSError,
            asyncpg.PostgresError,
            asyncpg.InterfaceError,
        ):
            raise CacheStorageError("Official cache operation failed") from None
        finally:
            if isinstance(self.store, MemoryStore) and self._events is not None:
                evictions, expirations = self.store.inspection_events
                old_evictions, old_expirations = self._observed_events
                self._events.record_evictions(evictions - old_evictions)
                self._events.record_expirations(expirations - old_expirations)
                self._observed_events = (evictions, expirations)

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheCandidate | None:
        """Convert a package candidate into validated server models without a hit.

        Store selection alone does not confirm the revision or increment server hits.
        """
        async with self._operation():
            match = await self.store.find_nearest(embedding, namespace=namespace)
            if match is None:
                return None
            return CacheCandidate(
                entry=CacheEntry.model_validate(match.entry.model_dump()),
                similarity_score=match.similarity_score,
            )

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        """Validate/convert a server entry and delegate TTL/capacity/expiry to storage.

        The store owns revision allocation and persistence semantics; no parallel copy
        of the entry is retained by this adapter.
        """
        async with self._operation():
            await self.store.put(
                OfficialEntry.model_validate(entry.model_dump()),
                ttl_seconds=ttl_seconds,
            )

    async def _count(self, namespace: str, *, hit: bool) -> None:
        if self._counter_pool is not None:
            # This existing server-owned table stores telemetry only. Legacy cache
            # entries are never read, mutated or adopted by the official store.
            async with self._counter_pool.acquire() as connection:
                await connection.execute(
                    """INSERT INTO semantix.cache_namespace_counters
                    (embedding_space,namespace,hits,misses) VALUES ($1,$2,$3,$4)
                    ON CONFLICT (embedding_space,namespace) DO UPDATE SET
                    hits=semantix.cache_namespace_counters.hits+EXCLUDED.hits,
                    misses=semantix.cache_namespace_counters.misses+EXCLUDED.misses""",
                    self._counter_scope,
                    namespace,
                    int(hit),
                    int(not hit),
                )
        else:
            counters = self._counters.setdefault(namespace, CacheCounters())
            if hit:
                counters.hits += 1
            else:
                counters.misses += 1

    async def record_hit(
        self, cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        """Delegate atomic store revision confirmation, then count a confirmed hit.

        Args:
            cache_key: Selected candidate key in the bound store.
            namespace: Exact authorized namespace for confirmation.
            expected_created_at: Revision timestamp from the candidate entry.

        Returns:
            True only if the store confirms and subsequent server counting succeeds;
            False when confirmation rejects the candidate. Telemetry failure can raise
            after the store has already applied hit/LRU effects; no rollback is promised.
        """
        async with self._operation():
            confirmed = await self.store.record_hit(
                cache_key,
                namespace=namespace,
                expected_created_at=expected_created_at,
            )
            if confirmed is True:
                await self._count(namespace, hit=True)
            return confirmed is True

    async def record_miss(self, namespace: str) -> None:
        """Count one server miss without mutating authoritative entry/hit state."""
        async with self._operation():
            await self._count(namespace, hit=False)

    async def list_entries(
        self,
        *,
        offset: int,
        limit: int,
        namespace: str | None,
        search: str | None,
        sort: CacheEntrySort,
    ) -> CacheEntryListResponse:
        """Delegate observational pagination and convert previews to server metadata.

        The caller authorizes scope; results neither confirm hits nor guarantee stable
        cross-request pages. Truncated previews use the server omission message.
        """
        async with self._operation():
            page = await self.store.inspect_entries(
                offset=offset,
                limit=limit,
                namespace=namespace,
                search=search,
                sort=sort,
            )
            return CacheEntryListResponse(
                items=[self._metadata(item) for item in page.items],
                total=page.total,
                offset=page.offset,
                limit=page.limit,
                has_more=page.has_more,
            )

    @staticmethod
    def _metadata(entry: InspectionEntry) -> CacheEntryMetadata:
        values = entry.model_dump()
        if entry.response_preview_truncated:
            values["response_preview"] = TRUNCATED_RESPONSE_PREVIEW_MESSAGE
        return CacheEntryMetadata.model_validate(values)

    async def get_entry(
        self, cache_key: str, *, authorized_namespaces: AuthorizedNamespaceScope
    ) -> CacheEntryMetadata | None:
        """Inspect a key within authorized scope without recording a hit.

        None scope permits all namespaces, an empty set none. Storage returns no entry
        for excluded/absent keys; the service maps that result to its safe not-found error.
        """
        async with self._operation():
            entry = await self.store.inspect_entry(
                cache_key,
                namespaces=None
                if authorized_namespaces is None
                else tuple(sorted(authorized_namespaces)),
            )
            return None if entry is None else self._metadata(entry)

    async def delete_entry(
        self, cache_key: str, *, authorized_namespaces: AuthorizedNamespaceScope
    ) -> bool:
        """Resolve an authorized key observation, then delete in its observed namespace.

        Inspection and deletion are separate calls, not a revision-conditional delete
        transaction. False covers an absent/excluded observation or unsuccessful delete.
        """
        async with self._operation():
            entry = await self.store.inspect_entry(
                cache_key,
                namespaces=None
                if authorized_namespaces is None
                else tuple(sorted(authorized_namespaces)),
            )
            if entry is None:
                return False
            return await self.store.delete_entry(cache_key, namespace=entry.namespace)

    async def clear(self, namespace: str | None) -> None:
        """Clear namespace/all store entries, then reset matching server counters.

        The caller authorizes scope. A telemetry failure may follow a completed clear;
        counter reset and entry clearing do not form one atomic transaction.
        """
        async with self._operation():
            if namespace is None:
                await self.store.clear_all()
            else:
                await self.store.clear(namespace=namespace)
            if self._counter_pool is not None:
                async with self._counter_pool.acquire() as connection:
                    await connection.execute(
                        """DELETE FROM semantix.cache_namespace_counters
                        WHERE embedding_space=$1 AND ($2::text IS NULL OR namespace=$2)""",
                        self._counter_scope,
                        namespace,
                    )
            elif namespace is None:
                self._counters.clear()
            else:
                self._counters.pop(namespace, None)

    async def stats(self, namespace: str | None) -> CacheStatsResponse:
        """Combine observed live-entry count with separately read server counters.

        None aggregates namespaces within this binding/counter scope. Local totals are
        process-owned; PostgreSQL totals use the server telemetry table. Size and counts
        are not one atomic snapshot and do not expose authoritative entry contents.
        """
        async with self._operation():
            page = await self.store.inspect_entries(namespace=namespace, limit=1)
            if self._counter_pool is not None:
                async with self._counter_pool.acquire() as connection:
                    row = await connection.fetchrow(
                        """SELECT COALESCE(SUM(hits),0) AS hits,
                        COALESCE(SUM(misses),0) AS misses FROM semantix.cache_namespace_counters
                        WHERE embedding_space=$1 AND ($2::text IS NULL OR namespace=$2)""",
                        self._counter_scope,
                        namespace,
                    )
                if row is None:
                    raise CacheStorageError("Cache telemetry is unavailable")
                hits, misses = int(row["hits"]), int(row["misses"])
            else:
                counters = [
                    value
                    for key, value in self._counters.items()
                    if namespace is None or key == namespace
                ]
                hits = sum(value.hits for value in counters)
                misses = sum(value.misses for value in counters)
            return CacheStatsResponse(
                size=page.total,
                hits=hits,
                misses=misses,
                hit_rate=0.0 if hits + misses == 0 else hits / (hits + misses),
            )
