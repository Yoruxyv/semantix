"""Numeric coalescing evidence, isolation and observation without runtime hooks."""

import asyncio
import json
from collections.abc import AsyncGenerator, Sequence
from dataclasses import FrozenInstanceError, asdict, fields
from datetime import datetime
from typing import Any, cast

import pytest

from semantix_cache import (
    AsyncSemanticCache,
    CacheBusyError,
    CacheConfigurationError,
    CacheEntry,
    CacheMatch,
    CachePolicy,
    CacheResult,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    GenerationError,
    _coalescing,
    engine,
)
from semantix_cache._coalescing_metrics import Ledger
from semantix_cache.observability import CoalescingSnapshot

from .conftest import Adapter, SpyStore
from .test_coalescing import Generation, drained, pair, until

FIELD_NAMES = (
    "leaders_admitted",
    "followers_joined",
    "admissions_declined",
    "follower_hits",
    "follower_generated",
    "follower_errors",
    "follower_cancelled",
    "follower_timeouts",
    "follower_generations_started",
    "followers_pending",
    "wait_count",
    "wait_seconds",
    "active_flights",
    "retained_flights",
    "participants",
)


@pytest.fixture(autouse=True)
async def no_leaked_tasks() -> AsyncGenerator[None, None]:
    before = asyncio.all_tasks()
    yield
    await asyncio.sleep(0)
    assert not {
        t for t in asyncio.all_tasks() - before if t is not asyncio.current_task()
    }


@pytest.fixture
def cache(adapter: Adapter, store: SpyStore) -> AsyncSemanticCache:
    return AsyncSemanticCache(
        embedder=adapter, store=store, collect_coalescing_metrics=True
    )


def snapshot(cache: AsyncSemanticCache) -> CoalescingSnapshot:
    result = cache.coalescing_snapshot()
    assert result is not None
    assert result.followers_joined == (
        result.follower_hits
        + result.follower_generated
        + result.follower_errors
        + result.follower_cancelled
        + result.follower_timeouts
        + result.followers_pending
    )
    assert all(value >= 0 for value in asdict(result).values())
    return result


async def test_disabled_allocates_no_ledger(
    adapter: Adapter, store: SpyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden() -> Ledger:
        raise AssertionError("disabled collection allocated a ledger")

    monkeypatch.setattr(_coalescing, "Ledger", forbidden)
    cache = AsyncSemanticCache(embedder=adapter, store=store)
    generation = Generation()
    leader, follower = await pair(cache, generation)
    generation.finish.set()
    assert (await leader).provider_called
    assert (await follower).cache_hit
    assert cache.coalescing_snapshot() is None
    assert cache._flights._metrics is None
    drained(cache)
    await cache.aclose()


@pytest.mark.parametrize("value", [None, 0, 1, "true", []])
def test_collection_requires_bool(
    adapter: Adapter, store: SpyStore, value: object
) -> None:
    with pytest.raises(CacheConfigurationError):
        AsyncSemanticCache(
            embedder=adapter, store=store, collect_coalescing_metrics=cast(bool, value)
        )


async def test_zero_immutable_fixed_numeric_snapshot_and_lifetime(
    cache: AsyncSemanticCache, adapter: Adapter, store: SpyStore
) -> None:
    zero = snapshot(cache)
    assert tuple(field.name for field in fields(zero)) == FIELD_NAMES
    assert zero.__slots__ == FIELD_NAMES
    assert all(
        type(v) is (float if k == "wait_seconds" else int) and v == 0
        for k, v in asdict(zero).items()
    )
    assign = cast(Any, zero).__setattr__
    with pytest.raises(FrozenInstanceError):
        assign("participants", 10)
    generation = Generation()
    leader, follower = await pair(cache, generation)
    pending = snapshot(cache)
    assert (
        pending.leaders_admitted,
        pending.followers_joined,
        pending.followers_pending,
    ) == (1, 1, 1)
    assert (pending.active_flights, pending.retained_flights, pending.participants) == (
        1,
        1,
        2,
    )
    assert pending.wait_count == 0
    with pytest.raises(CacheBusyError):
        await cache.aclose()
    generation.finish.set()
    assert (await leader).provider_called
    assert (await follower).cache_hit
    final = snapshot(cache)
    assert final.follower_hits == final.wait_count == 1
    assert final.follower_generated == final.follower_generations_started == 0
    assert final.wait_seconds > 0
    drained(cache)
    await cache.aclose()
    assert snapshot(cache) == final
    assert asdict(zero) == dict.fromkeys(FIELD_NAMES, 0)
    fresh = AsyncSemanticCache(
        embedder=adapter, store=store, collect_coalescing_metrics=True
    )
    assert snapshot(fresh) == zero
    await fresh.aclose()


@pytest.mark.parametrize(
    "budget", ["_MAX_RECORDS", "_MAX_PARTICIPANTS", "_MAX_KEY_BYTES"]
)
async def test_decline_each_bound(
    cache: AsyncSemanticCache, monkeypatch: pytest.MonkeyPatch, budget: str
) -> None:
    monkeypatch.setattr(_coalescing, budget, 0)
    generation = Generation()
    generation.finish.set()
    result = await cache.resolve("question", generate=generation, coalescing_key="key")
    assert result.provider_called
    value = snapshot(cache)
    assert value.admissions_declined == generation.calls == 1
    assert value.leaders_admitted == value.followers_joined == value.wait_count == 0
    drained(cache)


@pytest.mark.parametrize("policy", list(CachePolicy))
@pytest.mark.parametrize("key", [None, "key"])
async def test_exclusions(
    cache: AsyncSemanticCache, policy: CachePolicy, key: str | None
) -> None:
    generation = Generation()
    generation.finish.set()
    if policy is CachePolicy.NORMAL and key is not None:
        await cache.set("question", "warm")
    await cache.resolve(
        "question", generate=generation, policy=policy, coalescing_key=key
    )
    assert snapshot(cache).leaders_admitted == snapshot(cache).followers_joined == 0
    for kwargs in ({"coalescing_key": ""}, {"cache_ttl_seconds": -1}, {"prompt": ""}):
        with pytest.raises(CacheValidationError):
            await cache.resolve(
                generate=generation, **({"prompt": "question"} | kwargs)
            )
    assert snapshot(cache).admissions_declined == 0


@pytest.mark.parametrize(
    ("error", "field"),
    [
        (RuntimeError("synthetic private error"), "follower_errors"),
        (TimeoutError("callback timeout"), "follower_errors"),
        (CacheTimeoutError("cache deadline"), "follower_timeouts"),
        (asyncio.CancelledError(), "follower_cancelled"),
    ],
)
async def test_shared_error_classification_no_retry(
    cache: AsyncSemanticCache, error: BaseException, field: str
) -> None:
    generation = Generation(error=error)
    leader, follower = await pair(cache, generation)
    generation.finish.set()
    outcomes = await asyncio.gather(leader, follower, return_exceptions=True)
    assert all(type(value) is type(error) for value in outcomes)
    value = snapshot(cache)
    assert getattr(value, field) == value.followers_joined == value.wait_count == 1
    assert value.follower_generations_started == 0
    assert generation.calls == 1
    drained(cache)


@pytest.mark.parametrize("leader_cancel", [False, True])
async def test_cancel_once_and_aborted_wait(
    cache: AsyncSemanticCache, leader_cancel: bool
) -> None:
    generation = Generation()
    leader, follower = await pair(cache, generation)
    target = leader if leader_cancel else follower
    target.cancel()
    target.cancel()
    if leader_cancel:
        assert all(
            isinstance(value, asyncio.CancelledError)
            for value in await asyncio.gather(leader, follower, return_exceptions=True)
        )
    else:
        with pytest.raises(asyncio.CancelledError):
            await follower
        generation.finish.set()
        assert (await leader).provider_called
    assert snapshot(cache).follower_cancelled == snapshot(cache).wait_count == 1
    assert snapshot(cache).wait_seconds > 0
    drained(cache)


async def test_real_shared_deadline(adapter: Adapter, store: SpyStore) -> None:
    cache = AsyncSemanticCache(
        embedder=adapter,
        store=store,
        operation_timeout_seconds=0.05,
        collect_coalescing_metrics=True,
    )
    generation = Generation()
    leader, follower = await pair(cache, generation)
    assert all(
        isinstance(value, CacheTimeoutError)
        for value in await asyncio.gather(leader, follower, return_exceptions=True)
    )
    assert snapshot(cache).follower_timeouts == snapshot(cache).wait_count == 1
    assert generation.calls == 1
    drained(cache)


@pytest.mark.parametrize(
    "failure",
    [
        "none",
        "output",
        "before-write",
        "after-write",
        "result",
        "provider",
        "cancel",
        "timeout",
    ],
)
async def test_follower_generation_phase_and_terminal(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await follower_generation_case(failure, monkeypatch)


async def follower_generation_case(
    failure: str, monkeypatch: pytest.MonkeyPatch, *, metrics_available: bool = True
) -> None:
    adapter = Adapter()
    generation = Generation()
    leader_task: asyncio.Task[Any] | None = None

    class ChurningStore(SpyStore):
        async def find_nearest(
            self, embedding: Sequence[float], *, namespace: str
        ) -> CacheMatch | None:
            if leader_task is not None and leader_task.done():
                await self.clear(namespace=namespace)
            return await super().find_nearest(embedding, namespace=namespace)

        async def put(
            self, entry: CacheEntry, *, ttl_seconds: float | None = None
        ) -> None:
            follower = leader_task is not None and leader_task.done()
            if follower and failure == "before-write":
                raise CacheStoreError("synthetic write failure")
            await super().put(entry, ttl_seconds=ttl_seconds)
            if follower and failure == "after-write":
                raise CacheStoreError("synthetic write failure")

    store = ChurningStore(adapter.embedding_space)
    cache = AsyncSemanticCache(
        embedder=adapter, store=store, collect_coalescing_metrics=True
    )
    leader_task, follower = await pair(cache, generation)
    generation.finish.set()
    assert (await leader_task).provider_called
    if failure == "output":
        generation.output = ""
    elif failure == "provider":
        generation.error = RuntimeError("synthetic follower provider failure")
    elif failure == "cancel":
        generation.error = asyncio.CancelledError()
    elif failure == "timeout":
        generation.error = CacheTimeoutError("synthetic follower deadline")
    elif failure == "result":

        def broken(**kwargs: Any) -> Any:
            raise RuntimeError("synthetic result failure")

        monkeypatch.setattr(engine, "CacheResult", broken)
    if failure == "none":
        assert (await follower).provider_called
    else:
        expected = {
            "output": GenerationError,
            "result": RuntimeError,
            "provider": RuntimeError,
            "cancel": asyncio.CancelledError,
            "timeout": CacheTimeoutError,
        }.get(failure, CacheStoreError)
        with pytest.raises(expected):
            await follower
    assert generation.calls == 2
    if metrics_available:
        value = snapshot(cache)
        assert value.follower_generations_started == value.wait_count == 1
        assert value.follower_generated == (failure == "none")
        assert value.follower_errors == (failure not in {"none", "cancel", "timeout"})
        assert value.follower_cancelled == (failure == "cancel")
        assert value.follower_timeouts == (failure == "timeout")
    else:
        assert cache.coalescing_snapshot() is None
    drained(cache)
    await store.aclose()


async def test_wait_clock_excludes_recheck(
    cache: AsyncSemanticCache, store: SpyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    times = iter([5.0, 8.0])
    monkeypatch.setattr(_coalescing, "perf_counter", lambda: next(times))
    generation = Generation()
    leader, follower = await pair(cache, generation)
    original = store.record_hit
    entered, finish = asyncio.Event(), asyncio.Event()

    async def confirm(
        cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        entered.set()
        await finish.wait()
        return await original(
            cache_key, namespace=namespace, expected_created_at=expected_created_at
        )

    monkeypatch.setattr(store, "record_hit", confirm)
    generation.finish.set()
    await leader
    await entered.wait()
    value = snapshot(cache)
    assert value.wait_count == 1
    assert value.wait_seconds == pytest.approx(3.0)
    assert (
        value.active_flights,
        value.retained_flights,
        value.participants,
        value.followers_pending,
    ) == (0, 1, 1, 1)
    with pytest.raises(CacheBusyError):
        await cache.aclose()
    finish.set()
    assert (await follower).cache_hit
    assert snapshot(cache).wait_seconds == pytest.approx(3.0)
    drained(cache)


async def test_snapshot_constructed_outside_guard(
    cache: AsyncSemanticCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = CoalescingSnapshot

    def construct(*args: Any) -> CoalescingSnapshot:
        assert not cache._flights._guard.locked()
        return original(*args)

    monkeypatch.setattr(_coalescing, "CoalescingSnapshot", construct)
    snapshot(cache)


@pytest.mark.parametrize(
    "stage",
    [
        "leaders_admitted",
        "followers_joined",
        "follower_hits",
        "wait",
        "clock-start",
        "clock-end",
        "copy",
        "model",
    ],
)
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_bookkeeping_failure_isolation(
    cache: AsyncSemanticCache, monkeypatch: pytest.MonkeyPatch, stage: str, outcome: str
) -> None:
    original_increment = Ledger.increment

    def increment(self: Ledger, counter: Any) -> None:
        if counter == stage:
            raise ArithmeticError("synthetic ledger failure")
        original_increment(self, counter)

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise ArithmeticError("synthetic ledger failure")

    monkeypatch.setattr(Ledger, "increment", increment)
    if stage == "wait":
        monkeypatch.setattr(Ledger, "waited", broken)
    if stage == "clock-start":
        monkeypatch.setattr(_coalescing, "perf_counter", broken)
    error = (
        RuntimeError("synthetic original provider failure")
        if outcome == "error"
        else None
    )
    generation = Generation(error=error)
    leader, follower = await pair(cache, generation)
    if stage == "clock-end":
        monkeypatch.setattr(_coalescing, "perf_counter", broken)
    elif stage == "copy":
        monkeypatch.setattr(Ledger, "copy", broken)
        assert cache.coalescing_snapshot() is None
    elif stage == "model":
        monkeypatch.setattr(_coalescing, "CoalescingSnapshot", broken)
        assert cache.coalescing_snapshot() is None
    if outcome == "cancel":
        leader.cancel()
    else:
        generation.finish.set()
    outcomes = await asyncio.gather(leader, follower, return_exceptions=True)
    if outcome == "success":
        assert isinstance(outcomes[0], CacheResult)
        assert isinstance(outcomes[1], CacheResult)
        assert outcomes[0].provider_called
        assert outcomes[1].cache_hit
    elif outcome == "error":
        assert all(value is error for value in outcomes)
    else:
        assert all(isinstance(value, asyncio.CancelledError) for value in outcomes)
    # The hit-counter fault is deliberately unreachable on non-hit outcomes.
    if stage != "follower_hits" or outcome == "success":
        assert cache.coalescing_snapshot() is None
    assert generation.calls == 1
    drained(cache)


async def test_generation_counter_failure_preserves_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Ledger.increment

    def broken(self: Ledger, counter: Any) -> None:
        if counter == "follower_generations_started":
            raise ArithmeticError("synthetic ledger failure")
        original(self, counter)

    monkeypatch.setattr(Ledger, "increment", broken)
    await follower_generation_case("none", monkeypatch, metrics_available=False)


async def test_concurrent_snapshot_privacy_and_constant_state(
    cache: AsyncSemanticCache,
) -> None:
    payload_marker = "synthetic payload namespace key model provider error"
    generation = Generation(error=RuntimeError(payload_marker), output=payload_marker)
    leader = asyncio.create_task(
        cache.resolve(
            payload_marker,
            namespace="synthetic-private-namespace",
            coalescing_key=payload_marker,
            generate=generation,
        )
    )
    await generation.started.wait()
    followers = [
        asyncio.create_task(
            cache.resolve(
                payload_marker,
                namespace="synthetic-private-namespace",
                coalescing_key=payload_marker,
                generate=generation,
            )
        )
        for _ in range(20)
    ]
    await until(lambda: cache._flights.counts()[2] == 21)

    def read() -> None:
        for _ in range(500):
            value = snapshot(cache)
            encoded = json.dumps(asdict(value))
            assert payload_marker not in encoded
            assert payload_marker not in repr(value)
            assert tuple(asdict(value)) == FIELD_NAMES
            assert all(type(v) in (int, float) for v in asdict(value).values())

    readers = [asyncio.create_task(asyncio.to_thread(read)) for _ in range(3)]
    generation.finish.set()
    assert all(
        isinstance(value, RuntimeError)
        for value in await asyncio.gather(leader, *followers, return_exceptions=True)
    )
    await asyncio.gather(*readers)
    assert snapshot(cache).follower_errors == snapshot(cache).wait_count == 20
    ledger = cache._flights._metrics
    assert ledger is not None
    assert not hasattr(ledger, "__dict__")
    assert len(fields(ledger)) == 11
    assert all(type(v) in (int, float) for v in asdict(ledger).values())
    drained(cache)


async def test_ledger_allocation_failure_is_unavailable(
    adapter: Adapter, store: SpyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> Ledger:
        raise ArithmeticError("synthetic allocation failure")

    monkeypatch.setattr(_coalescing, "Ledger", broken)
    cache = AsyncSemanticCache(
        embedder=adapter, store=store, collect_coalescing_metrics=True
    )
    generation = Generation()
    leader, follower = await pair(cache, generation)
    generation.finish.set()
    assert (await leader).provider_called
    assert (await follower).cache_hit
    assert cache.coalescing_snapshot() is None
    drained(cache)
