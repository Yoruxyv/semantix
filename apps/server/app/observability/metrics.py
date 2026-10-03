import math
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic

MAX_LATENCY_SAMPLES = 2_048


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    observed_at: datetime
    uptime_seconds: float
    request_count: int
    error_count: int
    cache_hits: int
    cache_misses: int
    provider_calls: int
    in_flight_coalesced_requests: int
    average_latency_ms: float | None
    p95_latency_ms: float | None
    latency_sample_size: int
    cache_size: int
    evictions: int
    expirations: int


class RuntimeMetrics:
    """Bounded process-local metrics for the interactive query path."""

    def __init__(self) -> None:
        self._started_at = monotonic()
        self._request_count = 0
        self._completed_request_count = 0
        self._error_count = 0
        self._cache_hits = 0
        self._cache_misses = 0
        self._provider_calls = 0
        self._in_flight_coalesced_requests = 0
        self._latency_total_ms = 0.0
        self._latencies_ms: deque[float] = deque(maxlen=MAX_LATENCY_SAMPLES)
        self._evictions = 0
        self._expirations = 0
        self._lock = Lock()

    def record_request_started(self) -> None:
        with self._lock:
            self._request_count += 1

    def record_request_completed(
        self,
        latency_ms: float,
        *,
        failed: bool,
    ) -> None:
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("latency_ms must be finite and non-negative")
        with self._lock:
            self._completed_request_count += 1
            if failed:
                self._error_count += 1
            self._latency_total_ms += latency_ms
            self._latencies_ms.append(latency_ms)

    def record_cache_hit(self) -> None:
        with self._lock:
            self._cache_hits += 1

    def record_cache_miss(self) -> None:
        with self._lock:
            self._cache_misses += 1

    def record_provider_call(self) -> None:
        with self._lock:
            self._provider_calls += 1

    def record_coalesced_delta(self, delta: int) -> None:
        if delta not in {-1, 1}:
            raise ValueError("Coalesced request delta must be -1 or 1")
        with self._lock:
            next_value = self._in_flight_coalesced_requests + delta
            if next_value < 0:
                raise RuntimeError("Coalesced request count cannot be negative")
            self._in_flight_coalesced_requests = next_value

    def record_evictions(self, count: int) -> None:
        self._record_cache_removals(count, expired=False)

    def record_expirations(self, count: int) -> None:
        self._record_cache_removals(count, expired=True)

    def snapshot(self, *, cache_size: int) -> MetricsSnapshot:
        if cache_size < 0:
            raise ValueError("cache_size must be non-negative")
        with self._lock:
            latencies = sorted(self._latencies_ms)
            sample_size = len(latencies)
            average_latency_ms = (
                None
                if self._completed_request_count == 0
                else self._latency_total_ms / self._completed_request_count
            )
            p95_latency_ms = (
                None
                if sample_size == 0
                else latencies[math.ceil(sample_size * 0.95) - 1]
            )
            return MetricsSnapshot(
                observed_at=datetime.now(UTC),
                uptime_seconds=max(0.0, monotonic() - self._started_at),
                request_count=self._request_count,
                error_count=self._error_count,
                cache_hits=self._cache_hits,
                cache_misses=self._cache_misses,
                provider_calls=self._provider_calls,
                in_flight_coalesced_requests=(self._in_flight_coalesced_requests),
                average_latency_ms=average_latency_ms,
                p95_latency_ms=p95_latency_ms,
                latency_sample_size=sample_size,
                cache_size=cache_size,
                evictions=self._evictions,
                expirations=self._expirations,
            )

    def _record_cache_removals(
        self,
        count: int,
        *,
        expired: bool,
    ) -> None:
        if count < 0:
            raise ValueError("Cache removal count must be non-negative")
        if count == 0:
            return
        with self._lock:
            if expired:
                self._expirations += count
            else:
                self._evictions += count
