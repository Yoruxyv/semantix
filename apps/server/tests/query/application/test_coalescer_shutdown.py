import asyncio

import pytest

from app.core.exceptions import QueryShuttingDownError
from app.query.application.coalescing import RequestCoalescer


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", ["leader", "follower", "all"])
async def test_caller_cancellation_still_shields_shared_work(cancel: str) -> None:
    started, joined, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    coalescer: RequestCoalescer[str] = RequestCoalescer(
        lambda delta: joined.set() if delta == 1 else None
    )
    shared: asyncio.Task[object] | None = None
    calls = 0

    async def operation() -> str:
        nonlocal shared, calls
        shared = asyncio.current_task()
        calls += 1
        started.set()
        await release.wait()
        return "shared"

    leader = asyncio.create_task(coalescer.run("same", operation))
    await started.wait()
    follower = asyncio.create_task(coalescer.run("same", operation))
    await joined.wait()
    cancelled = (
        [leader, follower]
        if cancel == "all"
        else [leader if cancel == "leader" else follower]
    )
    for task in cancelled:
        task.cancel()
    outcomes = await asyncio.gather(*cancelled, return_exceptions=True)
    assert all(isinstance(outcome, asyncio.CancelledError) for outcome in outcomes)
    assert shared is not None
    assert not shared.done()
    assert shared.cancelling() == 0
    release.set()
    results = await asyncio.gather(leader, follower, return_exceptions=True)
    if cancel == "follower":
        assert not isinstance(results[0], BaseException)
        assert results[0].is_leader
    if cancel == "leader":
        assert not isinstance(results[1], BaseException)
        assert not results[1].is_leader
    await coalescer.aclose(grace_seconds=1)
    assert calls == 1
    assert not coalescer._in_flight
    assert not coalescer._cleanup_tasks


@pytest.mark.asyncio
async def test_seal_rejects_registration_already_waiting_for_lock() -> None:
    coalescer: RequestCoalescer[str] = RequestCoalescer()
    waiting, closing = asyncio.Event(), asyncio.Event()

    async def forbidden() -> str:
        pytest.fail("Unadmitted operation must never be invoked")

    async def request() -> None:
        waiting.set()
        await coalescer.run("queued", forbidden)

    async def close() -> None:
        closing.set()
        await coalescer.aclose(grace_seconds=0)

    await coalescer._lock.acquire()
    caller = asyncio.create_task(request())
    await waiting.wait()
    shutdown = asyncio.create_task(close())
    await closing.wait()
    coalescer._lock.release()
    with pytest.raises(QueryShuttingDownError):
        await caller
    await shutdown
    assert not coalescer._in_flight


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_cleanup", [False, True])
async def test_shutdown_joins_async_cleanup_and_preserves_its_failure(
    monkeypatch: pytest.MonkeyPatch,
    cancel_cleanup: bool,
) -> None:
    coalescer: RequestCoalescer[str] = RequestCoalescer()
    started, release = asyncio.Event(), asyncio.Event()
    cleaning, finish_cleanup = asyncio.Event(), asyncio.Event()
    remove = coalescer._remove
    error = (
        asyncio.CancelledError()
        if cancel_cleanup
        else RuntimeError("fixture cleanup failure")
    )

    async def operation() -> str:
        started.set()
        await release.wait()
        return "shared"

    async def failed_cleanup(key: str, completed: asyncio.Future[str]) -> None:
        cleaning.set()
        await finish_cleanup.wait()
        await remove(key, completed)
        raise error

    monkeypatch.setattr(coalescer, "_remove", failed_cleanup)
    caller = asyncio.create_task(coalescer.run("same", operation))
    await started.wait()
    caller.cancel()
    await asyncio.gather(caller, return_exceptions=True)
    shutdown = asyncio.create_task(coalescer.aclose(grace_seconds=5))
    release.set()
    await cleaning.wait()
    assert not shutdown.done()
    finish_cleanup.set()
    with pytest.raises(
        BaseExceptionGroup, match="Shared query shutdown failed"
    ) as caught:
        await shutdown
    if cancel_cleanup:
        assert len(caught.value.exceptions) == 1
        assert isinstance(caught.value.exceptions[0], asyncio.CancelledError)
    else:
        assert caught.value.exceptions == (error,)
    assert not coalescer._cleanup_tasks
    assert not coalescer._in_flight
    with pytest.raises(BaseExceptionGroup):
        await coalescer.aclose(grace_seconds=0)


@pytest.mark.asyncio
async def test_concurrent_closes_cancel_then_join_the_same_operation() -> None:
    coalescer: RequestCoalescer[str] = RequestCoalescer()
    started, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cancellations = 0

    async def operation() -> str:
        nonlocal cancellations
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancellations += 1
            cancelled.set()
            await release.wait()
        return "settled"

    caller = asyncio.create_task(coalescer.run("same", operation))
    await started.wait()
    first = asyncio.create_task(coalescer.aclose(grace_seconds=0))
    await cancelled.wait()
    second = asyncio.create_task(coalescer.aclose(grace_seconds=5))
    first.cancel()
    rejected = asyncio.create_task(coalescer.run("other", operation))
    with pytest.raises(QueryShuttingDownError):
        await rejected
    assert not first.done()
    assert not second.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert (await caller).value == "settled"
    assert cancellations == 1
    assert not coalescer._in_flight
    assert not coalescer._cleanup_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("grace", [-1.0, float("nan"), float("inf")])
async def test_invalid_grace_does_not_seal_admission(grace: float) -> None:
    coalescer: RequestCoalescer[str] = RequestCoalescer()
    with pytest.raises(ValueError, match="finite and nonnegative"):
        await coalescer.aclose(grace_seconds=grace)

    async def operation() -> str:
        return "still open"

    assert (await coalescer.run("same", operation)).value == "still open"
    await coalescer.aclose(grace_seconds=0)
