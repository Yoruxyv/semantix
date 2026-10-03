import asyncio
import threading
from datetime import UTC, datetime, timedelta, tzinfo
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray
from pydantic import ValidationError

from semantix_cache import (
    AsyncSemanticCache,
    CacheBusyError,
    CacheClosedError,
    CacheConfigurationError,
    CacheEntry,
    CacheMatch,
    CacheStoreError,
    CacheValidationError,
    EmbeddingSpace,
    MemoryStore,
    engine,
    memory,
)
from semantix_cache._semantics import prompt_cache_key

from .conftest import Adapter, generate


def entry(
    prompt: str,
    *,
    namespace: str = "default",
    vector: tuple[float, ...] = (1.0, 0.0),
    created_at: datetime | None = None,
) -> CacheEntry:
    return CacheEntry(
        cache_key=prompt_cache_key(prompt, namespace=namespace),
        namespace=namespace,
        prompt=prompt,
        response="response " + prompt,
        embedding=vector,
        created_at=datetime.now(UTC) if created_at is None else created_at,
    )


@pytest.mark.parametrize("capacity", [0, -1, 5001, True, 1.5])
def test_capacity_validation(capacity: object) -> None:
    with pytest.raises(CacheConfigurationError):
        MemoryStore(
            embedding_space=EmbeddingSpace(identity="test", dimensions=2),
            max_size=cast(int, capacity),
        )


@pytest.mark.parametrize("capacity", [1, 500, 5000])
def test_capacity_boundaries(capacity: int) -> None:
    assert MemoryStore(
        embedding_space=EmbeddingSpace(identity="test", dimensions=2),
        max_size=capacity,
    ).default_ttl_seconds == pytest.approx(3600.0)


@pytest.mark.parametrize("ttl", [-1, 0, True, float("nan"), float("inf"), 31_536_001])
def test_store_ttl_validation(ttl: object) -> None:
    with pytest.raises(CacheConfigurationError):
        MemoryStore(
            embedding_space=EmbeddingSpace(identity="test", dimensions=2),
            default_ttl_seconds=cast(float, ttl),
        )


async def test_ttl_exact_boundary_cap_and_overwrite(
    adapter: Adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    store = MemoryStore(
        embedding_space=adapter.embedding_space, default_ttl_seconds=2.0
    )
    value = entry("prompt")
    await store.put(value, ttl_seconds=100.0)
    match = await store.find_nearest((1.0, 0.0), namespace="default")
    assert match is not None
    assert match.expires_at is not None
    assert match.expires_at.tzinfo == UTC
    assert 1.0 < (match.expires_at - datetime.now(UTC)).total_seconds() <= 2.0
    now = 101.0
    assert await store.record_hit(
        value.cache_key, namespace="default", expected_created_at=match.entry.created_at
    )
    now = 102.0
    assert await store.find_nearest((1.0, 0.0), namespace="default") is None
    assert not await store.record_hit(
        value.cache_key, namespace="default", expected_created_at=match.entry.created_at
    )
    await store.put(value, ttl_seconds=0.5)
    now = 102.25
    await store.put(value, ttl_seconds=0.5)
    now = 102.5
    replacement = await store.find_nearest((1.0, 0.0), namespace="default")
    assert replacement is not None
    assert replacement.entry.created_at > match.entry.created_at
    now = 102.75
    assert await store.clear(namespace="default") == 0


async def test_no_expiry_and_inherited_default(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 0.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    store = MemoryStore(
        embedding_space=adapter.embedding_space, default_ttl_seconds=None
    )
    await store.put(entry("forever"))
    now = 1e9
    match = await store.find_nearest((1.0, 0.0), namespace="default")
    assert match is not None
    assert match.expires_at is None
    await store.put(entry("short"), ttl_seconds=0.25)
    now += 0.25
    assert await store.clear(namespace="default") == 1


async def test_lru_across_namespaces_and_scoped_mutations(adapter: Adapter) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space, max_size=2)
    a, b, c = (
        entry("a", namespace="a"),
        entry("b", namespace="b"),
        entry("c", namespace="c"),
    )
    await store.put(a)
    await store.put(b)
    # A search alone must not update LRU; only confirmed hits do.
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
    assert not await store.delete_entry(a.cache_key, namespace="b")
    assert await store.clear(namespace="c") == 1
    assert await store.delete_entry(a.cache_key, namespace="a")
    assert not await store.delete_entry(a.cache_key, namespace="a")
    await store.put(a)
    await store.put(b)
    assert await store.find_nearest((1, 0), namespace="a") is not None
    await store.put(c)
    assert await store.find_nearest((1, 0), namespace="a") is None


async def test_tie_breaking_not_lru_and_revision_staleness(adapter: Adapter) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space)
    old = datetime.now(UTC) - timedelta(days=1)
    a, b = entry("a", created_at=old), entry("b", created_at=old)
    await store.put(a)
    await store.put(b)
    match = await store.find_nearest((1, 0), namespace="default")
    assert match is not None
    assert match.entry.prompt == "a"
    assert await store.record_hit(
        a.cache_key, namespace="default", expected_created_at=match.entry.created_at
    )
    again = await store.find_nearest((1, 0), namespace="default")
    assert again is not None
    assert again.entry.prompt == "a"
    await store.put(a)
    assert not await store.record_hit(
        a.cache_key, namespace="default", expected_created_at=match.entry.created_at
    )
    assert match.entry.created_at == old
    assign = match.entry.__setattr__
    with pytest.raises(ValidationError):
        assign("response", "mutated")
    # The numerical selection itself also specifies cache-key ordering for equal revisions.
    values = tuple(memory._Item(value, None, None) for value in (b, a))
    expected = min(a.cache_key, b.cache_key)
    assert memory._nearest(np.asarray([1.0, 0.0]), values).entry.cache_key == expected


async def test_malformed_direct_store_inputs(adapter: Adapter) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space)
    with pytest.raises(CacheStoreError):
        await store.put(entry("bad", vector=(1.0,)))
    with pytest.raises(CacheStoreError):
        await store.put(entry("bad").model_copy(update={"response": ""}))
    with pytest.raises(CacheStoreError):
        await store.put(cast(CacheEntry, object()))
    with pytest.raises(CacheStoreError):
        await store.put(entry("good"), ttl_seconds=0)
    with pytest.raises(CacheValidationError):
        await store.find_nearest((0, 0), namespace="default")
    with pytest.raises(CacheValidationError):
        await store.find_nearest((1, 0), namespace="*")
    with pytest.raises(CacheValidationError):
        await store.record_hit(
            "bad", namespace="default", expected_created_at=datetime.now(UTC)
        )
    with pytest.raises(CacheValidationError):
        await store.record_hit(
            entry("a").cache_key,
            namespace="default",
            expected_created_at=datetime(2020, 1, 1, tzinfo=UTC).replace(tzinfo=None),
        )
    with pytest.raises(CacheValidationError):
        await store.clear(namespace=cast(str, None))


async def test_store_context_and_close(adapter: Adapter) -> None:
    async with MemoryStore(embedding_space=adapter.embedding_space) as store:
        await store.put(entry("a"))
    await store.aclose()
    with pytest.raises(CacheClosedError):
        await store.find_nearest((1, 0), namespace="default")
    with pytest.raises(CacheClosedError):
        await store.__aenter__()


async def test_numerical_worker_cancellation_retains_slot(
    adapter: Adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    original = memory._nearest

    def blocked(
        query: NDArray[np.float64], items: tuple[memory._Item, ...]
    ) -> CacheMatch:
        started.set()
        if not release.wait(timeout=5):
            raise RuntimeError("Test worker was not released")
        return original(query, items)

    monkeypatch.setattr(memory, "_nearest", blocked)
    store = MemoryStore(embedding_space=adapter.embedding_space)
    await store.put(entry("a"))
    first = asyncio.create_task(store.find_nearest((1, 0), namespace="default"))
    assert await asyncio.to_thread(started.wait, 2)
    with pytest.raises(CacheBusyError):
        await store.aclose()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(CacheBusyError):
        await store.aclose()
    second = asyncio.create_task(store.find_nearest((1, 0), namespace="default"))
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    release.set()
    await asyncio.gather(*store._workers)
    await asyncio.sleep(0)  # Run completion callbacks; no elapsed-time dependency.
    assert await store.find_nearest((1, 0), namespace="default") is not None
    await store.aclose()


async def test_snapshot_replaced_during_worker(
    adapter: Adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space)
    value = entry("a")
    await store.put(value)
    original = memory._nearest
    started, release = threading.Event(), threading.Event()

    def blocked(
        query: NDArray[np.float64], items: tuple[memory._Item, ...]
    ) -> CacheMatch:
        started.set()
        if not release.wait(timeout=5):
            raise RuntimeError("Test worker was not released")
        return original(query, items)

    monkeypatch.setattr(memory, "_nearest", blocked)
    task = asyncio.create_task(store.find_nearest((1, 0), namespace="default"))
    assert await asyncio.to_thread(started.wait, 2)
    await store.put(value)
    release.set()
    assert await task is None


async def test_concurrent_namespaces_and_stores() -> None:
    adapters = [Adapter(identity="space-a"), Adapter(identity="space-b")]
    stores = [
        MemoryStore(embedding_space=adapter.embedding_space) for adapter in adapters
    ]
    caches = [
        AsyncSemanticCache(embedder=adapter, store=store)
        for adapter, store in zip(adapters, stores, strict=True)
    ]
    results = await asyncio.gather(
        *(
            cache.resolve(f"question-{n}", namespace=f"ns-{n}", generate=generate)
            for cache in caches
            for n in range(8)
        )
    )
    assert all(result.cache_written and not result.cache_hit for result in results)
    for cache in caches:
        assert await cache.clear(namespace="ns-0") == 1
        assert await cache.get("question", namespace="ns-1") is not None


async def test_memory_expiry_uses_monotonic_despite_wall_clock_jump(
    adapter: Adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    store = MemoryStore(embedding_space=adapter.embedding_space, default_ttl_seconds=1)
    cache = AsyncSemanticCache(embedder=adapter, store=store)
    await cache.set("seed", "cached")

    class FutureTime:
        @staticmethod
        def now(zone: tzinfo | None = None) -> datetime:
            return datetime.now(zone) + timedelta(days=1)

    monkeypatch.setattr(engine, "datetime", FutureTime)
    assert await cache.get("question") is not None
    now = 101.0
    assert await cache.get("question") is None
