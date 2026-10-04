"""Reusable semantic-store behavior, independent of database driver methods.

Third-party adapter authors can reproduce these tests using their own factory and
expiry fixture. Database-specific transactions and connection failures have their
own integration cases. No pytest dependency enters the runtime package.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest

from examples import custom_store
from examples.custom_store import CompanyCacheStore
from semantix_cache import (
    AsyncSemanticCache,
    CacheClosedError,
    CacheMatch,
    CacheStore,
    CacheStoreError,
    CacheValidationError,
    EmbeddingSpace,
    MemoryStore,
    memory,
)
from semantix_cache.stores.pgvector import PgVectorStore

from .conftest import Adapter
from .test_memory import entry


@dataclass
class StoreCase:
    store: CacheStore
    expire: Callable[[], Awaitable[None]]


Factory = Callable[[int, float | None], Awaitable[StoreCase]]


@pytest.fixture(params=["memory", "company", "pgvector"])
async def store_factory(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    pg_pool: asyncpg.Pool | None,
) -> AsyncIterator[Factory]:
    stores: list[CacheStore] = []
    schemas: list[str] = []
    pool: asyncpg.Pool | None = None
    mode = request.param
    if mode == "pgvector":
        if pg_pool is None:
            pytest.skip("Set PGVECTOR_TEST_DATABASE_URL to a disposable database")
        pool = pg_pool
    now = [0.0]
    monkeypatch.setattr(memory, "monotonic", lambda: now[0])
    monkeypatch.setattr(custom_store, "monotonic", lambda: now[0])

    async def factory(capacity: int = 32, ttl: float | None = None) -> StoreCase:
        store: CacheStore
        schema = "cache_test_" + uuid4().hex
        space = EmbeddingSpace(identity="conformance-v1", dimensions=2)
        if mode == "pgvector":
            assert pool is not None
            pg = PgVectorStore(
                pool=pool,
                embedding_space=space,
                schema=schema,
                max_size=capacity,
                default_ttl_seconds=ttl,
            )
            await pg.initialize_schema(migration_pool=pool)
            schemas.append(schema)
            store = pg
        elif mode == "memory":
            store = MemoryStore(
                embedding_space=space, max_size=capacity, default_ttl_seconds=ttl
            )
        else:
            store = CompanyCacheStore(
                embedding_space=space, max_size=capacity, default_ttl_seconds=ttl
            )
        stores.append(store)

        async def expire() -> None:
            now[0] += 31536001
            if mode == "pgvector":
                assert pool is not None
                async with pool.acquire() as connection:
                    await connection.execute(
                        f'UPDATE "{schema}".cache_entries SET expires_at=clock_timestamp() WHERE expires_at IS NOT NULL'
                    )

        return StoreCase(store, expire)

    try:
        yield factory
    finally:
        for store in stores:
            await store.aclose()
        if pool is not None:
            for schema in schemas:
                assert schema.startswith("cache_test_")
                assert len(schema) == 43
                async with pool.acquire() as connection:
                    await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


async def test_empty_exact_similar_and_threshold(store_factory: Factory) -> None:
    case = await store_factory(32, None)
    store = case.store
    assert await store.find_nearest((1, 0), namespace="a") is None
    value = entry("seed", namespace="a", vector=(1, 0))
    await store.put(value)
    exact = await store.find_nearest((1, 0), namespace="a")
    assert exact is not None
    assert exact.similarity_score == pytest.approx(1)
    similar = await store.find_nearest((0.99, 0.1), namespace="a")
    assert similar is not None
    assert similar.similarity_score == pytest.approx(0.994937, abs=1e-6)
    adapter = Adapter(vector=(0, 1))
    adapter.space = store.embedding_space
    async with AsyncSemanticCache(embedder=adapter, store=store) as cache:
        assert await cache.get("different", namespace="a") is None
    assert isinstance(exact, CacheMatch)
    assert exact.entry.response == value.response


async def test_namespace_isolation_scoped_mutations(store_factory: Factory) -> None:
    store = (await store_factory(32, None)).store
    a, b = entry("same", namespace="a"), entry("same", namespace="b")
    await store.put(a)
    await store.put(b)
    assert await store.find_nearest((1, 0), namespace="foreign") is None
    assert not await store.delete_entry(a.cache_key, namespace="b")
    assert await store.clear(namespace="a") == 1
    assert await store.find_nearest((1, 0), namespace="b") is not None
    assert await store.delete_entry(b.cache_key, namespace="b")
    assert not await store.delete_entry(b.cache_key, namespace="b")


async def test_revision_and_detached_candidate(store_factory: Factory) -> None:
    store = (await store_factory(32, None)).store
    value = entry("revision", created_at=datetime(2020, 1, 1, tzinfo=UTC))
    await store.put(value)
    old = await store.find_nearest((1, 0), namespace="default")
    assert old is not None
    await store.put(value)
    assert not await store.record_hit(
        value.cache_key, namespace="default", expected_created_at=old.entry.created_at
    )
    new = await store.find_nearest((1, 0), namespace="default")
    assert new is not None
    assert new.entry.created_at > old.entry.created_at
    assert old.entry.created_at == value.created_at
    await store.clear(namespace="default")
    await store.put(value)
    assert not await store.record_hit(
        value.cache_key, namespace="default", expected_created_at=new.entry.created_at
    )


async def test_expiry_retention_cap_and_non_sliding_hit(store_factory: Factory) -> None:
    case = await store_factory(32, 5.0)
    store = case.store
    value = entry("expiring")
    before = datetime.now(UTC)
    await store.put(value, ttl_seconds=100)
    match = await store.find_nearest((1, 0), namespace="default")
    assert match is not None
    assert match.expires_at is not None
    assert 0 < (match.expires_at - before).total_seconds() < 6
    assert await store.record_hit(
        value.cache_key, namespace="default", expected_created_at=match.entry.created_at
    )
    again = await store.find_nearest((1, 0), namespace="default")
    assert again is not None
    assert again.expires_at == match.expires_at
    await case.expire()
    assert await store.find_nearest((1, 0), namespace="default") is None
    assert not await store.record_hit(
        value.cache_key, namespace="default", expected_created_at=match.entry.created_at
    )
    assert await store.clear(namespace="default") == 0


async def test_no_expiry_shorter_override_and_tie_order(store_factory: Factory) -> None:
    case = await store_factory(32, None)
    store = case.store
    old = datetime(2020, 1, 1, tzinfo=UTC)
    await store.put(entry("first", created_at=old))
    await store.put(entry("second", created_at=old))
    match = await store.find_nearest((1, 0), namespace="default")
    assert match is not None
    assert match.entry.prompt == "first"
    assert match.expires_at is None
    assert await store.record_hit(
        match.entry.cache_key,
        namespace="default",
        expected_created_at=match.entry.created_at,
    )
    await store.put(entry("short", namespace="short"), ttl_seconds=1)
    await case.expire()
    assert await store.find_nearest((1, 0), namespace="short") is None
    assert (await store.find_nearest((1, 0), namespace="default")) is not None


async def test_capacity_lru_across_namespaces(store_factory: Factory) -> None:
    store = (await store_factory(2, None)).store
    a, b, c = (
        entry("a", namespace="a"),
        entry("b", namespace="b"),
        entry("c", namespace="c"),
    )
    await store.put(a)
    await store.put(b)
    match = await store.find_nearest((1, 0), namespace="a")
    assert match is not None
    assert not await store.record_hit(
        a.cache_key, namespace="foreign", expected_created_at=match.entry.created_at
    )
    assert await store.record_hit(
        a.cache_key, namespace="a", expected_created_at=match.entry.created_at
    )
    await store.put(c)
    assert await store.find_nearest((1, 0), namespace="b") is None
    assert await store.find_nearest((1, 0), namespace="a") is not None
    # Searching c does not make it more recent than the next insert.
    await store.put(b)
    assert await store.find_nearest((1, 0), namespace="a") is None


async def test_concurrent_inserts_and_confirmations(store_factory: Factory) -> None:
    store = (await store_factory(32, None)).store
    values = [entry(f"question-{n}", namespace=f"ns-{n}") for n in range(16)]
    await asyncio.gather(*(store.put(value) for value in values))

    async def hit(value_namespace: str) -> None:
        match = await store.find_nearest((1, 0), namespace=value_namespace)
        assert match is not None
        assert await store.record_hit(
            match.entry.cache_key,
            namespace=value_namespace,
            expected_created_at=match.entry.created_at,
        )

    await asyncio.gather(*(hit(value.namespace) for value in values))
    assert (
        sum(
            await asyncio.gather(
                *(store.clear(namespace=value.namespace) for value in values)
            )
        )
        == 16
    )


async def test_invalid_vectors_namespaces_and_ttl(store_factory: Factory) -> None:
    store = (await store_factory(32, None)).store
    for vector in ((0, 0), (1,), (float("nan"), 0), (True, 0)):
        with pytest.raises(CacheValidationError):
            await store.find_nearest(vector, namespace="default")
    with pytest.raises(CacheValidationError):
        await store.clear(namespace="*")
    with pytest.raises(CacheStoreError):
        await store.put(entry("bad", vector=(1,)), ttl_seconds=1)
    with pytest.raises(CacheStoreError):
        await store.put(entry("bad"), ttl_seconds=0)


async def test_close_double_close_and_no_reopen(store_factory: Factory) -> None:
    store = (await store_factory(32, None)).store
    await store.aclose()
    await store.aclose()
    with pytest.raises(CacheClosedError):
        await store.find_nearest((1, 0), namespace="default")
    with pytest.raises(CacheClosedError):
        await store.clear(namespace="default")
