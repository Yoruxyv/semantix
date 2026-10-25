"""Barriers protect bounded scheduling ownership and live revision confirmation."""

import asyncio
import gc
import threading
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from contextvars import ContextVar
from datetime import datetime
from typing import cast

import numpy as np
import pytest
from numpy.typing import ArrayLike, DTypeLike, NDArray

from semantix_cache import (
    AsyncSemanticCache,
    CacheBusyError,
    CacheClosedError,
    CacheMatch,
    MemoryStore,
    memory,
)

from .conftest import Adapter
from .test_memory import entry


async def test_cold_readers_publish_once_and_keep_one_use_policy(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space)
    await store.put(entry("oldest"))
    await store.put(entry("other"))
    loop = asyncio.get_running_loop()
    started, release = asyncio.Event(), threading.Event()
    original = np.asarray
    builds = 0
    active = 0
    peak = 0
    guard = threading.Lock()

    def traced(
        values: ArrayLike, dtype: DTypeLike | None = None
    ) -> NDArray[np.float64]:
        nonlocal builds, active, peak
        is_matrix = (
            isinstance(values, list) and bool(values) and isinstance(values[0], tuple)
        )
        if not is_matrix:
            return cast(NDArray[np.float64], original(values, dtype=dtype))
        with guard:
            builds += 1
            active += 1
            peak = max(peak, active)
            first = builds == 1
        try:
            if first:
                loop.call_soon_threadsafe(started.set)
                if not release.wait(5):
                    raise RuntimeError("Cold preparation gate was not released")
            return cast(NDArray[np.float64], original(values, dtype=dtype))
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(np, "asarray", traced)
    tasks = [
        asyncio.create_task(store.find_nearest((1.0, 0.0), namespace="default"))
        for _ in range(12)
    ]
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(CacheBusyError):
            await store.aclose()
    finally:
        release.set()
    matches = await asyncio.gather(*tasks)
    assert all(
        match is not None and match.entry.prompt == "oldest" for match in matches
    )
    # One worker-local first-use build, then exactly one retained publication.
    assert builds == 2
    assert peak == 1
    snapshot = store._snapshots["default"]
    assert snapshot.matrix is not None
    assert not snapshot.matrix.flags.writeable
    assert snapshot.norms is not None
    assert not snapshot.norms.flags.writeable
    assert await store.find_nearest((1.0, 0.0), namespace="default") == matches[0]
    assert builds == 2
    await store.aclose()


async def test_cancelled_searches_keep_worker_and_buffer_ownership(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space)
    await store.put(entry("original"))
    for _ in range(2):
        await store.find_nearest((1.0, 0.0), namespace="default")
    retired = store._snapshots["default"]
    capacity = store._slot._value
    loop = asyncio.get_running_loop()
    started, release = asyncio.Event(), threading.Event()
    original = memory._nearest
    active = 0
    peak = 0

    def blocked(query: NDArray[np.float64], snapshot: memory._Snapshot) -> CacheMatch:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(5):
                raise RuntimeError("Worker ownership gate was not released")
            return original(query, snapshot)
        finally:
            active -= 1

    monkeypatch.setattr(memory, "_nearest", blocked)
    tasks = [
        asyncio.create_task(store.find_nearest((1.0, 0.0), namespace="default"))
        for _ in range(capacity)
    ]
    try:
        await asyncio.wait_for(started.wait(), 2)
        for task in tasks:
            task.cancel()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in outcomes)
        assert store._slot._value == 0
        assert len(store._workers) == 1
        with pytest.raises(CacheBusyError):
            await store.aclose()
        for index in range(20):
            await store.put(entry("original", vector=(0.0, 1.0)))
            await store.put(entry(str(index), namespace="foreign"))
        assert retired.matrix is not None
        np.testing.assert_array_equal(retired.matrix, [[1.0, 0.0]])
        assert not retired.matrix.flags.writeable
        queued = asyncio.Event()
        acquire = store._slot.acquire

        async def acquiring() -> bool:
            queued.set()
            return await acquire()

        monkeypatch.setattr(store._slot, "acquire", acquiring)
        waiting = asyncio.create_task(
            store.find_nearest((1.0, 0.0), namespace="default")
        )
        await asyncio.wait_for(queued.wait(), 2)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert store._slot._value == 0
    finally:
        release.set()
    await asyncio.gather(*store._workers)
    await asyncio.sleep(0)  # Drain completion callbacks, independent of elapsed time.
    assert not store._workers
    assert store._slot._value == capacity
    assert peak == 1
    match = await store.find_nearest((1.0, 0.0), namespace="default")
    assert match is not None
    assert match.similarity_score == 0
    assert len(store._snapshots) == 1
    await store.aclose()
    assert not store._snapshots
    with pytest.raises(CacheClosedError):
        await store.find_nearest((1.0, 0.0), namespace="default")


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_one_failed_search_does_not_abort_waiting_readers(
    failure: type[BaseException], adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with MemoryStore(embedding_space=adapter.embedding_space) as store:
        await store.put(entry("seed"))
        capacity = store._slot._value
        original = memory._nearest
        calls = 0

        def failing(
            query: NDArray[np.float64], snapshot: memory._Snapshot
        ) -> CacheMatch:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise failure("Controlled worker failure")
            return original(query, snapshot)

        monkeypatch.setattr(memory, "_nearest", failing)
        results = await asyncio.gather(
            *(
                store.find_nearest((1.0, 0.0), namespace="default")
                for _ in range(capacity * 4)
            ),
            return_exceptions=True,
        )
        assert isinstance(results[0], failure)
        assert all(isinstance(result, CacheMatch) for result in results[1:])
        assert not store._workers
        assert store._slot._value == capacity
        assert await store.find_nearest((1.0, 0.0), namespace="default") is not None


@pytest.mark.parametrize("submission", ["raise", "cancel"])
async def test_submission_failure_releases_every_admission(
    submission: str, adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with MemoryStore(embedding_space=adapter.embedding_space) as store:
        await store.put(entry("seed"))
        capacity = store._slot._value
        loop = asyncio.get_running_loop()
        original = loop.run_in_executor

        def unavailable(*args: object, **kwargs: object) -> asyncio.Future[object]:
            if submission == "cancel":
                result: asyncio.Future[object] = loop.create_future()
                result.cancel()
                return result
            raise RuntimeError("Controlled executor failure")

        monkeypatch.setattr(loop, "run_in_executor", unavailable)
        results = await asyncio.gather(
            *(
                store.find_nearest((1.0, 0.0), namespace="default")
                for _ in range(capacity)
            ),
            return_exceptions=True,
        )
        failure = RuntimeError if submission == "raise" else asyncio.CancelledError
        assert all(isinstance(result, failure) for result in results)
        assert not store._workers
        assert store._slot._value == capacity
        monkeypatch.setattr(loop, "run_in_executor", original)
        assert await store.find_nearest((1.0, 0.0), namespace="default") is not None


@pytest.mark.parametrize(
    "mutation", ["replace", "delete", "clear", "expire", "foreign"]
)
async def test_scheduled_candidate_rechecks_live_revision(
    mutation: str, adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 100.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    store = MemoryStore(
        embedding_space=adapter.embedding_space, default_ttl_seconds=1.0
    )
    value = entry("seed")
    await store.put(value)
    original = memory._nearest
    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def blocked(query: NDArray[np.float64], snapshot: memory._Snapshot) -> CacheMatch:
        result = original(query, snapshot)
        loop.call_soon_threadsafe(started.set)
        if not release.wait(5):
            raise RuntimeError("Revision gate was not released")
        return result

    monkeypatch.setattr(memory, "_nearest", blocked)
    task = asyncio.create_task(store.find_nearest((1.0, 0.0), namespace="default"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        if mutation == "replace":
            await store.put(value.model_copy(update={"embedding": (0.0, 1.0)}))
        elif mutation == "delete":
            await store.delete_entry(value.cache_key, namespace="default")
        elif mutation == "clear":
            await store.clear(namespace="default")
        elif mutation == "expire":
            now += 1.0
        else:
            await store.put(entry("other", namespace="foreign"))
    finally:
        release.set()
    result = await task
    if mutation == "foreign":
        assert result is not None
        assert result.entry.namespace == "default"
    else:
        assert result is None
        assert not await store.record_hit(
            value.cache_key, namespace="default", expected_created_at=value.created_at
        )
    if mutation == "expire":
        assert store.inspection_events == (0, 1)
    await store.aclose()


async def test_expiry_between_candidate_and_atomic_confirmation(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 100.0
    monkeypatch.setattr(memory, "monotonic", lambda: now)
    async with MemoryStore(
        embedding_space=adapter.embedding_space, default_ttl_seconds=1.0
    ) as store:
        await store.put(entry("seed"))
        entered, release = asyncio.Event(), asyncio.Event()
        original = store.record_hit

        async def confirm(
            cache_key: str, *, namespace: str, expected_created_at: datetime
        ) -> bool:
            entered.set()
            await release.wait()
            return await original(
                cache_key, namespace=namespace, expected_created_at=expected_created_at
            )

        monkeypatch.setattr(store, "record_hit", confirm)
        async with AsyncSemanticCache(embedder=adapter, store=store) as cache:
            task = asyncio.create_task(cache.get("query"))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                now += 1.0
            finally:
                release.set()
            assert await task is None
        assert store.inspection_events == (0, 1)


async def test_each_search_preserves_its_own_context(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    label: ContextVar[int] = ContextVar("reader-label", default=-1)
    seen: list[int] = []
    original = memory._nearest

    def traced(query: NDArray[np.float64], snapshot: memory._Snapshot) -> CacheMatch:
        seen.append(label.get())
        return original(query, snapshot)

    monkeypatch.setattr(memory, "_nearest", traced)
    async with MemoryStore(embedding_space=adapter.embedding_space) as store:
        await store.put(entry("seed"))

        async def search(index: int) -> CacheMatch | None:
            token = label.set(index)
            try:
                return await store.find_nearest((1.0, 0.0), namespace="default")
            finally:
                label.reset(token)

        assert all(await asyncio.gather(*(search(index) for index in range(12))))
        assert sorted(seen) == list(range(12))


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_worker_error_after_caller_cancellation_is_consumed(
    failure: type[BaseException], adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = asyncio.get_running_loop()
    old_handler = loop.get_exception_handler()
    unhandled: list[dict[str, object]] = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    store = MemoryStore(embedding_space=adapter.embedding_space)
    await store.put(entry("seed"))
    started, drained, release = asyncio.Event(), asyncio.Event(), threading.Event()
    original = memory._nearest

    def failing(query: NDArray[np.float64], snapshot: memory._Snapshot) -> CacheMatch:
        loop.call_soon_threadsafe(started.set)
        if not release.wait(5):
            raise RuntimeError("Cancelled worker gate was not released")
        raise failure("Controlled detached worker failure")

    monkeypatch.setattr(memory, "_nearest", failing)
    task = asyncio.create_task(store.find_nearest((1.0, 0.0), namespace="default"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(CacheBusyError):
            await store.aclose()
        worker = next(iter(store._workers))
        worker.add_done_callback(lambda _worker: drained.set())
        release.set()
        await asyncio.wait_for(drained.wait(), 2)
        assert not store._workers
        assert store._slot._value == 1
        # Do not await the worker: production must retrieve its abandoned error.
        del worker, task
        gc.collect()
        assert not unhandled
        monkeypatch.setattr(memory, "_nearest", original)
        assert await store.find_nearest((1.0, 0.0), namespace="default") is not None
    finally:
        release.set()
        loop.set_exception_handler(old_handler)
    await store.aclose()


async def test_cancelled_executor_queue_keeps_admission_until_work_drains(
    adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = asyncio.get_running_loop()
    occupied, submitted, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release, ran = threading.Event(), threading.Event()
    original_executor = loop.run_in_executor
    original_nearest = memory._nearest
    store = MemoryStore(embedding_space=adapter.embedding_space)
    await store.put(entry("seed"))

    def occupying() -> None:
        loop.call_soon_threadsafe(occupied.set)
        if not release.wait(5):
            raise RuntimeError("Executor gate was not released")

    def nearest(query: NDArray[np.float64], snapshot: memory._Snapshot) -> CacheMatch:
        ran.set()
        return original_nearest(query, snapshot)

    with ThreadPoolExecutor(max_workers=1) as pool:
        blocker = pool.submit(occupying)
        try:
            await asyncio.wait_for(occupied.wait(), 2)

            def queued(
                executor: Executor | None,
                function: Callable[..., object],
                *args: object,
            ) -> asyncio.Future[object]:
                result = original_executor(pool, function, *args)
                submitted.set()
                return result

            monkeypatch.setattr(loop, "run_in_executor", queued)
            monkeypatch.setattr(memory, "_nearest", nearest)
            task = asyncio.create_task(
                store.find_nearest((1.0, 0.0), namespace="default")
            )
            await asyncio.wait_for(submitted.wait(), 2)
            assert not ran.is_set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(CacheBusyError):
                await store.aclose()
            assert len(store._workers) == 1
            assert store._slot._value == 0
            next(iter(store._workers)).add_done_callback(lambda _worker: drained.set())
            release.set()
            await asyncio.wait_for(drained.wait(), 2)
            assert ran.is_set()
            assert not store._workers
            assert store._slot._value == 1
        finally:
            release.set()
            monkeypatch.setattr(loop, "run_in_executor", original_executor)
        blocker.result(timeout=2)
    await store.aclose()


@pytest.mark.parametrize("completion", ["result", "error", "cancel"])
async def test_already_finished_worker_cleans_up_before_caller_returns(
    completion: str, adapter: Adapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space)
    await store.put(entry("seed"))
    match = await store.find_nearest((1.0, 0.0), namespace="default")
    assert match is not None
    loop = asyncio.get_running_loop()
    worker: asyncio.Future[CacheMatch] = loop.create_future()
    if completion == "result":
        worker.set_result(match)
    elif completion == "error":
        worker.set_exception(RuntimeError("Controlled already-finished failure"))
    else:
        worker.cancel()

    def finished(*args: object, **kwargs: object) -> asyncio.Future[CacheMatch]:
        return worker

    monkeypatch.setattr(loop, "run_in_executor", finished)
    if completion == "result":
        assert await store.find_nearest((1.0, 0.0), namespace="default") == match
    else:
        error = RuntimeError if completion == "error" else asyncio.CancelledError
        with pytest.raises(error):
            await store.find_nearest((1.0, 0.0), namespace="default")
    assert not store._workers
    assert store._slot._value == 1
    await store.aclose()
