from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import cast

import asyncpg
from asyncpg import Connection
from asyncpg.pool import Pool

from app.cache.api.schemas import (
    CacheEntryListResponse,
    CacheEntryMetadata,
    CacheEntrySort,
    CacheStatsResponse,
)
from app.cache.domain.models import CacheCandidate, CacheEntry
from app.cache.domain.namespaces import AuthorizedNamespaceScope
from app.cache.domain.protocols import CacheEventRecorder
from app.cache.domain.vector_validation import (
    validated_cache_vector,
    vector_literal,
)
from app.cache.infrastructure.backends.pgvector_records import (
    cache_entry_from_record,
    cache_metadata_from_record,
)
from app.cache.infrastructure.backends.pgvector_sql import (
    ADVISORY_LOCK,
    CLEAR_COUNTERS,
    CLEAR_ENTRIES,
    COUNT_ENTRIES,
    COUNTER_TOTALS,
    DELETE_ENTRY,
    DELETE_OVERFLOW,
    FIND_NEAREST,
    GET_ENTRY,
    PURGE_EXPIRED,
    PUT_ENTRY,
    RECORD_HIT,
    RECORD_MISS,
    list_entries_query,
)
from app.core.exceptions import CacheStorageError


def _deleted_rows(command_status: str) -> int:
    operation, separator, count = command_status.partition(" ")
    if operation != "DELETE" or not separator or not count.isdigit():
        raise CacheStorageError("Persistent cache returned an invalid command status")
    return int(count)


class PgVectorCacheBackend:
    """Persistent pgvector store scoped to one embedding model and dimension."""

    def __init__(
        self,
        pool: Pool,
        max_size: int,
        ttl_seconds: float | None,
        *,
        dimensions: int,
        embedding_space: str,
        events: CacheEventRecorder | None = None,
    ) -> None:
        if (
            max_size < 1
            or dimensions < 1
            or not embedding_space.strip()
            or (ttl_seconds is not None and ttl_seconds <= 0)
        ):
            raise ValueError("Invalid cache policy")
        self._pool = pool
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._dimensions = dimensions
        self._embedding_space = embedding_space
        self._events = events

    @property
    def default_ttl_seconds(self) -> float | None:
        return self._ttl_seconds

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[Connection]:
        try:
            async with self._pool.acquire() as connection:
                yield cast(Connection, connection)
        except CacheStorageError:
            raise
        except (OSError, TimeoutError, asyncpg.PostgresError) as error:
            raise CacheStorageError("Persistent cache operation failed") from error

    async def _purge_expired(self, connection: Connection) -> None:
        result = await connection.execute(PURGE_EXPIRED, self._embedding_space)
        expired_count = _deleted_rows(result)
        if expired_count and self._events is not None:
            self._events.record_expirations(expired_count)

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
        async with self._connection() as connection:
            await self._purge_expired(connection)
            row = await connection.fetchrow(
                FIND_NEAREST,
                self._embedding_space,
                self._dimensions,
                namespace,
                vector_literal(query),
            )
        if row is None:
            return None

        score = max(-1.0, min(1.0, float(row["similarity_score"])))
        return CacheCandidate(
            entry=cache_entry_from_record(
                row,
                dimensions=self._dimensions,
            ),
            similarity_score=score,
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
        embedding = validated_cache_vector(
            entry.embedding,
            dimensions=self._dimensions,
            description="Stored",
        )
        async with self._connection() as connection, connection.transaction():
            await connection.execute(
                ADVISORY_LOCK,
                self._embedding_space,
            )
            await self._purge_expired(connection)
            await connection.execute(
                PUT_ENTRY,
                self._embedding_space,
                self._dimensions,
                entry.cache_key,
                entry.namespace,
                entry.prompt,
                entry.response,
                vector_literal(embedding),
                entry.created_at,
                effective_ttl_seconds,
            )
            overflow_result = await connection.execute(
                DELETE_OVERFLOW,
                self._embedding_space,
                self._max_size,
            )
            eviction_count = _deleted_rows(overflow_result)
            if eviction_count and self._events is not None:
                self._events.record_evictions(eviction_count)

    async def record_hit(
        self,
        cache_key: str,
        *,
        expected_created_at: datetime,
    ) -> bool:
        async with self._connection() as connection, connection.transaction():
            await self._purge_expired(connection)
            result = await connection.fetchval(
                RECORD_HIT,
                self._embedding_space,
                cache_key,
                expected_created_at,
            )
        return result is not None

    async def record_miss(self, namespace: str) -> None:
        async with self._connection() as connection:
            await connection.execute(
                RECORD_MISS,
                self._embedding_space,
                namespace,
            )

    async def list_entries(
        self,
        *,
        offset: int,
        limit: int,
        namespace: str | None,
        search: str | None,
        sort: CacheEntrySort,
    ) -> CacheEntryListResponse:
        normalized_search = None if search is None else search.strip()
        if not normalized_search:
            normalized_search = None

        async with self._connection() as connection:
            await self._purge_expired(connection)
            async with connection.transaction(
                isolation="repeatable_read",
                readonly=True,
            ):
                total = int(
                    await connection.fetchval(
                        COUNT_ENTRIES,
                        self._embedding_space,
                        namespace,
                        normalized_search,
                    )
                )
                rows = await connection.fetch(
                    list_entries_query(sort),
                    self._embedding_space,
                    namespace,
                    normalized_search,
                    limit,
                    offset,
                )

        items = [cache_metadata_from_record(row) for row in rows]
        return CacheEntryListResponse(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
            has_more=offset + len(items) < total,
        )

    async def get_entry(
        self,
        cache_key: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> CacheEntryMetadata | None:
        async with self._connection() as connection:
            await self._purge_expired(connection)
            row = await connection.fetchrow(
                GET_ENTRY,
                self._embedding_space,
                cache_key,
                (
                    None
                    if authorized_namespaces is None
                    else list(authorized_namespaces)
                ),
            )
        return (
            None
            if row is None
            else cache_metadata_from_record(row, include_response=True)
        )

    async def delete_entry(
        self,
        cache_key: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> bool:
        async with self._connection() as connection:
            await self._purge_expired(connection)
            result = await connection.execute(
                DELETE_ENTRY,
                self._embedding_space,
                cache_key,
                (
                    None
                    if authorized_namespaces is None
                    else list(authorized_namespaces)
                ),
            )
        return result == "DELETE 1"

    async def clear(self, namespace: str | None) -> None:
        async with self._connection() as connection, connection.transaction():
            await connection.execute(
                CLEAR_ENTRIES,
                self._embedding_space,
                namespace,
            )
            await connection.execute(
                CLEAR_COUNTERS,
                self._embedding_space,
                namespace,
            )

    async def stats(self, namespace: str | None) -> CacheStatsResponse:
        async with self._connection() as connection:
            await self._purge_expired(connection)
            async with connection.transaction(
                isolation="repeatable_read",
                readonly=True,
            ):
                size = int(
                    await connection.fetchval(
                        COUNT_ENTRIES,
                        self._embedding_space,
                        namespace,
                        None,
                    )
                )
                counters = await connection.fetchrow(
                    COUNTER_TOTALS,
                    self._embedding_space,
                    namespace,
                )
        if counters is None:
            raise CacheStorageError("Cache counters could not be read")

        hits = int(counters["hits"])
        misses = int(counters["misses"])
        total = hits + misses
        return CacheStatsResponse(
            size=size,
            hits=hits,
            misses=misses,
            hit_rate=0.0 if total == 0 else hits / total,
        )
