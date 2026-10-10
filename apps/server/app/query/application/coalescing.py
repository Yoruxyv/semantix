"""Share concurrent work for requests with the same cache policy key.

This server implementation accepts caller-defined string keys and has no cache
policy eligibility rules, authorization, persistent result cache or cross-process
coordination. Its shielding/cleanup contract is separate from the embedded
AsyncSemanticCache cold-miss coalescer. Operation timeouts belong to callers or
dependencies; this class supplies no deadline or explicit shutdown/drain method.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

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
            asyncio.CancelledError: This caller or the underlying operation is cancelled.
                Other operation exceptions propagate to its awaiters as well.
        """
        async with self._lock:
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
        cleanup.add_done_callback(self._cleanup_tasks.discard)

    async def _remove(
        self,
        key: str,
        completed: asyncio.Future[Result],
    ) -> None:
        async with self._lock:
            if self._in_flight.get(key) is completed:
                del self._in_flight[key]
