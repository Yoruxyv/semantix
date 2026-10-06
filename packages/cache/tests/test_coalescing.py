"""Opt-in caller equivalence, authoritative follower evidence and bounded cleanup."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Sequence
from contextvars import ContextVar
from datetime import datetime
from typing import Any
from uuid import uuid4

import asyncpg
import pytest

from semantix_cache import (
    AsyncSemanticCache,
    CacheBusyError,
    CacheClosedError,
    CacheEntry,
    CacheMatch,
    CachePolicy,
    CacheResult,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    EmbeddingSpace,
    EmbeddingSpaceError,
    GenerationError,
    MemoryStore,
    _coalescing,
    engine,
)
from semantix_cache.stores.pgvector import PgVectorStore

from .conftest import Adapter, SpyStore


class Generation:
    def __init__(
        self, error: BaseException | None = None, output: str = "answer"
    ) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.finish = asyncio.Event()
        self.error = error
        self.output = output

    async def __call__(self, prompt: str) -> str:
        self.calls += 1
        self.started.set()
        await self.finish.wait()
        if self.error is not None:
            raise self.error
        return self.output


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(3):
        while not predicate():  # noqa: ASYNC110 -- bounded test-only state observation
            await asyncio.sleep(0.001)


def drained(cache: AsyncSemanticCache) -> None:
    assert cache._flights.counts() == (0, 0, 0, 0)
    assert cache._state.active == 0
    snapshot = cache.coalescing_snapshot()
    if snapshot is not None:
        assert snapshot.followers_pending == 0
        assert snapshot.followers_joined == (
            snapshot.follower_hits
            + snapshot.follower_generated
            + snapshot.follower_errors
            + snapshot.follower_cancelled
            + snapshot.follower_timeouts
        )
        assert (
            snapshot.active_flights,
            snapshot.retained_flights,
            snapshot.participants,
        ) == (0, 0, 0)


@pytest.fixture(name="cache", params=[False, True], ids=["metrics-off", "metrics-on"])
def collected_cache(
    request: pytest.FixtureRequest, adapter: Adapter, store: SpyStore
) -> AsyncSemanticCache:
    return AsyncSemanticCache(
        embedder=adapter, store=store, collect_coalescing_metrics=request.param
    )


@pytest.fixture(autouse=True)
async def no_leaked_tasks() -> AsyncGenerator[None, None]:
    before = asyncio.all_tasks()
    yield
    await asyncio.sleep(0)
    extra = {t for t in asyncio.all_tasks() - before if t is not asyncio.current_task()}
    assert not extra


async def pair(
    cache: AsyncSemanticCache, generation: Generation, **kwargs: Any
) -> tuple[asyncio.Task[CacheResult], asyncio.Task[CacheResult]]:
    leader = asyncio.create_task(
        cache.resolve(
            "question", generate=generation, coalescing_key="epoch1", **kwargs
        )
    )
    await generation.started.wait()
    follower = asyncio.create_task(
        cache.resolve(
            "question", generate=generation, coalescing_key="epoch1", **kwargs
        )
    )
    await until(lambda: cache._flights.counts()[2] == 2)
    return leader, follower


async def test_equivalent_burst_truthful_results_and_prepared_embedding(
    cache: AsyncSemanticCache, store: SpyStore, adapter: Adapter
) -> None:
    generation = Generation()
    leader = asyncio.create_task(
        cache.resolve("  question\t", generate=generation, coalescing_key="epoch1")
    )
    await generation.started.wait()
    followers = [
        asyncio.create_task(
            cache.resolve("question", generate=generation, coalescing_key="epoch1")
        )
        for _ in range(31)
    ]
    await until(lambda: cache._flights.counts()[2] == 32)
    assert generation.calls == 1
    with pytest.raises(CacheBusyError):
        await cache.aclose()
    generation.finish.set()
    results = await asyncio.gather(leader, *followers)
    first, *rest = results
    assert first.provider_called
    assert first.cache_written
    assert not first.cache_hit
    assert all(r.response == "answer" for r in results)
    assert all(
        r.cache_hit
        and r.generation_skipped
        and not r.provider_called
        and not r.cache_written
        for r in rest
    )
    assert all(
        r.matched_prompt == "question"
        and r.cache_entry_created_at is not None
        and r.cache_entry_age_seconds is not None
        for r in rest
    )
    assert len({id(r) for r in results}) == 32
    assert store.calls.count("write") == 1
    assert store.calls.count("confirm") == 31
    assert len(adapter.calls) == 32
    drained(cache)
    await cache.aclose()
    await cache.aclose()
    assert not store._state.closed
    with pytest.raises(CacheClosedError):
        await cache.resolve("question", generate=generation, coalescing_key="epoch1")
    await store.aclose()


@pytest.mark.parametrize("policy", list(CachePolicy))
@pytest.mark.parametrize("key", [None, "epoch1"])
async def test_disabled_and_other_policies_remain_independent(
    cache: AsyncSemanticCache, store: SpyStore, policy: CachePolicy, key: str | None
) -> None:
    generation = Generation()
    tasks = [
        asyncio.create_task(
            cache.resolve(
                "question", generate=generation, policy=policy, coalescing_key=key
            )
        )
        for _ in range(4)
    ]
    coalesce = policy is CachePolicy.NORMAL and key is not None
    await until(
        lambda: cache._flights.counts()[2] == 4 if coalesce else generation.calls == 4
    )
    generation.finish.set()
    results = await asyncio.gather(*tasks)
    assert generation.calls == (1 if coalesce else 4)
    assert sum(r.cache_hit for r in results) == (3 if coalesce else 0)
    assert store.calls.count("write") == (
        1 if coalesce else 4 if policy._write_enabled else 0
    )
    drained(cache)
    await store.aclose()


class HostileString(str):
    def __hash__(self) -> int:
        raise AssertionError("user hashing must not execute")


@pytest.mark.parametrize(
    "key", ["", " \t", "a" * 257, "é" * 129, "\ud800", HostileString("epoch"), 123]
)
@pytest.mark.parametrize("policy", list(CachePolicy))
async def test_invalid_key_before_callbacks(
    cache: AsyncSemanticCache,
    store: SpyStore,
    adapter: Adapter,
    key: Any,
    policy: CachePolicy,
) -> None:
    generation = Generation()
    with pytest.raises(CacheValidationError):
        await cache.resolve(
            "question", generate=generation, coalescing_key=key, policy=policy
        )
    assert not generation.calls
    assert not store.calls
    assert not adapter.calls
    drained(cache)


@pytest.mark.parametrize(
    "change",
    [
        "prompt",
        "namespace",
        "ttl",
        "ttl-intent",
        "default-ttl",
        "key",
        "callable",
        "bound-method",
        "query",
        "signed-zero",
        "instance",
        "space",
        "threshold",
        "timeout",
    ],
)
async def test_non_equivalent_identities_never_join(change: str) -> None:
    adapter = Adapter()
    store = MemoryStore(embedding_space=adapter.embedding_space, default_ttl_seconds=1)
    cache = AsyncSemanticCache(
        collect_coalescing_metrics=True, embedder=adapter, store=store
    )
    generation = Generation()
    callable_first = generation.__call__ if change == "bound-method" else generation
    leader = asyncio.create_task(
        cache.resolve(
            "question",
            generate=callable_first,
            coalescing_key="epoch1",
            cache_ttl_seconds=2,
        )
    )
    await generation.started.wait()
    other_cache = cache
    prompt, namespace, key, ttl = "question", "default", "epoch1", 2.0
    other_generate = generation
    prompt = "different" if change == "prompt" else prompt
    namespace = "different" if change == "namespace" else namespace
    if change == "ttl":
        ttl = 0.5
    if change == "ttl-intent":
        ttl = 3  # both capped to 1, different intent
    if change == "default-ttl":
        store._ttl = 0.5
    if change == "key":
        key = "epoch2"
    if change == "query":
        adapter.vector = (0, 1)
    if change == "signed-zero":
        adapter.vector = (1, -0.0)
    if change == "threshold":
        cache._threshold = 0.95
    if change == "timeout":
        cache._timeout = 29
    if change in {"callable", "bound-method"}:

        async def wrapper(text: str) -> str:
            return await generation(text)

        second_callable = generation.__call__ if change == "bound-method" else wrapper
    else:
        second_callable = other_generate
    second_store = store
    if change == "instance":
        other_cache = AsyncSemanticCache(
            collect_coalescing_metrics=True, embedder=adapter, store=store
        )
    if change == "space":
        second_adapter = Adapter(identity="other-space")
        second_store = MemoryStore(embedding_space=second_adapter.embedding_space)
        other_cache = AsyncSemanticCache(
            collect_coalescing_metrics=True, embedder=second_adapter, store=second_store
        )
    follower = asyncio.create_task(
        other_cache.resolve(
            prompt,
            namespace=namespace,
            generate=second_callable,
            coalescing_key=key,
            cache_ttl_seconds=ttl,
        )
    )
    await until(lambda: generation.calls == 2)
    generation.finish.set()
    results = await asyncio.gather(leader, follower)
    assert all(r.provider_called and not r.cache_hit for r in results)
    drained(cache)
    drained(other_cache)
    await store.aclose()
    if second_store is not store:
        await second_store.aclose()


async def test_contextvars_use_distinct_explicit_keys(
    cache: AsyncSemanticCache, store: SpyStore
) -> None:
    context: ContextVar[str] = ContextVar("generation-snapshot")
    finish = asyncio.Event()
    calls: list[str] = []

    async def generate(prompt: str) -> str:
        calls.append(context.get())
        await finish.wait()
        return context.get()

    tasks = []
    for value in ["tenant-a", "tenant-b"]:
        context.set(value)
        tasks.append(
            asyncio.create_task(
                cache.resolve("question", generate=generate, coalescing_key=value)
            )
        )
    await until(lambda: len(calls) == 2)
    finish.set()
    assert [r.response for r in await asyncio.gather(*tasks)] == [
        "tenant-a",
        "tenant-b",
    ]
    drained(cache)
    await store.aclose()


@pytest.mark.parametrize("cancel_all", [False, True])
async def test_follower_cancellation_isolated(
    cache: AsyncSemanticCache, store: SpyStore, cancel_all: bool
) -> None:
    generation = Generation()
    leader, follower = await pair(cache, generation)
    other = asyncio.create_task(
        cache.resolve("question", generate=generation, coalescing_key="epoch1")
    )
    await until(lambda: cache._flights.counts()[2] == 3)
    follower.cancel()
    follower.cancel()
    if cancel_all:
        other.cancel()
    with pytest.raises(asyncio.CancelledError):
        await follower
    if cancel_all:
        with pytest.raises(asyncio.CancelledError):
            await other
    assert not leader.done()
    assert cache._flights.counts()[0] == 1
    generation.finish.set()
    assert (await leader).provider_called
    if not cancel_all:
        assert (await other).cache_hit
    assert generation.calls == 1
    drained(cache)
    await store.aclose()


async def test_leader_cancellation_fails_flight_no_promotion(
    cache: AsyncSemanticCache, store: SpyStore
) -> None:
    generation = Generation()
    leader, follower = await pair(cache, generation)
    leader.cancel()
    outcomes = await asyncio.gather(leader, follower, return_exceptions=True)
    assert all(isinstance(e, asyncio.CancelledError) for e in outcomes)
    assert generation.calls == 1
    assert not store.calls.count("write")
    drained(cache)
    generation.finish.set()
    assert (
        await cache.resolve("question", generate=generation, coalescing_key="epoch1")
    ).provider_called
    assert generation.calls == 2
    drained(cache)
    await store.aclose()


@pytest.mark.parametrize(
    "error",
    [
        GenerationError("provider"),
        RuntimeError("programming"),
        TimeoutError("callback timeout"),
    ],
)
async def test_provider_failure_shared_without_retry(
    cache: AsyncSemanticCache, store: SpyStore, error: BaseException
) -> None:
    generation = Generation(error=error)
    leader, follower = await pair(cache, generation)
    generation.finish.set()
    outcomes = await asyncio.gather(leader, follower, return_exceptions=True)
    assert all(type(e) is type(error) for e in outcomes)
    assert generation.calls == 1
    assert not store.calls.count("write")
    drained(cache)
    await store.aclose()


async def test_invalid_generation_output_is_failed_flight(
    cache: AsyncSemanticCache, store: SpyStore
) -> None:
    generation = Generation(output="")
    leader, follower = await pair(cache, generation)
    generation.finish.set()
    assert all(
        isinstance(e, GenerationError)
        for e in await asyncio.gather(leader, follower, return_exceptions=True)
    )
    assert generation.calls == 1
    drained(cache)
    await store.aclose()


async def test_leader_deadline_is_translated_before_followers_notified(
    adapter: Adapter, store: SpyStore
) -> None:
    cache = AsyncSemanticCache(
        collect_coalescing_metrics=True,
        embedder=adapter,
        store=store,
        operation_timeout_seconds=0.1,
    )
    generation = Generation()
    leader, follower = await pair(cache, generation)
    assert all(
        isinstance(e, CacheTimeoutError)
        for e in await asyncio.gather(leader, follower, return_exceptions=True)
    )
    assert generation.calls == 1
    drained(cache)
    await store.aclose()


async def test_follower_original_deadline_never_resets(store: SpyStore) -> None:
    blocked = asyncio.Event()
    unblock = asyncio.Event()

    class SlowFirstAdapter(Adapter):
        async def embed(self, text: str) -> Sequence[float]:
            if asyncio.current_task() is delayed:
                blocked.set()
                await unblock.wait()
            return await super().embed(text)

    adapter = SlowFirstAdapter()
    cache = AsyncSemanticCache(
        collect_coalescing_metrics=True,
        embedder=adapter,
        store=store,
        operation_timeout_seconds=0.2,
    )
    generation = Generation()
    delayed = asyncio.create_task(
        cache.resolve("question", generate=generation, coalescing_key="epoch1")
    )
    await blocked.wait()
    await asyncio.sleep(0.1)
    leader = asyncio.create_task(
        cache.resolve("question", generate=generation, coalescing_key="epoch1")
    )
    await generation.started.wait()
    unblock.set()
    await until(lambda: cache._flights.counts()[2] == 2)
    with pytest.raises(CacheTimeoutError):
        await delayed
    assert not leader.done()
    generation.finish.set()
    assert (await leader).provider_called
    assert generation.calls == 1
    snapshot = cache.coalescing_snapshot()
    if snapshot is not None:
        assert snapshot.follower_timeouts == snapshot.wait_count == 1
        assert snapshot.follower_generations_started == 0
    drained(cache)
    await store.aclose()


@pytest.mark.parametrize("phase", ["before-put", "after-put"])
async def test_persistence_failure_is_failed_flight(phase: str) -> None:
    adapter = Adapter()

    class FailingStore(SpyStore):
        async def put(
            self, entry: CacheEntry, *, ttl_seconds: float | None = None
        ) -> None:
            if phase == "after-put":
                await super().put(entry, ttl_seconds=ttl_seconds)
            raise CacheStoreError("persistence failed")

    store = FailingStore(adapter.embedding_space)
    cache = AsyncSemanticCache(
        collect_coalescing_metrics=True, embedder=adapter, store=store
    )
    generation = Generation()
    leader, follower = await pair(cache, generation)
    generation.finish.set()
    assert all(
        isinstance(e, CacheStoreError)
        for e in await asyncio.gather(leader, follower, return_exceptions=True)
    )
    assert generation.calls == 1
    snapshot = cache.coalescing_snapshot()
    if snapshot is not None:
        assert snapshot.follower_errors == snapshot.wait_count == 1
        assert snapshot.follower_generations_started == 0
    drained(cache)
    await store.aclose()


@pytest.mark.parametrize("phase", ["before-put", "after-put"])
async def test_leader_cancel_during_persistence(phase: str) -> None:
    adapter = Adapter()
    entered = asyncio.Event()
    block = asyncio.Event()

    class BlockingStore(SpyStore):
        async def put(
            self, entry: CacheEntry, *, ttl_seconds: float | None = None
        ) -> None:
            if phase == "after-put":
                await super().put(entry, ttl_seconds=ttl_seconds)
            entered.set()
            await block.wait()

    store = BlockingStore(adapter.embedding_space)
    cache = AsyncSemanticCache(
        collect_coalescing_metrics=True, embedder=adapter, store=store
    )
    generation = Generation()
    leader, follower = await pair(cache, generation)
    generation.finish.set()
    await entered.wait()
    leader.cancel()
    assert all(
        isinstance(e, asyncio.CancelledError)
        for e in await asyncio.gather(leader, follower, return_exceptions=True)
    )
    drained(cache)
    await store.aclose()


@pytest.mark.parametrize(
    "churn", ["expired", "delete", "clear", "revision", "replacement", "lookup-error"]
)
async def test_follower_requires_own_authoritative_confirmation(churn: str) -> None:
    adapter = Adapter()
    leader_task: asyncio.Task[CacheResult] | None = None

    class ChurningStore(SpyStore):
        changed = False

        async def find_nearest(
            self, embedding: Sequence[float], *, namespace: str
        ) -> CacheMatch | None:
            if (
                leader_task is not None
                and asyncio.current_task() is not leader_task
                and leader_task.done()
                and not self.changed
            ):
                self.changed = True
                if churn == "expired":
                    await asyncio.sleep(0.03)
                elif churn == "delete":
                    match = await super().find_nearest(embedding, namespace=namespace)
                    assert match is not None
                    await self.delete_entry(match.entry.cache_key, namespace=namespace)
                elif churn == "clear":
                    await self.clear(namespace=namespace)
                elif churn == "lookup-error":
                    raise CacheStoreError("lookup failed")
                elif churn == "replacement":
                    match = await super().find_nearest(embedding, namespace=namespace)
                    assert match is not None
                    await self.put(
                        match.entry.model_copy(
                            update={
                                "response": "replacement",
                                "created_at": datetime.now(
                                    match.entry.created_at.tzinfo
                                ),
                            }
                        )
                    )
            return await super().find_nearest(embedding, namespace=namespace)

        async def record_hit(
            self, cache_key: str, *, namespace: str, expected_created_at: datetime
        ) -> bool:
            if churn == "revision":
                await self.clear(namespace=namespace)
            return await super().record_hit(
                cache_key, namespace=namespace, expected_created_at=expected_created_at
            )

    store = ChurningStore(adapter.embedding_space)
    cache = AsyncSemanticCache(
        collect_coalescing_metrics=True, embedder=adapter, store=store
    )
    generation = Generation()
    leader_task, follower = await pair(
        cache, generation, cache_ttl_seconds=0.02 if churn == "expired" else None
    )
    generation.finish.set()
    first = await leader_task
    assert first.provider_called
    if churn == "lookup-error":
        with pytest.raises(CacheStoreError):
            await follower
        assert generation.calls == 1
    else:
        result = await follower
        if churn == "replacement":
            assert result.cache_hit
            assert result.response == "replacement"
            assert generation.calls == 1
        else:
            assert not result.cache_hit
            assert result.provider_called
            assert result.cache_written
            assert generation.calls == 2
    assert len(adapter.calls) == 2
    snapshot = cache.coalescing_snapshot()
    assert snapshot is not None
    assert snapshot.followers_joined == snapshot.wait_count == 1
    assert snapshot.follower_hits == (churn == "replacement")
    assert snapshot.follower_generated == (churn not in {"replacement", "lookup-error"})
    assert snapshot.follower_errors == (churn == "lookup-error")
    assert snapshot.follower_generations_started == snapshot.follower_generated
    drained(cache)
    await store.aclose()


@pytest.mark.parametrize("budget", ["records", "participants", "bytes"])
async def test_overflow_keeps_independent_generation(
    monkeypatch: pytest.MonkeyPatch,
    budget: str,
    cache: AsyncSemanticCache,
    store: SpyStore,
) -> None:
    monkeypatch.setattr(
        _coalescing,
        {
            "records": "_MAX_RECORDS",
            "participants": "_MAX_PARTICIPANTS",
            "bytes": "_MAX_KEY_BYTES",
        }[budget],
        1,
    )
    generation = Generation()
    leader = asyncio.create_task(
        cache.resolve("question", generate=generation, coalescing_key="epoch1")
    )
    await generation.started.wait()
    follower = asyncio.create_task(
        cache.resolve(
            "question",
            generate=generation,
            coalescing_key="epoch2" if budget == "records" else "epoch1",
        )
    )
    await until(lambda: generation.calls == 2)
    assert cache._flights.counts()[1] <= 1
    generation.finish.set()
    assert all(r.provider_called for r in await asyncio.gather(leader, follower))
    drained(cache)
    await store.aclose()


async def test_terminal_records_stay_charged_and_late_release_cannot_remove_new_flight() -> (
    None
):
    flights = _coalescing.Flights()
    generation = Generation()
    first = flights.admit((1, "identity"), generation)
    assert first is not None
    assert first.leader
    follower = flights.admit((1, "identity"), generation)
    assert follower is not None
    assert not follower.leader
    charged = flights.counts()[3]
    flights.settle(first.flight)
    flights.release(first.flight)
    assert flights.counts() == (0, 1, 1, charged)
    newer = flights.admit((1, "identity"), generation)
    assert newer is not None
    assert newer.leader
    flights.release(follower.flight)
    assert flights.counts() == (1, 1, 1, charged)
    flights.settle(newer.flight)
    flights.release(newer.flight)
    assert flights.counts() == (0, 0, 0, 0)


async def test_hit_never_touches_registry(
    cache: AsyncSemanticCache, store: SpyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await cache.set("question", "persisted")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("hot path entered registry")

    monkeypatch.setattr(cache._flights, "admit", forbidden)
    generation = Generation()
    for key in [None, "epoch1"]:
        assert (
            await cache.resolve("question", generate=generation, coalescing_key=key)
        ).cache_hit
    assert generation.calls == 0
    drained(cache)
    await store.aclose()


async def test_leader_recheck_closes_miss_to_admission_race(
    cache: AsyncSemanticCache, store: SpyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = cache._lookup
    reads = 0

    async def lookup(
        prompt: str, namespace: str, embedding: tuple[float, ...] | None = None
    ) -> engine._Lookup:
        nonlocal reads
        result = await original(prompt, namespace, embedding)
        reads += 1
        if reads == 1:
            await cache.set(prompt, "raced write", namespace=namespace)
        return result

    monkeypatch.setattr(cache, "_lookup", lookup)
    generation = Generation()
    result = await cache.resolve(
        "question", generate=generation, coalescing_key="epoch1"
    )
    assert result.cache_hit
    assert result.response == "raced write"
    assert not result.provider_called
    assert generation.calls == 0
    assert reads == 2
    snapshot = cache.coalescing_snapshot()
    if snapshot is not None:
        assert snapshot.leaders_admitted == 1
        assert snapshot.followers_joined == snapshot.wait_count == 0
    drained(cache)
    await store.aclose()


async def test_result_construction_failure_is_failed_flight(
    cache: AsyncSemanticCache, store: SpyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    generation = Generation()
    leader, follower = await pair(cache, generation)

    def broken(**kwargs: Any) -> CacheResult:
        raise RuntimeError("result construction failed")

    monkeypatch.setattr(engine, "CacheResult", broken)
    generation.finish.set()
    assert all(
        isinstance(e, RuntimeError)
        for e in await asyncio.gather(leader, follower, return_exceptions=True)
    )
    assert generation.calls == 1
    drained(cache)
    await store.aclose()


async def test_live_space_change_fails_flight(
    cache: AsyncSemanticCache, store: SpyStore, adapter: Adapter
) -> None:
    generation = Generation()
    leader, follower = await pair(cache, generation)
    adapter.space = adapter.space.model_copy(update={"identity": "changed"})
    generation.finish.set()
    assert all(
        isinstance(e, EmbeddingSpaceError)
        for e in await asyncio.gather(leader, follower, return_exceptions=True)
    )
    drained(cache)
    await store.aclose()


@pytest.mark.pgvector
async def test_postgresql_confirmation_ownership_and_pool_drain(
    pg_pool: asyncpg.Pool | None,
) -> None:
    if pg_pool is None:
        pytest.skip("Disposable database required")
    adapter = Adapter()
    schema = "coalescing_test_" + uuid4().hex
    store = PgVectorStore(
        pool=pg_pool, embedding_space=adapter.embedding_space, schema=schema
    )
    await store.initialize_schema(migration_pool=pg_pool)
    cache = AsyncSemanticCache(
        collect_coalescing_metrics=True, embedder=adapter, store=store
    )
    generation = Generation()
    try:
        leader, follower = await pair(cache, generation)
        generation.finish.set()
        results = await asyncio.gather(leader, follower)
        assert generation.calls == 1
        assert results[0].provider_called
        assert results[1].cache_hit
        async with pg_pool.acquire() as connection:
            row = await connection.fetchrow(
                f'SELECT hit_count, created_at FROM "{schema}".cache_entries'  # noqa: S608 -- generated UUID identifier
            )
        assert row is not None
        assert row["hit_count"] == 1
        assert results[1].cache_entry_created_at == row["created_at"]
        drained(cache)
        await cache.aclose()
        await store.aclose()
        assert not pg_pool.is_closing()
        assert pg_pool.get_size() == pg_pool.get_idle_size()
    finally:
        await store.aclose()
        async with pg_pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


async def test_cancel_leader_in_recheck_before_generation(
    cache: AsyncSemanticCache, store: SpyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = cache._lookup
    recheck = asyncio.Event()
    block = asyncio.Event()

    async def lookup(
        prompt: str, namespace: str, embedding: tuple[float, ...] | None = None
    ) -> engine._Lookup:
        if embedding is not None:
            recheck.set()
            await block.wait()
        return await original(prompt, namespace, embedding)

    monkeypatch.setattr(cache, "_lookup", lookup)
    generation = Generation()
    leader = asyncio.create_task(
        cache.resolve("question", generate=generation, coalescing_key="epoch1")
    )
    await recheck.wait()
    follower = asyncio.create_task(
        cache.resolve("question", generate=generation, coalescing_key="epoch1")
    )
    await until(lambda: cache._flights.counts()[2] == 2)
    leader.cancel()
    outcomes = await asyncio.gather(leader, follower, return_exceptions=True)
    assert all(isinstance(e, asyncio.CancelledError) for e in outcomes)
    assert generation.calls == 0
    drained(cache)
    await store.aclose()


async def test_failed_gate_is_observed_after_all_followers_cancel(
    cache: AsyncSemanticCache, store: SpyStore
) -> None:
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    warnings: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda loop, context: warnings.append(context))
    try:
        generation = Generation(error=RuntimeError("provider"))
        leader, follower = await pair(cache, generation)
        follower.cancel()
        with pytest.raises(asyncio.CancelledError):
            await follower
        generation.finish.set()
        with pytest.raises(RuntimeError):
            await leader
        drained(cache)
        await asyncio.sleep(0)
        assert warnings == []
    finally:
        loop.set_exception_handler(previous)
        await store.aclose()


async def test_guard_never_spans_dependencies_or_user_code() -> None:
    holder: list[AsyncSemanticCache] = []

    class GuardAdapter(Adapter):
        @property
        def embedding_space(self) -> EmbeddingSpace:
            if holder:
                assert not holder[0]._flights._guard.locked()
            return super().embedding_space

        async def embed(self, text: str) -> Sequence[float]:
            assert not cache._flights._guard.locked()
            return await super().embed(text)

    adapter = GuardAdapter()

    class GuardStore(SpyStore):
        async def find_nearest(
            self, embedding: Sequence[float], *, namespace: str
        ) -> CacheMatch | None:
            assert not cache._flights._guard.locked()
            return await super().find_nearest(embedding, namespace=namespace)

        async def record_hit(
            self, cache_key: str, *, namespace: str, expected_created_at: datetime
        ) -> bool:
            assert not cache._flights._guard.locked()
            return await super().record_hit(
                cache_key, namespace=namespace, expected_created_at=expected_created_at
            )

        async def put(
            self, entry: CacheEntry, *, ttl_seconds: float | None = None
        ) -> None:
            assert not cache._flights._guard.locked()
            await super().put(entry, ttl_seconds=ttl_seconds)

    store = GuardStore(adapter.embedding_space)
    cache = AsyncSemanticCache(
        collect_coalescing_metrics=True, embedder=adapter, store=store
    )
    holder.append(cache)
    generation = Generation()

    async def generate(prompt: str) -> str:
        assert not cache._flights._guard.locked()
        return await generation(prompt)

    leader = asyncio.create_task(
        cache.resolve("question", generate=generate, coalescing_key="epoch1")
    )
    await generation.started.wait()
    follower = asyncio.create_task(
        cache.resolve("question", generate=generate, coalescing_key="epoch1")
    )
    await until(lambda: cache._flights.counts()[2] == 2)
    generation.finish.set()
    assert (await leader).provider_called
    assert (await follower).cache_hit
    drained(cache)
    await store.aclose()


async def test_completed_records_enforce_every_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flights = _coalescing.Flights()
    generation = Generation()
    leader = flights.admit(("first",), generation)
    assert leader is not None
    follower = flights.admit(("first",), generation)
    assert follower is not None
    flights.settle(leader.flight)
    flights.release(leader.flight)
    monkeypatch.setattr(_coalescing, "_MAX_RECORDS", 1)
    assert flights.admit(("second",), generation) is None
    monkeypatch.setattr(_coalescing, "_MAX_RECORDS", 128)
    monkeypatch.setattr(_coalescing, "_MAX_PARTICIPANTS", 1)
    assert flights.admit(("second",), generation) is None
    monkeypatch.setattr(_coalescing, "_MAX_PARTICIPANTS", 256)
    monkeypatch.setattr(_coalescing, "_MAX_KEY_BYTES", flights.counts()[3])
    assert flights.admit(("second",), generation) is None
    flights.release(follower.flight)
    assert flights.counts() == (0, 0, 0, 0)


async def test_loop_identity_prevents_cross_loop_future_join() -> None:
    flights = _coalescing.Flights()
    generation = Generation()
    first = flights.admit((id(asyncio.get_running_loop()), "same"), generation)
    assert first is not None

    async def on_other_loop() -> bool:
        other = flights.admit((id(asyncio.get_running_loop()), "same"), generation)
        assert other is not None
        try:
            assert other.flight.gate.get_loop() is asyncio.get_running_loop()
            return other.leader
        finally:
            flights.settle(other.flight)
            flights.release(other.flight)

    assert await asyncio.to_thread(asyncio.run, on_other_loop())
    flights.settle(first.flight)
    flights.release(first.flight)
    assert flights.counts() == (0, 0, 0, 0)


async def test_follower_deterministic_tie_is_own_lookup_evidence(
    cache: AsyncSemanticCache, store: SpyStore
) -> None:
    generation = Generation()
    leader, follower = await pair(cache, generation)
    await cache.set("older tied candidate", "other truthful answer")
    generation.finish.set()
    assert (await leader).response == "answer"
    result = await follower
    assert result.cache_hit
    assert result.response == "other truthful answer"
    assert result.matched_prompt == "older tied candidate"
    assert generation.calls == 1
    drained(cache)
    await store.aclose()


@pytest.mark.parametrize("side", ["below", "equal", "above"])
async def test_follower_inclusive_threshold_nextafter(
    cache: AsyncSemanticCache,
    store: SpyStore,
    monkeypatch: pytest.MonkeyPatch,
    side: str,
) -> None:
    import math  # noqa: PLC0415 -- test-local numerical boundary

    original = store.find_nearest
    score = (
        math.nextafter(0.92, 0)
        if side == "below"
        else math.nextafter(0.92, 1)
        if side == "above"
        else 0.92
    )

    async def nearest(
        embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        match = await original(embedding, namespace=namespace)
        return (
            None
            if match is None
            else match.model_copy(update={"similarity_score": score})
        )

    monkeypatch.setattr(store, "find_nearest", nearest)
    generation = Generation()
    leader, follower = await pair(cache, generation)
    generation.finish.set()
    await leader
    result = await follower
    assert result.cache_hit == (side != "below")
    assert result.similarity_score == score
    assert generation.calls == (2 if side == "below" else 1)
    drained(cache)
    await store.aclose()


async def test_join_drops_temporary_numerical_key_before_wait(
    cache: AsyncSemanticCache, store: SpyStore
) -> None:
    generation = Generation()
    leader, follower = await pair(cache, generation)
    # A per-follower key copy would bypass the charged per-record byte bound.
    coroutine: Any = follower.get_coro()
    lookup_frames = []
    while coroutine is not None:
        frame = getattr(coroutine, "cr_frame", None)
        if frame is not None and frame.f_code.co_name == "lookup":
            lookup_frames.append(frame)
        coroutine = getattr(coroutine, "cr_await", None)
    assert len(lookup_frames) == 1
    assert "identity" not in lookup_frames[0].f_locals
    generation.finish.set()
    await asyncio.gather(leader, follower)
    drained(cache)
    await store.aclose()


@pytest.mark.parametrize("budget", ["records", "participants", "bytes"])
async def test_real_production_admission_caps(budget: str) -> None:
    flights = _coalescing.Flights()
    generation = Generation()
    admitted = []
    for index in range(300):
        identity: _coalescing.Identity = (
            id(asyncio.get_running_loop()),
            0 if budget == "participants" else index,
            bytes(65536) if budget == "bytes" else b"query",
        )
        participation = flights.admit(identity, generation)
        if participation is None:
            break
        admitted.append(participation)
    active, records, participants, charged = flights.counts()
    assert active <= 128
    assert records <= 128
    assert participants <= 256
    assert charged <= 4 * 1024 * 1024
    if budget == "records":
        assert records == 128
    elif budget == "participants":
        assert participants == 256
    else:
        assert records < 128
        assert charged > 3 * 1024 * 1024
    for participation in admitted:
        if participation.leader:
            flights.settle(participation.flight)
        flights.release(participation.flight)
    assert flights.counts() == (0, 0, 0, 0)


@pytest.mark.pgvector
@pytest.mark.parametrize("churn", ["revision", "checksum"])
async def test_postgresql_follower_churn_and_live_schema_checks(
    pg_pool: asyncpg.Pool | None, churn: str
) -> None:
    if pg_pool is None:
        pytest.skip("Disposable database required")
    adapter = Adapter()
    schema = "coalescing_test_" + uuid4().hex
    leader_task: asyncio.Task[CacheResult] | None = None

    class ChurningPgStore(PgVectorStore):
        changed = False

        async def find_nearest(
            self, embedding: Sequence[float], *, namespace: str
        ) -> CacheMatch | None:
            if (
                churn == "checksum"
                and leader_task is not None
                and leader_task.done()
                and not self.changed
            ):
                self.changed = True
                async with self._pool.acquire() as connection:
                    await connection.execute(
                        f'UPDATE "{schema}".schema_migrations SET checksum=$1',  # noqa: S608 -- generated UUID identifier
                        "tampered",
                    )
            return await super().find_nearest(embedding, namespace=namespace)

        async def record_hit(
            self, cache_key: str, *, namespace: str, expected_created_at: datetime
        ) -> bool:
            if churn == "revision" and not self.changed:
                self.changed = True
                async with self._pool.acquire() as connection:
                    await connection.execute(
                        f'UPDATE "{schema}".cache_entries SET created_at=clock_timestamp()',  # noqa: S608 -- generated UUID identifier
                    )
            return await super().record_hit(
                cache_key, namespace=namespace, expected_created_at=expected_created_at
            )

    store = ChurningPgStore(
        pool=pg_pool, embedding_space=adapter.embedding_space, schema=schema
    )
    await store.initialize_schema(migration_pool=pg_pool)
    cache = AsyncSemanticCache(
        collect_coalescing_metrics=True, embedder=adapter, store=store
    )
    generation = Generation()
    try:
        leader_task, follower = await pair(cache, generation)
        generation.finish.set()
        assert (await leader_task).provider_called
        if churn == "checksum":
            with pytest.raises(CacheStoreError):
                await follower
            assert generation.calls == 1
        else:
            result = await follower
            assert result.provider_called
            assert not result.cache_hit
            assert generation.calls == 2
        drained(cache)
        assert store._state.active == 0
        assert pg_pool.get_size() == pg_pool.get_idle_size()
        await cache.aclose()
    finally:
        await store.aclose()
        async with pg_pool.acquire() as connection:
            await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.mark.parametrize("key", ["a" * 256, "é" * 128, " epoch1 "])
async def test_valid_utf8_key_boundary_and_exact_text(
    cache: AsyncSemanticCache, store: SpyStore, key: str
) -> None:
    generation = Generation()
    generation.finish.set()
    result = await cache.resolve("question", generate=generation, coalescing_key=key)
    assert result.provider_called
    assert generation.calls == 1
    drained(cache)
    await store.aclose()


async def test_callable_equality_and_hash_are_never_used(
    cache: AsyncSemanticCache, store: SpyStore
) -> None:
    class HostileGeneration(Generation):
        def __eq__(self, other: object) -> bool:
            raise AssertionError("user equality executed")

        def __hash__(self) -> int:
            raise AssertionError("user hashing executed")

    generation = HostileGeneration()
    leader, follower = await pair(cache, generation)
    generation.finish.set()
    assert (await leader).provider_called
    assert (await follower).cache_hit
    assert generation.calls == 1
    drained(cache)
    await store.aclose()


async def test_swallowed_leader_cancellation_cannot_settle_success(
    cache: AsyncSemanticCache, store: SpyStore
) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = 0

    async def generate(prompt: str) -> str:
        nonlocal calls
        calls += 1
        started.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            return "swallowed cancellation"
        return "answer"

    leader = asyncio.create_task(
        cache.resolve("question", generate=generate, coalescing_key="epoch1")
    )
    await started.wait()
    follower = asyncio.create_task(
        cache.resolve("question", generate=generate, coalescing_key="epoch1")
    )
    await until(lambda: cache._flights.counts()[2] == 2)
    leader.cancel()
    outcomes = await asyncio.gather(leader, follower, return_exceptions=True)
    assert all(isinstance(e, asyncio.CancelledError) for e in outcomes)
    assert calls == 1
    assert store.calls.count("write") == 0
    drained(cache)
    await store.aclose()
