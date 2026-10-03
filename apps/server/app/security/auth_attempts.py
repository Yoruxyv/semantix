from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic

FAILURES_PER_STAGE = 3
LOCKOUT_DURATIONS_SECONDS = (30, 60, 3_600)
STALE_STATE_SECONDS = 86_400


@dataclass(slots=True)
class _ClientAttempts:
    failures: int
    escalation_stage: int
    locked_until: float | None
    last_activity: float


class AuthenticationAttemptTracker:
    """Track progressive authentication lockouts for one application process."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        stale_state_seconds: int = STALE_STATE_SECONDS,
    ) -> None:
        self._clock = clock
        self._stale_state_seconds = stale_state_seconds
        self._attempts: dict[str, _ClientAttempts] = {}
        self._lock = Lock()

    def retry_after(self, client: str) -> int | None:
        """Return the active lock duration without extending or counting it."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            state = self._attempts.get(client)
            if state is None or state.locked_until is None:
                return None

            remaining = state.locked_until - now
            if remaining <= 0:
                state.locked_until = None
                state.last_activity = now
                return None
            return max(1, ceil(remaining))

    def record_failure(self, client: str) -> int | None:
        """Record one failed session attempt and return a new lock duration."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            state = self._attempts.get(client)
            if state is None:
                state = _ClientAttempts(
                    failures=0,
                    escalation_stage=0,
                    locked_until=None,
                    last_activity=now,
                )
                self._attempts[client] = state

            if state.locked_until is not None:
                remaining = state.locked_until - now
                if remaining > 0:
                    return max(1, ceil(remaining))
                state.locked_until = None

            state.failures += 1
            state.last_activity = now
            if state.failures < FAILURES_PER_STAGE:
                return None

            duration = LOCKOUT_DURATIONS_SECONDS[
                min(
                    state.escalation_stage,
                    len(LOCKOUT_DURATIONS_SECONDS) - 1,
                )
            ]
            state.failures = 0
            state.escalation_stage += 1
            state.locked_until = now + duration
            return duration

    def reset(self, client: str) -> None:
        """Forget all failures, escalation, and lock state after success."""
        with self._lock:
            self._attempts.pop(client, None)

    def _prune(self, now: float) -> None:
        stale_clients = [
            client
            for client, state in self._attempts.items()
            if now - state.last_activity >= self._stale_state_seconds
        ]
        for client in stale_clients:
            del self._attempts[client]
