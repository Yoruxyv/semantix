"""Characterize unchanged SQLite close policy; never repair library state."""

import asyncio
import json
import sqlite3
import sys
import threading
from collections.abc import Awaitable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from semantix_cache import CacheStoreError, EmbeddingSpace
from semantix_cache.stores._backends.sqlite.database import Database
from semantix_cache.stores._backends.sqlite.worker import Job, Worker
from semantix_cache.stores.sqlite import SQLiteStore


def connection_state(connection: sqlite3.Connection) -> str:
    try:
        _ = connection.in_transaction
    except sqlite3.ProgrammingError as error:
        if "closed database" not in str(error):
            raise
        return "CLOSED"
    return "OPEN"


async def observe(
    awaitable: Awaitable[object], failures: list[dict[str, object]]
) -> None:
    try:
        await awaitable
    except (CacheStoreError, asyncio.CancelledError) as error:
        failures.append(
            {
                "type": type(error).__name__,
                "message": str(error),
                "cause": None if error.__cause__ is None else str(error.__cause__),
                "context": None
                if error.__context__ is None
                else str(error.__context__),
                "notes": getattr(error, "__notes__", []),
            }
        )


async def characterize(root: Path, mode: str) -> dict[str, object]:
    await asyncio.to_thread(root.mkdir, exist_ok=False)
    path = root / "case.db"
    space = EmbeddingSpace(identity="gate-b0-close", dimensions=2)
    await SQLiteStore.initialize_schema(path, embedding_space=space)
    original_connect = sqlite3.connect
    original_open = Database.open
    events: list[dict[str, object]] = []
    workers: list[Worker] = []
    failures: list[dict[str, object]] = []
    calls = 0
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    cancelled = mode.startswith("cancel_")
    startup = mode.startswith("startup_")

    class InjectedConnection(sqlite3.Connection):
        def close(self) -> None:
            nonlocal calls
            calls += 1
            event: dict[str, object] = {"thread": threading.get_ident(), "call": calls}
            events.append(event)
            if cancelled and calls == 1:
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError("Close barrier was not released")
            before = "before" in mode
            persistent = mode.endswith("persistent")
            if before and (persistent or calls == 1):
                event["state"] = connection_state(self)
                event["fault"] = "BEFORE_NATIVE_CLOSE"
                raise sqlite3.OperationalError("controlled close failure")
            sqlite3.Connection.close(self)
            event["state"] = connection_state(self)
            if mode.endswith("after"):
                event["fault"] = "AFTER_NATIVE_CLOSE"
                raise sqlite3.OperationalError("controlled post-close failure")

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return original_connect(*args, **kwargs, factory=InjectedConnection)

    def opened(database: Database, job: Job, *, initialize: bool = False) -> None:
        original_open(database, job, initialize=initialize)
        workers.append(job.owner)
        events.append({"opened_thread": threading.get_ident()})
        if mode == "startup_cancel_before":
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("Startup barrier was not released")
        elif startup:
            raise CacheStoreError("controlled startup failure")

    with (
        patch.object(sqlite3, "connect", connect),
        patch.object(Database, "open", opened),
    ):
        if startup:
            if mode == "startup_cancel_before":
                opening = asyncio.create_task(
                    SQLiteStore.connect(path, embedding_space=space)
                )
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    opening.cancel()
                finally:
                    release.set()
                await observe(opening, failures)
            else:
                await observe(
                    SQLiteStore.connect(path, embedding_space=space), failures
                )
        else:
            store = await SQLiteStore.connect(path, embedding_space=space)
            if cancelled:
                first = asyncio.create_task(observe(store.aclose(), failures))
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    first.cancel()
                    await first
                    assert workers[0].cleanup is not None
                    assert not workers[0].cleanup.done()
                    assert workers[0].connection is not None
                    assert not workers[0].pool._shutdown
                    events.append({"cancelled_await_retained_owned_work": True})
                finally:
                    release.set()
            else:
                await observe(store.aclose(), failures)
            await observe(store.aclose(), failures)

    assert len(workers) == 1
    worker = workers[0]
    verify(worker, events, failures, mode, calls)
    assert worker.cleanup is not None
    cleanup_error = worker.cleanup.exception()
    return {
        "mode": mode,
        "source": sys.modules[SQLiteStore.__module__].__file__,
        "events": events,
        "public_failures": failures,
        "native_close_calls": calls,
        "physical_state_at_close_boundary": events[1]["state"],
        "connection_reference_retained": worker.connection is not None,
        "executor_shutdown": worker.pool._shutdown,
        "executor_threads_alive": sum(t.is_alive() for t in worker.pool._threads),
        "cleanup_error": None if cleanup_error is None else str(cleanup_error),
        "assertions": "PASS",
        "process_exit_is_not_library_disposal": True,
    }


def verify(
    worker: Worker,
    events: list[dict[str, object]],
    failures: list[dict[str, object]],
    mode: str,
    calls: int,
) -> None:
    cancelled = mode.startswith("cancel_")
    startup = mode.startswith("startup_")
    assert worker.cleanup is not None
    assert worker.cleanup.done()
    cleanup_error = worker.cleanup.exception()
    assert calls == 1, "Baseline must not retry native close"
    opened_thread = events[0]["opened_thread"]
    assert events[1]["thread"] == opened_thread
    assert opened_thread != threading.get_ident()
    assert not worker.pending and worker.admitted == 0
    assert worker.pool._shutdown
    assert all(not thread.is_alive() for thread in worker.pool._threads)
    expected_open = "before" in mode
    assert events[1]["state"] == ("OPEN" if expected_open else "CLOSED")
    if mode in {"success", "cancel_success"}:
        assert cleanup_error is None and worker.connection is None
        assert len(failures) == int(cancelled)
    else:
        assert isinstance(cleanup_error, CacheStoreError)
        assert worker.connection is not None
        if startup:
            assert len(failures) == 1
            if mode == "startup_cancel_before":
                assert failures[0]["type"] == "CancelledError"
            else:
                assert failures[0]["type"] == "CacheStoreError"
                assert failures[0]["message"] == "controlled startup failure"
            assert failures[0]["cause"] == "SQLite owned connection cleanup failed"
        elif cancelled:
            assert [f["type"] for f in failures] == [
                "CancelledError",
                "CacheStoreError",
            ]
        else:
            assert len(failures) == 2


if __name__ == "__main__":
    print(
        json.dumps(asyncio.run(characterize(Path(sys.argv[1]), sys.argv[2])), indent=2)
    )
