"""Numerical snapshot reuse must preserve exact scores, scope and mutation behavior."""

import asyncio
import threading

import numpy as np
import pytest
from numpy.typing import NDArray

from semantix_cache import (
    AsyncSemanticCache,
    CacheMatch,
    EmbeddingSpace,
    MemoryStore,
    memory,
)
from semantix_cache._semantics import nearest_index, normalized_vector

from .conftest import Adapter
from .test_memory import entry


async def test_snapshot_reuse_readonly_and_lru_independence(adapter: Adapter) -> None:
    async with MemoryStore(embedding_space=adapter.embedding_space) as store:
        await store.put(entry("first", namespace="a"))
        await store.put(entry("second", namespace="b"))
        match = await store.find_nearest((1, 0), namespace="a")
        assert match is not None
        snapshot = store._snapshots["a"]
        assert snapshot.matrix is None  # One-use scopes retain no numerical buffer.
        assert snapshot.norms is None
        assert await store.find_nearest((1, 0), namespace="a") == match
        assert snapshot.matrix is not None
        assert snapshot.matrix.dtype == np.float64
        assert snapshot.matrix.shape == (1, 2)
        assert snapshot.matrix.flags.c_contiguous
        assert not snapshot.matrix.flags.writeable
        with pytest.raises(ValueError, match="read-only"):
            snapshot.matrix[0, 0] = 0
        assert snapshot.norms is not None
        assert snapshot.norms.dtype == np.float64
        assert snapshot.norms.shape == (1,)
        assert snapshot.norms.flags.owndata
        assert not snapshot.norms.flags.writeable
        np.testing.assert_array_equal(
            snapshot.norms, np.linalg.norm(snapshot.matrix, axis=1)
        )
        norms = snapshot.norms
        assert isinstance(match.entry.embedding, tuple)
        assert await store.record_hit(
            match.entry.cache_key,
            namespace="a",
            expected_created_at=match.entry.created_at,
        )
        assert await store.find_nearest((1, 0), namespace="a") == match
        assert store._snapshots["a"] is snapshot
        assert snapshot.norms is norms
        await store.put(entry("third", namespace="b"))
        assert store._snapshots["a"] is snapshot
        for n in range(30):
            assert await store.find_nearest((1, 0), namespace=f"empty-{n}") is None
        assert set(store._snapshots) == {"a"}
    assert not store._snapshots


async def test_snapshot_invalidation_on_overwrite_delete_clear_and_eviction(
    adapter: Adapter,
) -> None:
    async with MemoryStore(
        embedding_space=adapter.embedding_space, max_size=2
    ) as store:
        value = entry("first", namespace="a")
        await store.put(value)
        await store.put(entry("second", namespace="b"))
        old = await store.find_nearest((1, 0), namespace="a")
        assert old is not None
        await store.find_nearest((1, 0), namespace="b")
        await store.put(value.model_copy(update={"embedding": (0.0, 1.0)}))
        assert "a" not in store._snapshots
        assert "b" in store._snapshots
        changed = await store.find_nearest((1, 0), namespace="a")
        assert changed is not None
        assert changed.similarity_score == 0
        assert changed.entry.created_at > old.entry.created_at
        assert not await store.record_hit(
            value.cache_key, namespace="a", expected_created_at=old.entry.created_at
        )
        await store.put(entry("third", namespace="c"))
        assert "b" not in store._snapshots
        assert await store.find_nearest((1, 0), namespace="b") is None
        assert not await store.delete_entry(value.cache_key, namespace="foreign")
        assert "a" in store._snapshots
        assert await store.delete_entry(value.cache_key, namespace="a")
        assert "a" not in store._snapshots
        await store.find_nearest((1, 0), namespace="c")
        assert await store.clear(namespace="c") == 1
        assert not store._snapshots


async def test_snapshot_expiry_invalidates_only_affected_namespace(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 100.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    async with MemoryStore(
        embedding_space=adapter.embedding_space, default_ttl_seconds=None
    ) as store:
        await store.put(entry("short", namespace="a"), ttl_seconds=1)
        await store.put(entry("forever", namespace="b"))
        await store.find_nearest((1, 0), namespace="a")
        await store.find_nearest((1, 0), namespace="b")
        other = store._snapshots["b"]
        now += 1
        assert await store.find_nearest((1, 0), namespace="a") is None
        assert "a" not in store._snapshots
        assert store._snapshots["b"] is other


@pytest.mark.parametrize("dimensions", [2, 384, 1536, 3072])
async def test_snapshot_scores_bitwise_match_original_tuple_kernel(
    dimensions: int,
) -> None:
    rng = np.random.default_rng(2301)
    vectors = rng.normal(size=(32, dimensions))
    space = EmbeddingSpace(identity="snapshot-oracle", dimensions=dimensions)
    async with MemoryStore(embedding_space=space, default_ttl_seconds=None) as store:
        for index, vector in enumerate(vectors):
            await store.put(entry(str(index), vector=tuple(float(v) for v in vector)))
        ordered = sorted(
            store._items.values(),
            key=lambda item: (item.entry.created_at, item.entry.cache_key),
        )
        corpus = [item.entry.embedding for item in ordered]
        queries = [*vectors[:3], *rng.normal(size=(6, dimensions))]
        for raw in queries:
            values = tuple(float(v) for v in raw)
            query = normalized_vector(values, dimensions=dimensions)
            expected_index, expected_score = nearest_index(query, corpus)
            actual = await store.find_nearest(values, namespace="default")
            assert actual is not None
            assert actual.entry.cache_key == ordered[expected_index].entry.cache_key
            assert actual.similarity_score == expected_score


@pytest.mark.parametrize("target", [0.92 - 1e-8, 0.92, 0.92 + 1e-8])
async def test_cached_snapshot_threshold_boundary_matches_original(
    target: float, adapter: Adapter
) -> None:
    vector = (target, float(np.sqrt(1 - target * target)))
    async with MemoryStore(embedding_space=adapter.embedding_space) as store:
        await store.put(entry("boundary", vector=vector))
        stored = next(iter(store._items.values())).entry
        _, expected = nearest_index(np.asarray([1.0, 0.0]), [stored.embedding])
        for threshold in [expected, float(np.nextafter(expected, np.inf))]:
            async with AsyncSemanticCache(
                embedder=adapter, store=store, similarity_threshold=threshold
            ) as cache:
                hit = await cache.get("query")
                assert (hit is not None) == (expected >= threshold)
                if hit is not None:
                    assert hit.similarity_score == expected


async def test_prepared_snapshot_remains_owned_during_concurrent_overwrite(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with MemoryStore(embedding_space=adapter.embedding_space) as store:
        value = entry("original")
        await store.put(value)
        assert await store.find_nearest((1, 0), namespace="default") is not None
        assert await store.find_nearest((1, 0), namespace="default") is not None
        retired = store._snapshots["default"]
        assert retired.matrix is not None
        assert retired.norms is not None
        original = memory._nearest
        started, release = threading.Event(), threading.Event()

        def blocked(
            query: NDArray[np.float64], snapshot: memory._Snapshot
        ) -> CacheMatch:
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("Snapshot worker was not released")
            return original(query, snapshot)

        monkeypatch.setattr(memory, "_nearest", blocked)
        task = asyncio.create_task(store.find_nearest((1, 0), namespace="default"))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            await store.put(value.model_copy(update={"embedding": (0.0, 1.0)}))
            assert "default" not in store._snapshots
            np.testing.assert_array_equal(retired.matrix, [[1.0, 0.0]])
            assert not retired.matrix.flags.writeable
            np.testing.assert_array_equal(retired.norms, [1.0])
            assert not retired.norms.flags.writeable
        finally:
            release.set()
        assert await task is None
        current = await store.find_nearest((1, 0), namespace="default")
        assert current is not None
        assert current.similarity_score == 0


async def test_cached_equal_scores_keep_oldest_candidate_after_lru_hit(
    adapter: Adapter,
) -> None:
    async with MemoryStore(embedding_space=adapter.embedding_space) as store:
        await store.put(entry("oldest"))
        await store.put(entry("newer"))
        first = await store.find_nearest((1, 0), namespace="default")
        assert first is not None
        assert first.entry.prompt == "oldest"
        assert await store.find_nearest((1, 0), namespace="default") == first
        snapshot = store._snapshots["default"]
        assert snapshot.matrix is not None
        assert snapshot.norms is not None
        assert await store.record_hit(
            first.entry.cache_key,
            namespace="default",
            expected_created_at=first.entry.created_at,
        )
        for _ in range(3):
            assert await store.find_nearest((1, 0), namespace="default") == first
        assert store._snapshots["default"] is snapshot
