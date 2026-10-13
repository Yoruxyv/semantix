"""Bounded accountability for MySQL construction that cannot return its owner."""

from __future__ import annotations

import asyncio
import os
import threading
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from ..errors import (
    CacheBusyError,
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
)
from ._mysql_format import safe

if TYPE_CHECKING:
    from ._mysql_worker import Worker

LIMIT = 8
_pid = os.getpid()
_lock = threading.Lock()
_owners: dict[str, Worker | None] = {}
_failed: set[str] = set()
_history: deque[MySQLCleanupStatus] = deque(maxlen=LIMIT)


@dataclass(frozen=True)
class MySQLCleanupStatus:
    """Safe process-local diagnostic; contains no connection or configuration.

    loop_closed is current for retained owners, captured at retirement for history.
    """

    cleanup_id: str
    state: Literal["pending", "retained", "retired", "escalation-required"]
    resources: tuple[str, ...]
    failure: str | None
    loop_closed: bool


def _check_process() -> None:
    if os.getpid() != _pid:
        safe(
            CacheConfigurationError(
                "MySQL cleanup management cannot be inherited across fork"
            )
        )


def _status(key: str, worker: Worker) -> MySQLCleanupStatus:
    future = worker.disposal
    done = future is not None and future.done()
    failure = (
        (future.result() or worker.cleanup_failure)
        if future is not None and done
        else None
    )
    resources = worker.remaining
    state: Literal["pending", "retained", "retired", "escalation-required"] = "pending"
    if done and not (
        worker.pool_stopped and worker.thread is not None and worker.thread.is_alive()
    ):
        state = "retained" if resources else "retired"
        if resources and worker.pool_stopped:
            state = "escalation-required"
    return MySQLCleanupStatus(
        key,
        state,
        resources,
        failure[1] if failure is not None else None,
        worker.loop.is_closed(),
    )


def _reap() -> None:
    for key, worker in tuple(_owners.items()):
        if (
            key not in _failed
            or worker is None
            or worker.disposal is None
            or not worker.disposal.done()
        ):
            continue
        if (
            not worker.remaining
            and worker.pool_stopped
            and (worker.thread is None or not worker.thread.is_alive())
        ):
            status = _status(key, worker)
            if status.failure is not None:
                _history.append(status)
            del _owners[key]
            _failed.remove(key)


def reserve() -> str:
    _check_process()
    with _lock:
        _reap()
        if len(_owners) >= LIMIT:
            safe(
                CacheBusyError(
                    "MySQL construction cleanup capacity exhausted; inspect failed_cleanups()"
                )
            )
        key = uuid4().hex
        _owners[key] = None
        return key


def attach(key: str, worker: Worker) -> None:
    with _lock:
        _owners[key] = worker


def release(key: str) -> None:
    with _lock:
        _owners.pop(key, None)
        _failed.discard(key)


def retain(key: str) -> None:
    with _lock:
        _failed.add(key)


def statuses() -> tuple[MySQLCleanupStatus, ...]:
    _check_process()
    with _lock:
        _reap()
        return tuple(_history) + tuple(
            _status(key, worker)
            for key, worker in _owners.items()
            if key in _failed and worker is not None
        )


async def retry(key: object) -> None:
    _check_process()
    if not isinstance(key, str):
        safe(CacheConfigurationError("Unknown MySQL construction cleanup ID"))
    with _lock:
        _reap()
        worker = _owners.get(key)
        if key not in _failed or worker is None:
            if any(item.cleanup_id == key for item in _history):
                return
            safe(CacheConfigurationError("Unknown MySQL construction cleanup ID"))
    if worker.pool_stopped and worker.remaining:
        safe(
            CacheStoreError(
                "MySQL physical close is unconfirmed; controlled process restart required"
            )
        )
    future = worker.submit_cleanup(terminal=True)
    wrapped = asyncio.wrap_future(future)
    done, _ = await asyncio.wait({wrapped}, timeout=worker.config.close_timeout)
    if not done:
        safe(
            CacheTimeoutError(
                "MySQL cleanup retry timed out; owner remains discoverable"
            )
        )
    failure = wrapped.result()
    if worker.pool_stopped:
        try:
            async with asyncio.timeout(worker.config.close_timeout):
                while worker.thread is not None and worker.thread.is_alive():  # noqa: ASYNC110 -- observe actual executor termination without another worker
                    await asyncio.sleep(0.005)
        except TimeoutError:
            safe(CacheTimeoutError("MySQL worker termination remains owned"))
    with _lock:
        _reap()
    if failure is not None:
        kind, message = failure
        safe(kind(message))
