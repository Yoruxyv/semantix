"""Share concurrent work for requests with the same cache policy key.

This server implementation accepts caller-defined string keys and has no cache
policy eligibility rules, authorization, persistent result cache or cross-process
coordination. Its shielding/cleanup contract is separate from the embedded
AsyncSemanticCache cold-miss coalescer. Operation timeouts belong to callers or
dependencies. Shutdown seals admission, gracefully drains, then cancels and joins
retained work before its owner releases dependencies.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from math import isfinite
from typing import Generic, TypeVar

from app.core.exceptions import QueryShuttingDownError

Result = TypeVar("Result")
WaiterDeltaCallback = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class CoalescedResult(Generic[Result]):
    """Return shared value plus whether this caller registered the operation.

    is_leader identifies task creation, not a confirmed hit or provider call.
    """

    value: Result
    is_leader: bool


class RequestCoalescer(Generic[Result]):
    """Own one shared future per registered key within this instance/event loop.

    The first caller creates the operation; followers await that future. Completion
    schedules identity-checked removal, with awaited cleanup also attempted by
    callers observing completion. A completed future can briefly remain registered.
    Cleanup tasks are retained until done; removal leaves no completed-result cache.
    """

    def __init__(
        self,
        on_waiter_delta: WaiterDeltaCallback | None = None,
    ) -> None:
        """Create an empty registry and optional synchronous follower gauge.

        Args:
            on_waiter_delta: Non-raising callback receiving +1 when a follower joins and
                -1 in its await-finally path, including cancellation or failure. Leaders
                do not change this gauge.
        """
        self._in_flight: dict[str, asyncio.Future[Result]] = {}
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()
        self._shutdown_task: asyncio.Task[None] | None = None
        self._on_waiter_delta = on_waiter_delta

    async def run(
        self,
        key: str,
        operation: Callable[[], Awaitable[Result]],
    ) -> CoalescedResult[Result]:
        """Create or join registered work, shielding it from caller cancellation.

        Only the leader invokes operation; followers use its value or exception.
        Cancelling either caller's await does not itself cancel the shared future,
        which can finish after all callers leave. If the shared operation is cancelled,
        awaiters receive cancellation. Completion removes only the same registered
        future, allowing later requests to start fresh work rather than reuse a result.
        This is in-flight sharing, not exactly-once external execution.

        Args:
            key: Caller-defined work identity; namespace/policy isolation belongs upstream.
            operation: Async work factory invoked only when no future is registered.

        Returns:
            Shared value and whether this caller created its future.

        Raises:
            QueryShuttingDownError: Shutdown has sealed admission for this instance.
            asyncio.CancelledError: This caller or the underlying operation is cancelled.
                Other operation exceptions propagate to its awaiters as well.
        """
        async with self._lock:
            if self._shutdown_task is not None:
                raise QueryShuttingDownError
            task = self._in_flight.get(key)
            is_leader = task is None
            if task is None:
                task = asyncio.ensure_future(operation())
                self._in_flight[key] = task
                task.add_done_callback(
                    lambda completed: self._schedule_cleanup(key, completed)
                )
            elif self._on_waiter_delta is not None:
                self._on_waiter_delta(1)

        try:
            value = await asyncio.shield(task)
        finally:
            if not is_leader and self._on_waiter_delta is not None:
                self._on_waiter_delta(-1)
            if task.done():
                await self._remove(key, task)
        return CoalescedResult(value=value, is_leader=is_leader)

    def _schedule_cleanup(
        self,
        key: str,
        completed: asyncio.Future[Result],
    ) -> None:
        """Observe an unclaimed exception and retain asynchronous registry cleanup.

        Retrieving exception() prevents abandoned failures becoming unhandled-task
        warnings; awaiters still receive the original exception. Cancelled futures
        skip that retrieval because exception() would itself raise cancellation.
        """
        if not completed.cancelled():
            completed.exception()
        cleanup = asyncio.create_task(self._remove(key, completed))
        self._cleanup_tasks.add(cleanup)
        cleanup.add_done_callback(self._cleanup_finished)

    def _cleanup_finished(self, cleanup: asyncio.Task[None]) -> None:
        if self._shutdown_task is None:
            self._cleanup_tasks.discard(cleanup)

    async def aclose(self, *, grace_seconds: float) -> None:
        """Seal once and settle shared operations plus asynchronous registry cleanup.

        Sealing/snapshotting happen before the first await. Registry critical sections
        in run/_remove never suspend, so registration cannot interleave with the seal.
        The grace deadline requests cancellation; it is not a deadline for joining
        cancellation-resistant work. Concurrent/repeated closes share the same outcome.
        Caller cancellation is re-raised only after owned work has settled.
        """
        if not isfinite(grace_seconds) or grace_seconds < 0:
            raise ValueError("Shutdown grace must be finite and nonnegative")
        if self._shutdown_task is None:
            operations = tuple(self._in_flight.values())
            self._shutdown_task = asyncio.create_task(
                self._drain(operations, grace_seconds)
            )
        await _join_shutdown(self._shutdown_task)

    async def _drain(
        self,
        operations: tuple[asyncio.Future[Result], ...],
        grace_seconds: float,
    ) -> None:
        failures: list[BaseException] = []
        if operations:
            _, pending = await asyncio.wait(operations, timeout=grace_seconds)
            for operation in pending:
                operation.cancel()
            await asyncio.gather(*operations, return_exceptions=True)
            for operation in operations:
                if not operation.cancelled():
                    error = operation.exception()
                    if error is not None:
                        failures.append(error)
        # Resolution callbacks register cleanup before the gathered tasks settle.
        # Keep completed cleanup registered during shutdown so failures stay visible.
        while self._cleanup_tasks:
            cleanups = tuple(self._cleanup_tasks)
            await asyncio.gather(*cleanups, return_exceptions=True)
            self._cleanup_tasks.difference_update(cleanups)
            for cleanup in cleanups:
                if cleanup.cancelled():
                    failures.append(
                        asyncio.CancelledError("Query cleanup was cancelled")
                    )
                else:
                    error = cleanup.exception()
                    if error is not None:
                        failures.append(error)
        if failures:
            raise BaseExceptionGroup("Shared query shutdown failed", failures)

    async def _remove(
        self,
        key: str,
        completed: asyncio.Future[Result],
    ) -> None:
        async with self._lock:
            if self._in_flight.get(key) is completed:
                del self._in_flight[key]


async def _join_shutdown(task: asyncio.Task[None]) -> None:
    """Delay even repeated caller cancellation until the owned shutdown settles."""
    settled = asyncio.gather(task, return_exceptions=True)
    cancelled = False
    while not settled.done():
        try:
            await asyncio.shield(settled)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        error = settled.result()[0]
        if isinstance(error, BaseException):
            raise asyncio.CancelledError from error
        raise asyncio.CancelledError
    task.result()
