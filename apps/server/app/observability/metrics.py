"""Process-local interactive-query event counters and bounded latency samples.

Query callers record starts/completions, shared cache lookups emit hit/miss
events, and generation records attempts before the provider await. Coalescing
means these counts need not match. Storage adapters report observed removals;
this module neither polls every backend nor aggregates replicas or persists data.
"""

import math
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic

MAX_LATENCY_SAMPLES = 2_048


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """Frozen process-local observations plus a caller-supplied cache size.

    request_count counts starts; error_count counts completions marked failed.
    Average latency uses all recorded completions, including failures, while p95
    uses at most 2,048 recent completion samples. Both are None before samples exist.
    The follower gauge and lookup/provider/removal counters reflect reported events,
    not per-request reconstructions. Cache size is not read under the metrics lock.
    observed_at is UTC; uptime uses monotonic time since RuntimeMetrics construction.
    """

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
    """Bounded process-local metrics for the interactive query path.

    Mutations and snapshot copying use one thread lock; construction starts empty.
    Callers own event pairing/classification. Starts and completions are independent,
    so starts include unfinished work and the collector does not infer HTTP status
    or enforce one completion per start. Counters last for this object's lifetime;
    they are not distributed, persistent telemetry or a complete health assessment.
    """

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
        """Count an admitted query-service invocation before its work can fail."""
        with self._lock:
            self._request_count += 1

    def record_request_completed(
        self,
        latency_ms: float,
        *,
        failed: bool,
    ) -> None:
        """Record one completion latency, including completions classified as failed.

        Update the lifetime total/denominator and append to the bounded recent sample
        under one lock. Invalid latency is rejected before counters change.

        Args:
            latency_ms: Finite nonnegative elapsed milliseconds supplied by the caller.
            failed: Whether to increment error_count for this completion.

        Raises:
            ValueError: latency_ms is negative or nonfinite.
        """
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("latency_ms must be finite and non-negative")
        with self._lock:
            self._completed_request_count += 1
            if failed:
                self._error_count += 1
            self._latency_total_ms += latency_ms
            self._latencies_ms.append(latency_ms)

    def record_cache_hit(self) -> None:
        """Count a confirmed shared lookup hit, not each coalesced caller."""
        with self._lock:
            self._cache_hits += 1

    def record_cache_miss(self) -> None:
        """Count a completed shared lookup miss; bypassed reads emit neither event."""
        with self._lock:
            self._cache_misses += 1

    def record_provider_call(self) -> None:
        """Count a generation attempt before awaiting its outcome, including failures."""
        with self._lock:
            self._provider_calls += 1

    def record_coalesced_delta(self, delta: int) -> None:
        """Adjust the in-flight follower gauge without permitting a negative value.

        Args:
            delta: One on follower entry or minus one on exit, as supplied by the coalescer.

        Raises:
            ValueError: delta is not -1 or 1.
            RuntimeError: The update would make the gauge negative.
        """
        if delta not in {-1, 1}:
            raise ValueError("Coalesced request delta must be -1 or 1")
        with self._lock:
            next_value = self._in_flight_coalesced_requests + delta
            if next_value < 0:
                raise RuntimeError("Coalesced request count cannot be negative")
            self._in_flight_coalesced_requests = next_value

    def record_evictions(self, count: int) -> None:
        """Add reported eviction events without inferring uninstrumented backend activity.

        Raises:
            ValueError: count is negative; zero is a no-op.
        """
        self._record_cache_removals(count, expired=False)

    def record_expirations(self, count: int) -> None:
        """Add reported expiry-removal events, not every record hidden by an expiry filter.

        Raises:
            ValueError: count is negative; zero is a no-op.
        """
        self._record_cache_removals(count, expired=True)

    def snapshot(self, *, cache_size: int) -> MetricsSnapshot:
        """Copy counters and latency summaries under the lock with a supplied cache size.

        Average latency divides the lifetime total by completed requests. Runtime p95
        sorts up to 2,048 recent samples and selects index ceil(n * 0.95) - 1, without
        interpolation. Both latency values are None before any recorded completion.
        Evaluation metrics use a separate interpolated percentile implementation.
        The caller's cache size observation is not atomic with these metrics.

        Args:
            cache_size: Separately observed nonnegative storage size.

        Returns:
            Frozen counters, sample size, UTC observation time and monotonic uptime.

        Raises:
            ValueError: cache_size is negative.
        """
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
