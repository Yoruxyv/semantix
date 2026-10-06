"""Bounded, instance-local completion gates; generation stays request-owned.

Only built-in immutable identities enter the mutex. Gates are created/notified
outside it. Terminal records remain charged until their last caller detaches;
there is no response buffer, worker task, retry, or completed-result cache.
"""

import asyncio
from dataclasses import dataclass, field
from sys import getsizeof
from threading import Lock
from time import perf_counter

from ._coalescing_metrics import Counter, Ledger, Terminal
from .errors import CacheValidationError
from .observability import CoalescingSnapshot
from .protocols import GenerationCallable

_MAX_RECORDS = 128
_MAX_PARTICIPANTS = 256
_MAX_KEY_BYTES = 4 * 1024 * 1024
Identity = tuple[str | bytes | int | float | None, ...]


def validate_key(key: str) -> None:
    if type(key) is not str or not key.strip():
        raise CacheValidationError("Invalid coalescing key")
    if len(key) > 256:
        raise CacheValidationError("Coalescing key exceeds 256 UTF-8 bytes")
    try:
        encoded = key.encode("utf-8")
    except UnicodeEncodeError:
        raise CacheValidationError("Invalid coalescing key") from None
    if len(encoded) > 256:
        raise CacheValidationError("Coalescing key exceeds 256 UTF-8 bytes")


@dataclass(eq=False, repr=False)
class Flight:
    identity: Identity
    key_bytes: int
    gate: asyncio.Future[None]
    # Strong reference prevents callable-id reuse before all callers detach.
    generate: GenerationCallable
    participants: int = 1
    error: BaseException | None = None


@dataclass(frozen=True)
class Participation:
    flight: Flight = field(repr=False)
    leader: bool


class Flights:
    def __init__(self, *, collect_metrics: bool = False) -> None:
        self._guard = Lock()
        self._active: dict[Identity, Flight] = {}
        self._records = 0
        self._participants = 0
        self._key_bytes = 0
        self._metrics: Ledger | None = None
        if collect_metrics:
            try:
                self._metrics = Ledger()
            except Exception:  # noqa: BLE001 -- collection cannot prevent cache use
                self._metrics = None

    def admit(
        self, identity: Identity, generate: GenerationCallable
    ) -> Participation | None:
        # Encoding, sizing and Future creation must never execute under the guard.
        charged = getsizeof(identity) + sum(getsizeof(value) for value in identity)
        gate: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        candidate = Flight(identity, charged, gate, generate)
        with self._guard:
            if self._participants >= _MAX_PARTICIPANTS:
                self._increment("admissions_declined")
                return None
            current = self._active.get(identity)
            if current is not None:
                current.participants += 1
                self._participants += 1
                self._increment("followers_joined")
                return Participation(current, leader=False)
            if (
                self._records >= _MAX_RECORDS
                or self._key_bytes + charged > _MAX_KEY_BYTES
            ):
                self._increment("admissions_declined")
                return None
            self._active[identity] = candidate
            self._records += 1
            self._participants += 1
            self._key_bytes += charged
            self._increment("leaders_admitted")
            return Participation(candidate, leader=True)

    def settle(self, flight: Flight, error: BaseException | None = None) -> None:
        with self._guard:
            if self._active.get(flight.identity) is flight:
                del self._active[flight.identity]
        # Future notification and exception observation may run loop callbacks.
        if isinstance(error, asyncio.CancelledError):
            flight.gate.cancel()
        else:
            # A completion-only gate avoids asyncio.shield's Python 3.14
            # cancellation warning that logs failed inner-future error text.
            # Active followers raise this terminal error after the gate opens.
            flight.error = error
            flight.gate.set_result(None)

    def release(self, flight: Flight, *, outcome: Terminal | None = None) -> None:
        with self._guard:
            flight.participants -= 1
            self._participants -= 1
            if flight.participants == 0:
                self._records -= 1
                self._key_bytes -= flight.key_bytes
            if outcome is not None:
                self._increment(outcome)

    def counts(self) -> tuple[int, int, int, int]:
        """Active map, retained records, participants, charged identity bytes."""
        with self._guard:
            return (
                len(self._active),
                self._records,
                self._participants,
                self._key_bytes,
            )

    def _increment(self, counter: Counter) -> None:
        # Called only under _guard, with fixed internal field names.
        if self._metrics is not None:
            try:
                self._metrics.increment(counter)
            except Exception:  # noqa: BLE001 -- isolate only optional bookkeeping
                self._metrics = None

    def generation_started(self, participation: Participation | None) -> None:
        if participation is None or participation.leader or self._metrics is None:
            return
        with self._guard:
            self._increment("follower_generations_started")

    def wait_started(self) -> float | None:
        if self._metrics is None:
            return None
        try:
            return perf_counter()
        except Exception:  # noqa: BLE001 -- isolate only the metrics clock
            with self._guard:
                self._metrics = None
            return None

    def wait_finished(self, started: float | None) -> None:
        if started is None or self._metrics is None:
            return
        try:
            seconds = perf_counter() - started
            with self._guard:
                if self._metrics is not None:
                    self._metrics.waited(seconds)
        except Exception:  # noqa: BLE001 -- isolate only optional wait accounting
            with self._guard:
                self._metrics = None

    def snapshot(self) -> CoalescingSnapshot | None:
        with self._guard:
            if self._metrics is None:
                return None
            try:
                values = (
                    *self._metrics.copy(),
                    len(self._active),
                    self._records,
                    self._participants,
                )
            except Exception:  # noqa: BLE001 -- isolate only the ledger copy
                self._metrics = None
                return None
        # Model construction must never run under the coalescer mutex.
        try:
            return CoalescingSnapshot(*values)
        except Exception:  # noqa: BLE001 -- a failed observation disables metrics
            with self._guard:
                self._metrics = None
            return None
