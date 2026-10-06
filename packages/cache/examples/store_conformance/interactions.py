"""Cache ownership, optional observability, and asynchronous store interactions."""
# ruff: noqa: S101
# This module is a pytest contract, not production assertion-based validation.

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from semantix_cache import AsyncSemanticCache, CacheBusyError, CacheTimeoutError

from . import HitMetadata, StoreFactory
from .cases import FixedEmbedding, StoreContract, entry


class StoreConformance(StoreContract):
    """Subclass with a test-prefixed name and provide the store_factory fixture."""

    async def test_optional_hit_metadata(self, store_factory: StoreFactory) -> None:
        case = await store_factory(32, 10)
        read = case.read_hit_metadata
        if read is None:
            pytest.skip("Backend does not expose persisted hit counters/last-access")
        store = case.store
        value = entry("metadata")
        await store.put(value)
        initial = await read(value.cache_key, "default")
        assert initial == HitMetadata(0, None)
        match = await store.find_nearest((1, 0), namespace="default")
        assert match is not None
        assert await read(value.cache_key, "default") == initial
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at - timedelta(microseconds=1),
        )
        assert await read(value.cache_key, "default") == initial
        assert await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
        confirmed = await read(value.cache_key, "default")
        assert confirmed is not None
        assert confirmed.count == 1
        assert confirmed.last_accessed is not None
        async with AsyncSemanticCache(
            embedder=FixedEmbedding(store.embedding_space, (1, 0)), store=store
        ) as cache:
            assert await cache.get("metadata") is not None
        second = await read(value.cache_key, "default")
        assert second is not None
        assert second.count == 2
        assert second.last_accessed is not None
        assert second.last_accessed >= confirmed.last_accessed
        await store.put(value)
        assert await read(value.cache_key, "default") == initial
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
        assert await read(value.cache_key, "default") == initial
        expired = await store.find_nearest((1, 0), namespace="default")
        assert expired is not None
        await case.expire()
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=expired.entry.created_at,
        )
        remaining = await read(value.cache_key, "default")
        assert remaining is None or remaining == initial

    async def test_cache_borrows_store(self, store_factory: StoreFactory) -> None:
        store = (await store_factory()).store
        value = entry("borrowed")
        await store.put(value)
        async with AsyncSemanticCache(
            embedder=FixedEmbedding(store.embedding_space, (1, 0)), store=store
        ) as cache:
            assert await cache.get("borrowed") is not None
        assert await store.find_nearest((1, 0), namespace="default") is not None
        await store.put(entry("still open"))

    @pytest.mark.parametrize("mutation", ["replace", "delete", "clear", "expire"])
    async def test_candidate_confirmation_interleaving(
        self, store_factory: StoreFactory, mutation: str
    ) -> None:
        case = await store_factory(32, 10)
        store = case.store
        value = entry("interleaved")
        await store.put(value)
        candidate_ready, mutated = asyncio.Event(), asyncio.Event()

        async def reader() -> bool:
            match = await store.find_nearest((1, 0), namespace="default")
            assert match is not None
            candidate_ready.set()
            await mutated.wait()
            return await store.record_hit(
                value.cache_key,
                namespace="default",
                expected_created_at=match.entry.created_at,
            )

        async def writer() -> None:
            await candidate_ready.wait()
            if mutation == "replace":
                await store.put(value.model_copy(update={"response": "replacement"}))
            elif mutation == "delete":
                assert await store.delete_entry(value.cache_key, namespace="default")
            elif mutation == "clear":
                assert await store.clear(namespace="default") == 1
            else:
                await case.expire()
            mutated.set()

        results = await asyncio.wait_for(asyncio.gather(reader(), writer()), timeout=5)
        assert results[0] is False

    async def test_concurrent_same_key_and_scoped_mutations(
        self, store_factory: StoreFactory
    ) -> None:
        store = (await store_factory()).store
        value = entry("shared", created_at=datetime(2020, 1, 1, tzinfo=UTC))
        await asyncio.gather(
            *(
                store.put(value.model_copy(update={"response": str(n)}))
                for n in range(8)
            )
        )
        match = await store.find_nearest((1, 0), namespace="default")
        assert match is not None
        assert match.entry.response in {str(n) for n in range(8)}
        assert match.entry.created_at >= value.created_at + timedelta(microseconds=7)
        confirmations = await asyncio.gather(
            *(
                store.record_hit(
                    value.cache_key,
                    namespace="default",
                    expected_created_at=match.entry.created_at,
                )
                for _ in range(8)
            )
        )
        assert confirmations == [True] * 8
        candidate, _ = await asyncio.gather(
            store.find_nearest((1, 0), namespace="default"), store.put(value)
        )
        if candidate is not None:
            current = await store.find_nearest((1, 0), namespace="default")
            assert current is not None
            assert await store.record_hit(
                value.cache_key,
                namespace="default",
                expected_created_at=candidate.entry.created_at,
            ) == (candidate.entry.created_at == current.entry.created_at)
        _, deleted = await asyncio.gather(
            store.find_nearest((1, 0), namespace="default"),
            store.delete_entry(value.cache_key, namespace="default"),
        )
        assert deleted is True
        assert not await store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
        await store.put(value)
        _, cleared = await asyncio.gather(
            store.find_nearest((1, 0), namespace="default"),
            store.clear(namespace="default"),
        )
        assert cleared == 1
        assert await store.find_nearest((1, 0), namespace="default") is None
        await store.put(value)
        current = await store.find_nearest((1, 0), namespace="default")
        assert current is not None
        confirmed, deleted = await asyncio.gather(
            store.record_hit(
                value.cache_key,
                namespace="default",
                expected_created_at=current.entry.created_at,
            ),
            store.delete_entry(value.cache_key, namespace="default"),
        )
        assert isinstance(confirmed, bool)
        assert deleted is True
        assert await store.find_nearest((1, 0), namespace="default") is None

    async def test_optional_busy_close_and_cancellation(
        self, store_factory: StoreFactory
    ) -> None:
        case = await store_factory()
        if case.block_lookup is None:
            pytest.skip(
                "Backend lookup has no controllable asynchronous blocking boundary"
            )
        await case.store.put(entry("blocked"))
        async with case.block_lookup() as entered:
            task = asyncio.create_task(
                case.store.find_nearest((1, 0), namespace="default")
            )
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                with pytest.raises(CacheBusyError):
                    await case.store.aclose()
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        assert await case.store.find_nearest((1, 0), namespace="default") is not None

    async def test_optional_cache_timeout_propagation(
        self, store_factory: StoreFactory
    ) -> None:
        case = await store_factory()
        if case.block_lookup is None:
            pytest.skip(
                "Backend lookup has no controllable asynchronous blocking boundary"
            )
        await case.store.put(entry("timeout"))
        async with (
            AsyncSemanticCache(
                embedder=FixedEmbedding(case.store.embedding_space, (1, 0)),
                store=case.store,
                operation_timeout_seconds=0.1,
            ) as cache,
            case.block_lookup() as entered,
        ):
            task = asyncio.create_task(cache.get("timeout"))
            try:
                await asyncio.wait_for(entered.wait(), timeout=5)
                with pytest.raises(CacheTimeoutError):
                    await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        assert await case.store.find_nearest((1, 0), namespace="default") is not None
