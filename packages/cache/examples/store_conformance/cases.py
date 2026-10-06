"""Reusable public-boundary cases; backend SQL/worker checks stay separate."""
# ruff: noqa: S101, ARG002
# This module is a pytest contract, not production assertion-based validation.

import asyncio
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from semantix_cache import (
    AsyncSemanticCache,
    CacheClosedError,
    CacheEntry,
    CacheMatch,
    CacheStoreError,
    CacheValidationError,
    EmbeddingSpace,
    EmbeddingSpaceError,
)

from . import SPACE, StoreFactory


def entry(
    prompt: str,
    *,
    namespace: str = "default",
    vector: tuple[float, ...] = (1, 0),
    created_at: datetime | None = None,
    response: str = "approved synthetic answer",
) -> CacheEntry:
    """Only already-canonical synthetic prompts; no private normalizer needed."""
    return CacheEntry(
        cache_key=hashlib.sha256((namespace + "\0" + prompt).encode()).hexdigest(),
        namespace=namespace,
        prompt=prompt,
        response=response,
        embedding=vector,
        created_at=created_at or datetime.now(UTC),
    )


class FixedEmbedding:
    def __init__(self, space: EmbeddingSpace, vector: Sequence[float]) -> None:
        self.embedding_space = space
        self.vector = vector

    async def embed(self, text: str) -> Sequence[float]:
        return self.vector


class StoreContract:
    """Core storage obligations, inherited by the public developer test class."""

    async def test_empty_exact_similar_and_threshold(
        self, store_factory: StoreFactory
    ) -> None:
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
        adapter = FixedEmbedding(store.embedding_space, (0, 1))
        async with AsyncSemanticCache(embedder=adapter, store=store) as cache:
            assert await cache.get("different", namespace="a") is None
        assert isinstance(exact, CacheMatch)
        assert exact.entry.response == value.response

    async def test_namespace_isolation_scoped_mutations(
        self, store_factory: StoreFactory
    ) -> None:
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

    async def test_revision_and_detached_candidate(
        self, store_factory: StoreFactory
    ) -> None:
        store = (await store_factory(32, None)).store
        value = entry("revision", created_at=datetime(2020, 1, 1, tzinfo=UTC))
        await store.put(value)
        old = await store.find_nearest((1, 0), namespace="default")
        assert old is not None
        await store.put(value)
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=old.entry.created_at,
        )
        new = await store.find_nearest((1, 0), namespace="default")
        assert new is not None
        assert new.entry.created_at > old.entry.created_at
        assert old.entry.created_at == value.created_at
        await store.clear(namespace="default")
        await store.put(value)
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=new.entry.created_at,
        )

    async def test_expiry_retention_cap_and_non_sliding_hit(
        self, store_factory: StoreFactory
    ) -> None:
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
            value.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
        again = await store.find_nearest((1, 0), namespace="default")
        assert again is not None
        assert again.expires_at == match.expires_at
        await case.expire()
        assert await store.find_nearest((1, 0), namespace="default") is None
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
        assert await store.clear(namespace="default") == 0

    async def test_no_expiry_shorter_override_and_tie_order(
        self, store_factory: StoreFactory
    ) -> None:
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
        after_hit = await store.find_nearest((1, 0), namespace="default")
        assert after_hit is not None
        assert after_hit.entry.cache_key == match.entry.cache_key
        await store.put(entry("short", namespace="short"), ttl_seconds=1)
        await case.expire()
        assert await store.find_nearest((1, 0), namespace="short") is None
        assert (await store.find_nearest((1, 0), namespace="default")) is not None

    async def test_capacity_lru_across_namespaces(
        self, store_factory: StoreFactory
    ) -> None:
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
        # Candidate lookup alone does not refresh a's LRU order.
        await store.put(b)
        assert await store.find_nearest((1, 0), namespace="a") is None
        candidate = await store.find_nearest((1, 0), namespace="c")
        assert candidate is not None
        assert not await store.record_hit(
            c.cache_key,
            namespace="c",
            expected_created_at=candidate.entry.created_at - timedelta(microseconds=1),
        )
        await store.put(a)
        assert await store.find_nearest((1, 0), namespace="c") is None
        assert await store.find_nearest((1, 0), namespace="b") is not None

    async def test_concurrent_inserts_and_confirmations(
        self, store_factory: StoreFactory
    ) -> None:
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

    async def test_invalid_vectors_namespaces_and_ttl(
        self, store_factory: StoreFactory
    ) -> None:
        store = (await store_factory(32, None)).store
        for vector in (
            (0, 0),
            (1,),
            (1, 0, 0),
            (float("nan"), 0),
            (float("inf"), 0),
            (True, 0),
        ):
            with pytest.raises(CacheValidationError):
                await store.find_nearest(vector, namespace="default")
        with pytest.raises(CacheValidationError):
            await store.clear(namespace="*")
        with pytest.raises(CacheStoreError):
            await store.put(entry("bad", vector=(1,)), ttl_seconds=1)
        with pytest.raises(CacheStoreError):
            await store.put(entry("bad"), ttl_seconds=0)
        for vector in ((0, 0), (float("nan"), 0), (float("inf"), 0), (True, 0)):
            with pytest.raises(CacheStoreError) as failure:
                await store.put(
                    entry("synthetic-private-marker").model_copy(
                        update={"embedding": vector}
                    )
                )
            assert "synthetic-private-marker" not in str(failure.value)
            assert "synthetic-private-marker" not in repr(failure.value)
        assert await store.find_nearest((1, 0), namespace="default") is None

    async def test_close_double_close_and_no_reopen(
        self, store_factory: StoreFactory
    ) -> None:
        store = (await store_factory(32, None)).store
        await store.aclose()
        await store.aclose()
        with pytest.raises(CacheClosedError):
            await store.find_nearest((1, 0), namespace="default")
        with pytest.raises(CacheClosedError):
            await store.clear(namespace="default")
        with pytest.raises(CacheClosedError):
            await store.put(entry("closed"))
        with pytest.raises(CacheClosedError):
            await store.delete_entry(entry("closed").cache_key, namespace="default")
        with pytest.raises(CacheClosedError):
            await store.record_hit(
                entry("closed").cache_key,
                namespace="default",
                expected_created_at=datetime.now(UTC),
            )

    async def test_space_and_dimension_binding(
        self, store_factory: StoreFactory
    ) -> None:
        spaces = (
            SPACE,
            EmbeddingSpace(identity="conformance-other-v1", dimensions=2),
            EmbeddingSpace(identity=SPACE.identity, dimensions=3),
        )
        stores = [(await store_factory(space=space)).store for space in spaces]
        for store, space in zip(stores, spaces, strict=True):
            assert store.embedding_space == space
        await stores[0].put(entry("same", response=spaces[0].model_dump_json()))
        first = await stores[0].find_nearest((1, 0), namespace="default")
        assert first is not None
        for store, space in zip(stores[1:], spaces[1:], strict=True):
            vector = (1.0,) + (0.0,) * (space.dimensions - 1)
            assert await store.find_nearest(vector, namespace="default") is None
            assert not await store.record_hit(
                first.entry.cache_key,
                namespace="default",
                expected_created_at=first.entry.created_at,
            )
            await store.put(
                entry("same", vector=vector, response=space.model_dump_json())
            )
        assert await stores[0].clear(namespace="default") == 1
        for store, space in zip(stores[1:], spaces[1:], strict=True):
            vector = (1.0,) + (0.0,) * (space.dimensions - 1)
            match = await store.find_nearest(vector, namespace="default")
            assert match is not None
            assert match.entry.response == space.model_dump_json()
        with pytest.raises(EmbeddingSpaceError):
            AsyncSemanticCache(
                embedder=FixedEmbedding(spaces[1], (1, 0)), store=stores[0]
            )
        assert await stores[1].delete_entry(first.entry.cache_key, namespace="default")
        assert await stores[2].find_nearest((1, 0, 0), namespace="default") is not None

    @pytest.mark.parametrize("vector", [(1, 0), (0, 1), (0.8, 0.6)])
    async def test_inclusive_threshold_boundaries(
        self, store_factory: StoreFactory, vector: tuple[float, float]
    ) -> None:
        store = (await store_factory()).store
        await store.put(entry("boundary"))
        match = await store.find_nearest(vector, namespace="default")
        assert match is not None
        score = match.similarity_score
        # Use the actual score, respecting float32 vs float64 backend arithmetic.
        thresholds = {0.0, 1.0, score}
        if 0 < score < 1:
            thresholds.update((score - 1e-6, score + 1e-6))
        for threshold in sorted(thresholds):
            async with AsyncSemanticCache(
                embedder=FixedEmbedding(store.embedding_space, vector),
                store=store,
                similarity_threshold=threshold,
            ) as cache:
                hit = await cache.get("boundary query")
                assert (hit is not None) == (score >= threshold)

    async def test_replacement_content_revision_and_retention(
        self, store_factory: StoreFactory
    ) -> None:
        store = (await store_factory(32, 10)).store
        value = entry(
            "replace", response="old", created_at=datetime(2020, 1, 1, tzinfo=UTC)
        )
        await store.put(value, ttl_seconds=1)
        old = await store.find_nearest((1, 0), namespace="default")
        assert old is not None
        assert old.expires_at is not None
        await store.put(
            value.model_copy(update={"response": "new", "embedding": (0, 1)}),
            ttl_seconds=10,
        )
        new = await store.find_nearest((0, 1), namespace="default")
        assert new is not None
        assert new.expires_at is not None
        assert new.entry.response == "new"
        assert new.entry.embedding == (0, 1)
        assert new.entry.created_at > old.entry.created_at
        assert new.expires_at > old.expires_at + timedelta(seconds=8)
        assert old.entry.response == "old"
        assert old.entry.embedding == (1, 0)
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=old.entry.created_at,
        )
        assert await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=new.entry.created_at,
        )
        await store.delete_entry(value.cache_key, namespace="default")
        await store.put(value)
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=new.entry.created_at,
        )
