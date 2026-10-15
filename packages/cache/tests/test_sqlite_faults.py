"""Failure, cancellation and connection-lifetime tests using deterministic barriers."""

import asyncio
import sqlite3
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache import (
    CacheBusyError,
    CacheClosedError,
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
)
from semantix_cache.stores._backends.sqlite import database
from semantix_cache.stores._backends.sqlite import worker as worker_module
from semantix_cache.stores._backends.sqlite.format import Configuration
from semantix_cache.stores._backends.sqlite.worker import Job, Row, Worker
from semantix_cache.stores.sqlite import SQLiteStore

from . import sqlite_helpers
from .sqlite_helpers import block_lookup, connection, drain_workers, state

sqlite_store = sqlite_helpers.sqlite_store


@pytest.mark.parametrize(
    ("operation", "point"),
    [
        ("put", "INSERT INTO cache_entries"),
        ("put", "INSERT INTO cache_payloads"),
        ("put", "UPDATE binding_state"),
        ("put", "DELETE FROM cache_entries"),
        ("hit", "WITH observation"),
        ("hit", "UPDATE binding_state"),
        ("delete", "DELETE FROM cache_entries"),
        ("clear", "DELETE FROM cache_entries"),
        ("put", "COMMIT"),
    ],
)
async def test_failure_after_business_statement_rolls_back(
    sqlite_store: SQLiteStore,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    point: str,
) -> None:
    value = entry("original")
    await sqlite_store.put(value)
    candidate = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert candidate
    before = state(sqlite_store._config.path)
    if point == "COMMIT":
        await sqlite_store._worker.run(
            lambda job: job.connection.set_authorizer(
                lambda action, first, second, database_name, source: (
                    sqlite3.SQLITE_DENY
                    if action == sqlite3.SQLITE_TRANSACTION and first == "COMMIT"
                    else sqlite3.SQLITE_OK
                )
            )
        )
    original = Job.rows
    fired: list[str] = []

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        if sql.startswith(point) and not fired:
            fired.append(sql)
            if point == "COMMIT":
                return original(job, sql, parameters)
            original(job, sql, parameters)
            raise sqlite3.OperationalError("sensitive path prompt response")
        return original(job, sql, parameters)

    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)

        async def mutate() -> None:
            if operation == "put":
                await sqlite_store.put(entry("replacement"))
            elif operation == "hit":
                await sqlite_store.record_hit(
                    value.cache_key,
                    namespace="default",
                    expected_created_at=candidate.entry.created_at,
                )
            elif operation == "delete":
                await sqlite_store.delete_entry(value.cache_key, namespace="default")
            else:
                await sqlite_store.clear(namespace="default")

        with pytest.raises(CacheStoreError) as caught:
            await mutate()
        assert caught.value.__context__ is None
        assert "sensitive" not in str(caught.value)
    assert fired
    assert state(sqlite_store._config.path) == before
    if point == "COMMIT":
        assert sqlite_store._worker.faulted.is_set()
        with pytest.raises(CacheStoreError, match="faulted"):
            await sqlite_store.clear(namespace="default")
    else:
        await sqlite_store.put(entry("usable after rollback"))


@pytest.mark.parametrize("side", ["before", "after"])
async def test_cancel_around_commit_retains_worker_and_never_replays(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch, side: str
) -> None:
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = Job.rows
    commits = []

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        if sql == "COMMIT":
            commits.append(sql)
            result = original(job, sql, parameters) if side == "after" else []
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(10):
                raise RuntimeError("Test did not release commit")
            return result if side == "after" else original(job, sql, parameters)
        return original(job, sql, parameters)

    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)
        task = asyncio.create_task(sqlite_store.put(entry("commit boundary")))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(CacheBusyError):
                await sqlite_store.aclose()
            assert sqlite_store._worker.admitted == 1
        finally:
            release.set()
        if sqlite_store._worker.pending:
            await asyncio.gather(
                *tuple(sqlite_store._worker.pending), return_exceptions=True
            )
    with connection(sqlite_store._config.path) as db:
        assert db.execute("SELECT count(*) FROM cache_entries").fetchone() == (
            int(side == "after"),
        )
        assert db.execute("SELECT access_counter FROM binding_state").fetchone() == (
            int(side == "after"),
        )
    assert commits == ["COMMIT"]
    await sqlite_store.put(entry("next operation"))


async def test_cancelled_numeric_worker_admission_and_delayed_interrupt(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sqlite_store.put(entry("numeric"))
    async with block_lookup(sqlite_store, monkeypatch) as entered:
        task = asyncio.create_task(
            sqlite_store.find_nearest((1, 0), namespace="default")
        )
        await asyncio.wait_for(entered.wait(), 5)
        old = sqlite_store._worker.current
        assert old
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sqlite_store._worker.admitted == 1
        assert len(sqlite_store._worker.pending) == 1
        waiters = [
            asyncio.create_task(sqlite_store.clear(namespace="other"))
            for _ in range(31)
        ]
        await asyncio.sleep(0)  # let each coroutine reach its local admission wait
        assert sqlite_store._worker.admitted == 32
        with pytest.raises(CacheStoreError, match="admission"):
            await sqlite_store.clear(namespace="other")
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        assert sqlite_store._worker.admitted == 1
    # Deliver the old token while a later job is active; it must not stop that job.
    async with block_lookup(sqlite_store, monkeypatch) as entered:
        task = asyncio.create_task(
            sqlite_store.find_nearest((1, 0), namespace="default")
        )
        await asyncio.wait_for(entered.wait(), 5)
        assert sqlite_store._worker.current is not old
        sqlite_store._worker.interrupt(old)
    assert await task is not None
    await sqlite_store.aclose()
    sqlite_store._worker.interrupt(old)  # safely ignores a closed connection


@pytest.mark.parametrize("retained_completion", [False, True])
async def test_real_sql_progress_cancellation_and_lock_deadline(
    sqlite_store: SQLiteStore,
    monkeypatch: pytest.MonkeyPatch,
    retained_completion: bool,
) -> None:
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()

    def started() -> int:
        loop.call_soon_threadsafe(entered.set)
        return 1

    def work(job: Job) -> list[Row]:
        job.connection.create_function("test_started", 0, started)
        return job.rows(
            "WITH RECURSIVE n(x) AS (SELECT test_started() UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n"
        )

    task = asyncio.create_task(sqlite_store._worker.run(work))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await sqlite_store.put(entry("after interrupt"))
    path = sqlite_store._config.path
    other = await SQLiteStore.connect(
        path,
        embedding_space=SPACE,
        default_ttl_seconds=None,
    )
    release = threading.Event()
    pending = asyncio.Event()
    original = Job.rows

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        try:
            return original(job, sql, parameters)
        finally:
            if (
                retained_completion
                and job.owner is other._worker
                and sql == "BEGIN IMMEDIATE"
            ):
                loop.call_soon_threadsafe(pending.set)
                if not release.wait(5):
                    raise RuntimeError("Test did not release retained SQLite work")

    monkeypatch.setattr(Job, "rows", rows)
    try:
        with connection(path) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            with pytest.raises(CacheTimeoutError):
                # Limit only the deadline probe, not the independent recovery write.
                await other._worker.run(
                    lambda job: other._database.put(job, entry("timed out"), None),
                    budget_seconds=0.15,
                )
            blocker.execute("ROLLBACK")
        if retained_completion:
            await asyncio.wait_for(pending.wait(), 5)
            assert other._worker.pending
            with pytest.raises(CacheBusyError):
                await other.aclose()
        release.set()
        await drain_workers(other)
        assert not other._worker.faulted.is_set()
        await other.put(entry("later independent operation"))
        with connection(path) as db:
            assert (
                db.execute(
                    "SELECT cache_key FROM cache_entries WHERE cache_key=?",
                    (entry("timed out").cache_key,),
                ).fetchall()
                == []
            )
    finally:
        release.set()
        await drain_workers(other)
        await other.aclose()


async def test_rollback_failure_faults_and_owned_close_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = sqlite3.connect
    fail = [False]
    closed = []

    class FaultConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            if fail[0] and sql == "ROLLBACK":
                raise sqlite3.OperationalError("secret rollback")
            return super().execute(sql, parameters)

        def close(self) -> None:
            closed.append(threading.get_ident())
            super().close()

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return real_connect(*args, factory=FaultConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    path = tmp_path / "rollback.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    store = await SQLiteStore.connect(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    original = Job.rows

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        result = original(job, sql, parameters)
        if sql.startswith("INSERT INTO cache_payloads"):
            raise sqlite3.OperationalError("secret write")
        return result

    fail[0] = True
    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)
        with pytest.raises(CacheStoreError, match="cleanup failed"):
            await store.put(entry("uncommitted"))
    assert store._worker.faulted.is_set()
    with pytest.raises(CacheStoreError, match="faulted"):
        await store.clear(namespace="default")
    await store.aclose()
    assert len(closed) == 2
    assert all(thread != threading.get_ident() for thread in closed)
    with connection(path) as db:
        assert db.execute("SELECT count(*) FROM cache_entries").fetchone() == (0,)


async def test_startup_cancel_and_partial_setup_close_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    workers = []
    original = database.Database.open

    def opening(
        active: database.Database, job: Job, *, initialize: bool = False
    ) -> None:
        workers.append(job.owner)
        original(active, job, initialize=initialize)
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(10):
            raise RuntimeError("Startup test not released")

    monkeypatch.setattr(database.Database, "open", opening)
    task = asyncio.create_task(
        SQLiteStore.initialize_schema(tmp_path / "startup.db", embedding_space=SPACE)
    )
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(workers) == 1
    assert workers[0].connection is None
    assert workers[0].cleanup
    assert workers[0].cleanup.done()
    monkeypatch.setattr(database.Database, "open", original)
    # Fail after actual DDL: preserve the owned incomplete file, never adopt it later.
    rows_original = Job.rows

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        result = rows_original(job, sql, parameters)
        if sql.startswith("CREATE TABLE cache_entries"):
            raise sqlite3.OperationalError("setup failed")
        return result

    path = tmp_path / "partial.db"
    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)
        with pytest.raises(CacheStoreError):
            await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
    assert path.is_file()
    with pytest.raises(CacheStoreError):
        await SQLiteStore.initialize_schema(path, embedding_space=SPACE)


async def test_close_shared_cancel_timeout_and_thread_cleanup(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    calls = []
    original = Worker._close_connection

    def close(worker: Worker) -> None:
        calls.append(threading.get_ident())
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(10):
            raise RuntimeError("Close test not released")
        original(worker)

    monkeypatch.setattr(Worker, "_close_connection", close)
    first = asyncio.create_task(sqlite_store.aclose())
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(sqlite_store.aclose())
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(CacheClosedError):
        await sqlite_store.clear(namespace="default")
    release.set()
    await second
    await sqlite_store.aclose()
    assert len(calls) == 1
    assert calls[0] != threading.get_ident()
    assert sqlite_store._worker.connection is None


async def test_close_failure_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "close-failure.db"
    await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
    store = await SQLiteStore.connect(path, embedding_space=SPACE)
    calls = []
    original = Worker._close_connection

    def close(worker: Worker) -> None:
        calls.append(1)
        original(worker)
        raise sqlite3.OperationalError("secret close")

    with monkeypatch.context() as patch:
        patch.setattr(Worker, "_close_connection", close)
        for _ in range(2):
            with pytest.raises(CacheStoreError, match="cleanup failed"):
                await store.aclose()
    assert calls == [1]
    assert store._worker.connection is None


async def test_process_and_loop_ownership_rejection(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_store._worker, "pid", -1)
        with pytest.raises(CacheConfigurationError):
            await sqlite_store.clear(namespace="default")

    def another_loop() -> None:
        with pytest.raises(CacheConfigurationError):
            asyncio.run(sqlite_store.clear(namespace="default"))

    await asyncio.to_thread(another_loop)


async def test_confirmation_clock_is_fresh_after_preflight(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1700000000000000]
    monkeypatch.setattr(database, "now_us", lambda: clock[0])
    await sqlite_store._worker.run(
        lambda job: job.connection.create_function(
            "semantix_now_us", 0, lambda: clock[0]
        )
    )
    value = entry("boundary crossed")
    await sqlite_store.put(value, ttl_seconds=1.0)
    match = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert match is not None
    assert match.expires_at is not None
    before = state(sqlite_store._config.path)
    original = Job.rows
    reached: list[str] = []

    def rows(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        if sql.startswith("WITH observation"):
            reached.append(sql)
            clock[0] += 1000000
        return original(job, sql, parameters)

    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)
        assert not await sqlite_store.record_hit(
            value.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
    assert len(reached) == 1
    assert state(sqlite_store._config.path) == before


async def test_close_timeout_keeps_one_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "close-timeout.db"
    await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
    store = await SQLiteStore.connect(
        path, embedding_space=SPACE, close_timeout_seconds=0.05
    )
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = Worker._close_connection
    calls: list[int] = []

    def close(worker: Worker) -> None:
        calls.append(1)
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(10):
            raise RuntimeError("Close timeout test was not released")
        original(worker)

    with monkeypatch.context() as patch:
        patch.setattr(Worker, "_close_connection", close)
        try:
            task = asyncio.create_task(store.aclose())
            await asyncio.wait_for(entered.wait(), 5)
            with pytest.raises(CacheTimeoutError):
                await task
            assert store._worker.cleanup is not None
            assert not store._worker.cleanup.done()
            with pytest.raises(CacheClosedError):
                await store.clear(namespace="default")
        finally:
            release.set()
        await store.aclose()
    assert calls == [1]
    assert store._worker.connection is None


async def test_commit_acknowledgement_loss_faults_without_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "lost-commit.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    real_connect = sqlite3.connect
    commits: list[int] = []
    armed = [False]

    class LostAckConnection(sqlite3.Connection):
        def execute(self, sql: str, parameters: Any = (), /) -> sqlite3.Cursor:
            cursor = super().execute(sql, parameters)
            if armed[0] and sql == "COMMIT":
                commits.append(1)
                cursor.close()
                raise sqlite3.OperationalError("secret acknowledgement loss")
            return cursor

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        return real_connect(*args, factory=LostAckConnection, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    store = await SQLiteStore.connect(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    armed[0] = True
    with pytest.raises(CacheStoreError):
        await store.put(entry("committed once"))
    assert store._worker.faulted.is_set()
    with pytest.raises(CacheStoreError, match="faulted"):
        await store.put(entry("never submitted"))
    await store.aclose()
    assert commits == [1]
    armed[0] = False
    with connection(path) as db:
        assert db.execute("SELECT access_counter FROM binding_state").fetchone() == (1,)
        assert db.execute("SELECT cache_key FROM cache_entries").fetchall() == [
            (entry("committed once").cache_key,)
        ]


async def test_cancel_while_connection_open_is_still_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "open-cancel.db"
    await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = sqlite3.connect
    closed: list[int] = []

    class TrackedConnection(sqlite3.Connection):
        def close(self) -> None:
            closed.append(threading.get_ident())
            super().close()

    def connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(10):
            raise RuntimeError("Connection open test was not released")
        return original(*args, factory=TrackedConnection, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        task = asyncio.create_task(SQLiteStore.connect(path, embedding_space=SPACE))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(closed) == 1
    assert closed[0] != threading.get_ident()
    async with await SQLiteStore.connect(path, embedding_space=SPACE) as store:
        await store.put(entry("later startup works"))


@pytest.mark.parametrize("remaining_seconds", [0.0005, 0.0065, 0.1495, 1.5])
async def test_native_lock_wait_covers_remaining_deadline(
    sqlite_store: SQLiteStore,
    monkeypatch: pytest.MonkeyPatch,
    remaining_seconds: float,
) -> None:
    def budget(job: Job) -> int:
        with monkeypatch.context() as patch:
            patch.setattr(worker_module, "monotonic", lambda: 1000.0)
            Job(job.owner, 1000.0 + remaining_seconds).prepare()
            row = job.connection.execute("PRAGMA busy_timeout").fetchone()
            assert row is not None
            return int(row[0])

    milliseconds = await sqlite_store._worker.run(budget)
    assert milliseconds / 1000 >= min(remaining_seconds, 1.0)
    assert 0 < milliseconds <= 1000


@pytest.mark.parametrize(
    ("expired", "expected"), [(False, CacheStoreError), (True, CacheTimeoutError)]
)
async def test_native_failure_classification_at_deadline(
    sqlite_store: SQLiteStore,
    monkeypatch: pytest.MonkeyPatch,
    expired: bool,
    expected: type[Exception],
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(worker_module, "monotonic", lambda: clock[0])

    def fail(job: Job) -> None:
        try:
            job.connection.execute("SELECT * FROM absent_diagnostic_table").close()
        except sqlite3.OperationalError:
            if expired:
                clock[0] = job.deadline
            raise

    with pytest.raises(expected) as caught:
        await sqlite_store._worker.run(fail)
    assert type(caught.value) is expected
    assert "absent_diagnostic_table" not in str(caught.value)
    assert caught.value.__context__ is None
    assert not sqlite_store._worker.faulted.is_set()


@pytest.mark.parametrize("expired", [False, True])
async def test_worker_completion_is_fenced_at_deadline(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch, expired: bool
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(worker_module, "monotonic", lambda: clock[0])

    def complete(job: Job) -> int:
        clock[0] = job.deadline - (0.0 if expired else 0.001)
        return 7

    if expired:
        with pytest.raises(CacheTimeoutError):
            await sqlite_store._worker.run(complete)
    else:
        assert await sqlite_store._worker.run(complete) == 7


async def test_timeout_retains_worker_until_late_completion(
    sqlite_store: SQLiteStore,
) -> None:
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def work(job: Job) -> int:
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("Test did not release retained worker")
        return 7

    task = asyncio.create_task(sqlite_store._worker.run(work, budget_seconds=0.02))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(CacheTimeoutError):
            await task
        assert sqlite_store._worker.admitted == 1
        assert len(sqlite_store._worker.pending) == 1
        with pytest.raises(CacheBusyError):
            await sqlite_store.aclose()
    finally:
        release.set()
        async with asyncio.timeout(5):
            await asyncio.gather(
                *tuple(sqlite_store._worker.pending), return_exceptions=True
            )
    assert not sqlite_store._worker.pending
    assert sqlite_store._worker.admitted == 0
    assert sqlite_store._worker.current is None
    await sqlite_store.put(entry("usable after late completion"))


async def test_immediate_native_lock_refusal_is_not_timeout(
    sqlite_store: SQLiteStore,
) -> None:
    def fail(job: Job) -> None:
        job.connection.execute("PRAGMA busy_timeout=0").close()
        with pytest.raises(sqlite3.OperationalError) as caught:
            job.connection.execute("BEGIN IMMEDIATE").close()
        assert caught.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
        raise caught.value

    with connection(sqlite_store._config.path) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(CacheStoreError) as caught:
            await sqlite_store._worker.run(fail)
        assert type(caught.value) is CacheStoreError
        assert caught.value.__context__ is None
        blocker.execute("ROLLBACK")
    assert not sqlite_store._worker.faulted.is_set()
    await sqlite_store.put(entry("usable after immediate lock refusal"))


async def test_public_configured_write_deadline_keeps_aborted_state(
    sqlite_store: SQLiteStore,
) -> None:
    path = sqlite_store._config.path
    before = state(path)
    other = await SQLiteStore.connect(
        path,
        embedding_space=SPACE,
        default_ttl_seconds=None,
        operation_timeout_seconds=0.15,
    )
    try:
        with connection(path) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            with pytest.raises(CacheTimeoutError):
                await other.put(entry("public configured deadline"))
            blocker.execute("ROLLBACK")
        await drain_workers(other)
        assert not other._worker.faulted.is_set()
        assert state(path) == before
    finally:
        await drain_workers(other)
        await other.aclose()
    assert other._worker.connection is None


P = ParamSpec("P")
T = TypeVar("T")


async def test_completed_executor_job_retires_before_public_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CompletedExecutor(ThreadPoolExecutor):
        def submit(
            self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs
        ) -> Future[T]:
            future = super().submit(fn, *args, **kwargs)
            # Model a worker finishing before asyncio wraps the real concurrent future.
            future.result(timeout=5)
            return future

    stores: list[SQLiteStore] = []
    original = SQLiteStore.__init__

    def allocated(store: SQLiteStore, configuration: Configuration) -> None:
        original(store, configuration)
        stores.append(store)

    monkeypatch.setattr(worker_module, "ThreadPoolExecutor", CompletedExecutor)
    monkeypatch.setattr(SQLiteStore, "__init__", allocated)
    path = tmp_path / "already-completed.db"
    try:
        await SQLiteStore.initialize_schema(path, embedding_space=SPACE)
        assert stores[0]._worker.connection is None
        store = await SQLiteStore.connect(path, embedding_space=SPACE)
        assert not store._worker.pending
        assert store._worker.admitted == 0
        await store.put(entry("completed worker"))
        with pytest.raises(CacheStoreError):
            await store._worker.run(
                lambda job: job.rows("SELECT * FROM nonexistent_table")
            )
        assert not store._worker.pending
        assert store._worker.admitted == 0
        # Deliver any queued callbacks to expose duplicate admission/slot retirement.
        ready = asyncio.Event()
        asyncio.get_running_loop().call_soon(ready.set)
        await ready.wait()
        assert store._worker.admitted == 0
        assert store._worker.slot._value == 1
        await store.put(entry("later independent call"))
        await store.aclose()
        assert store._worker.connection is None
    finally:
        # The regression must also retire the baseline's inaccessible startup owner.
        for store in stores:
            await drain_workers(store)
            await store.aclose()
