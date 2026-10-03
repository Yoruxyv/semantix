import asyncio

import pytest

from app.observability.metrics import RuntimeMetrics
from app.query.application.coalescing import RequestCoalescer


@pytest.mark.asyncio
async def test_coalesced_waiter_gauge_tracks_only_active_followers() -> None:
    metrics = RuntimeMetrics()
    coalescer: RequestCoalescer[str] = RequestCoalescer(metrics.record_coalesced_delta)
    started = asyncio.Event()
    release = asyncio.Event()

    async def operation() -> str:
        started.set()
        await release.wait()
        return "shared"

    leader = asyncio.create_task(coalescer.run("same", operation))
    await asyncio.wait_for(started.wait(), timeout=1)
    follower = asyncio.create_task(coalescer.run("same", operation))
    await asyncio.sleep(0)

    assert metrics.snapshot(cache_size=0).in_flight_coalesced_requests == 1

    release.set()
    results = await asyncio.gather(leader, follower)

    assert [result.value for result in results] == ["shared", "shared"]
    assert results[0].is_leader is True
    assert results[1].is_leader is False
    assert metrics.snapshot(cache_size=0).in_flight_coalesced_requests == 0
