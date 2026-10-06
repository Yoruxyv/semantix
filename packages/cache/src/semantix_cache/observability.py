"""Payload-free, per-instance coalescing evidence; no exporter or telemetry."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CoalescingSnapshot:
    """Lifetime counters and current gauges, copied coherently by the cache."""

    leaders_admitted: int
    followers_joined: int
    admissions_declined: int
    follower_hits: int
    follower_generated: int
    follower_errors: int
    follower_cancelled: int
    follower_timeouts: int
    follower_generations_started: int
    followers_pending: int
    wait_count: int
    wait_seconds: float
    active_flights: int
    retained_flights: int
    participants: int
