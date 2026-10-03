import asyncio

import pytest

from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.observability.metrics import RuntimeMetrics
from tests.cache.infrastructure.backends.support import cache_entry


def test_runtime_metrics_record_counters_latency_and_gauges() -> None:
    metrics = RuntimeMetrics()

    metrics.record_request_started()
    metrics.record_request_completed(10.0, failed=False)
    metrics.record_request_started()
    metrics.record_request_completed(30.0, failed=True)
    metrics.record_cache_hit()
    metrics.record_cache_miss()
    metrics.record_provider_call()
    metrics.record_coalesced_delta(1)
    metrics.record_evictions(2)
    metrics.record_expirations(3)

    snapshot = metrics.snapshot(cache_size=4)

    assert snapshot.request_count == 2
    assert snapshot.error_count == 1
    assert snapshot.cache_hits == 1
    assert snapshot.cache_misses == 1
    assert snapshot.provider_calls == 1
    assert snapshot.in_flight_coalesced_requests == 1
    assert snapshot.average_latency_ms == pytest.approx(20.0)
    assert snapshot.p95_latency_ms == pytest.approx(30.0)
    assert snapshot.latency_sample_size == 2
    assert snapshot.cache_size == 4
    assert snapshot.evictions == 2
    assert snapshot.expirations == 3
    assert snapshot.observed_at.utcoffset() is not None
    assert snapshot.uptime_seconds >= 0

    metrics.record_coalesced_delta(-1)
    assert metrics.snapshot(cache_size=4).in_flight_coalesced_requests == 0


def test_empty_metrics_preserve_missing_latency() -> None:
    snapshot = RuntimeMetrics().snapshot(cache_size=0)

    assert snapshot.average_latency_ms is None
    assert snapshot.p95_latency_ms is None
    assert snapshot.latency_sample_size == 0


@pytest.mark.asyncio
async def test_memory_backend_records_evictions_and_expirations() -> None:
    metrics = RuntimeMetrics()
    backend = InMemoryCacheBackend(
        1,
        0.01,
        dimensions=4,
        events=metrics,
    )
    first = cache_entry("first", "first response", vector_index=0)
    second = cache_entry("second", "second response", vector_index=1)

    await backend.put(first)
    await backend.put(second)
    assert metrics.snapshot(cache_size=1).evictions == 1

    await asyncio.sleep(0.02)
    stats = await backend.stats(None)
    snapshot = metrics.snapshot(cache_size=stats.size)

    assert snapshot.cache_size == 0
    assert snapshot.expirations == 1
