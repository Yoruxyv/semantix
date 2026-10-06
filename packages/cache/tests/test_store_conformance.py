"""Backend-owned setup for the one developer-facing conformance contract."""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from uuid import uuid4

import asyncpg
import numpy as np
import pytest
from numpy.typing import NDArray

from examples.store_conformance import (
    SPACE,
    HitMetadata,
    StoreCase,
    StoreConformance,
    StoreFactory,
)
from examples.test_custom_store_conformance import TestCompanyStore  # noqa: F401 -- pytest collects the external consumer
from semantix_cache import CacheMatch, CacheStore, EmbeddingSpace, MemoryStore, memory
from semantix_cache.stores.pgvector import PgVectorStore


@asynccontextmanager
async def _block_lookup(
    store: CacheStore, pool: asyncpg.Pool | None, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[asyncio.Event]:
    entered = asyncio.Event()
    if pool is not None:
        # Exhaust this fixture-owned pool and observe actual acquisition.
        original_acquire = type(pool).acquire
        async with AsyncExitStack() as stack:
            for _ in range(pool.get_max_size()):
                await stack.enter_async_context(original_acquire(pool))
            with monkeypatch.context() as patch:

                def acquire(
                    active_pool: asyncpg.Pool, *, timeout: float | None = None
                ) -> asyncpg.pool.PoolAcquireContext:
                    if active_pool is pool:
                        entered.set()
                    return original_acquire(active_pool, timeout=timeout)

                patch.setattr(type(pool), "acquire", acquire)
                yield entered
    else:
        # Numerical-worker admission/retention is a MemoryStore detail.
        # The kit itself uses only CacheStore's public operations.
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original_nearest = memory._nearest

        def nearest(
            query: NDArray[np.float64], items: tuple[memory._Item, ...]
        ) -> CacheMatch:
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(timeout=10):
                raise RuntimeError("Conformance worker was not released")
            return original_nearest(query, items)

        with monkeypatch.context() as patch:
            patch.setattr(memory, "_nearest", nearest)
            try:
                yield entered
            finally:
                release.set()
                # Public lookup queues behind and drains the retained worker.
                await store.find_nearest((1, 0), namespace="default")


@pytest.fixture(params=["memory", pytest.param("pgvector", marks=pytest.mark.pgvector)])
async def store_factory(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    pg_pool: asyncpg.Pool | None,
) -> AsyncIterator[StoreFactory]:
    stores: list[CacheStore] = []
    mode = request.param
    pool = pg_pool if mode == "pgvector" else None
    if mode == "pgvector" and pool is None:
        pytest.skip("Set PGVECTOR_TEST_DATABASE_URL to a disposable database")
    schema = "cache_test_" + uuid4().hex
    now = [0.0]
    monkeypatch.setattr(memory, "monotonic", lambda: now[0])

    async def factory(
        capacity: int = 32, ttl: float | None = None, *, space: EmbeddingSpace = SPACE
    ) -> StoreCase:
        store: CacheStore
        if pool is None:
            store = MemoryStore(
                embedding_space=space, max_size=capacity, default_ttl_seconds=ttl
            )
        else:
            pg = PgVectorStore(
                pool=pool,
                embedding_space=space,
                schema=schema,
                max_size=capacity,
                default_ttl_seconds=ttl,
            )
            await pg.initialize_schema(migration_pool=pool)
            store = pg
        stores.append(store)

        async def expire() -> None:
            now[0] += 31536001
            if pool is not None:
                async with pool.acquire() as connection:
                    await connection.execute(
                        f'UPDATE "{schema}".cache_entries SET expires_at=clock_timestamp() '
                        "WHERE embedding_space=$1 AND embedding_dimensions=$2 "
                        "AND expires_at IS NOT NULL",
                        space.identity,
                        space.dimensions,
                    )

        async def read_metadata(key: str, namespace: str) -> HitMetadata | None:
            assert pool is not None
            async with pool.acquire() as connection:
                row = await connection.fetchrow(
                    f'SELECT hit_count, last_accessed_at FROM "{schema}".cache_entries '
                    "WHERE embedding_space=$1 AND embedding_dimensions=$2 "
                    "AND namespace=$3 AND cache_key=$4",
                    space.identity,
                    space.dimensions,
                    namespace,
                    key,
                )
            return (
                None
                if row is None
                else HitMetadata(row["hit_count"], row["last_accessed_at"])
            )

        return StoreCase(
            store,
            expire,
            read_metadata if pool is not None else None,
            lambda: _block_lookup(store, pool, monkeypatch),
        )

    try:
        yield factory
    finally:
        for store in stores:
            await store.aclose()
        if pool is not None:
            assert schema.startswith("cache_test_")
            assert len(schema) == 43
            async with pool.acquire() as connection:
                await connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


class TestBuiltInStores(StoreConformance):
    """Real MemoryStore and PgVectorStore, not substitute wrappers."""
