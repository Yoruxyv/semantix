"""Real transport/transaction boundaries and retained ownership under failures."""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
from dataclasses import replace
from typing import Any

import pymysql
import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache import (
    CacheBusyError,
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
)
from semantix_cache.stores._backends.mysql.worker import Job, Worker
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import (
    admin,
    block_lookup,
    new_database,
    options,
    settings,
    store_factory,
)
from .mysql_relay import Relay
from .test_mysql import mysql_store

__all__ = ["mysql_store", "store_factory"]
pytestmark = pytest.mark.mysql


async def until(predicate: Any, budget: float = 3.0) -> None:
    deadline = time.monotonic() + budget
    while not predicate():
        assert time.monotonic() < deadline, "Owned operation did not finish"
        await asyncio.sleep(0.01)


async def test_read_io_cancellation_and_timeout_recover(
    mysql_store: MySQLStore,
) -> None:
    worker = mysql_store._worker
    loop = asyncio.get_running_loop()
    original_id = await worker.run(
        lambda job: job.rows("SELECT CONNECTION_ID()"), readonly=True
    )
    for cancel in (True, False):
        entered = asyncio.Event()

        def action(job: Job, entered: asyncio.Event = entered) -> None:
            with job.transaction():
                loop.call_soon_threadsafe(entered.set)
                job.rows("SELECT SLEEP(1)")

        task = asyncio.create_task(
            worker.run(action, readonly=True, budget_seconds=0.1 if not cancel else 5)
        )
        await asyncio.wait_for(entered.wait(), 2)
        if cancel:
            observed = False
            for _ in range(30):
                active = await asyncio.to_thread(
                    admin,
                    "SELECT count(*) FROM information_schema.PROCESSLIST WHERE ID=%s AND INFO='SELECT SLEEP(1)'",
                    (original_id[0][0],),
                )
                if active == [(1,)]:
                    observed = True
                    break
                await asyncio.sleep(0.005)
            assert observed, "Cancellation must interrupt actual server-observed I/O"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(CacheTimeoutError):
                await task
        if worker.pending:
            assert worker.admitted == 1
            with pytest.raises(CacheBusyError):
                await mysql_store.aclose()
        else:
            assert worker.admitted == 0
            assert worker.connection is None
        assert await mysql_store.find_nearest((1, 0), namespace="default") is None
        current_id = await worker.run(
            lambda job: job.rows("SELECT CONNECTION_ID()"), readonly=True
        )
        assert current_id != original_id
        original_id = current_id
        assert not worker.faulted.is_set()


async def test_cancelled_read_never_replayed_and_late_stop_cannot_touch_new_session(
    mysql_store: MySQLStore,
) -> None:
    worker = mysql_store._worker
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    jobs = []

    def action(job: Job) -> None:
        jobs.append(job)
        job.rows("SELECT 1")
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(3)

    task = asyncio.create_task(worker.run(action, readonly=True))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert worker.pending
        assert worker.admitted == 1
        with pytest.raises(CacheBusyError):
            await mysql_store.aclose()
        release.set()
        assert await mysql_store.find_nearest((1, 0), namespace="default") is None
        worker.interrupt(jobs[0])
        assert await mysql_store.find_nearest((1, 0), namespace="default") is None
        assert len(jobs) == 1
    finally:
        release.set()
        await until(lambda: not worker.pending)


async def test_revalidation_failure_is_terminal(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = mysql_store._worker
    await worker.run(lambda job: worker.retire(), readonly=True)
    called = []

    def invalid(job: Job) -> None:
        called.append("validate")
        raise CacheStoreError("MySQL replacement session validation failed")

    monkeypatch.setattr(worker, "revalidate", invalid)
    with pytest.raises(CacheStoreError):
        await mysql_store.find_nearest((1, 0), namespace="default")
    assert worker.faulted.is_set()
    assert worker.connection is None
    with pytest.raises(CacheStoreError):
        await mysql_store.find_nearest((1, 0), namespace="default")
    assert called == ["validate"]


async def test_cancel_before_commit_has_no_committed_mutation(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = mysql_store._worker
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    original_rows, original_commit = Job.rows, pymysql.Connection.commit
    commits = []

    def rows(job: Job, sql: str, parameters: Any = ()) -> Any:
        result = original_rows(job, sql, parameters)
        if sql == "SELECT count(*) FROM semantix_entries WHERE binding_id=%s":
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(3)
        return result

    def commit(connection: Any) -> None:
        commits.append(1)
        original_commit(connection)

    monkeypatch.setattr(Job, "rows", rows)
    monkeypatch.setattr(pymysql.Connection, "commit", commit)
    task = asyncio.create_task(mysql_store.put(entry("cancel before commit")))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await until(lambda: not worker.pending)
        assert commits == []
        assert worker.faulted.is_set()
        persisted = await asyncio.to_thread(
            admin,
            "SELECT count(*) FROM semantix_entries",
            name=mysql_store._config.database,
        )
        assert persisted == [(0,)]
    finally:
        release.set()
        await until(lambda: not worker.pending)


@pytest.mark.parametrize("operation", ["put", "clear_all"])
async def test_actual_commit_acknowledgement_loss_is_terminal(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None}
    await MySQLStore.initialize_schema(**config)
    fixture = settings()
    relay = Relay((fixture["address"], fixture["port"]))
    store = await MySQLStore.connect(**(config | {"port": relay.port}))
    value = entry("lost acknowledgement")
    if operation == "clear_all":
        await store.put(value)
    original = pymysql.Connection.commit
    dispatches = []

    def commit(connection: Any) -> None:
        dispatches.append(1)
        relay.block_downstream.set()
        original(connection)

    monkeypatch.setattr(pymysql.Connection, "commit", commit)
    task = asyncio.create_task(
        store.put(value) if operation == "put" else store.clear_all()
    )
    try:
        await until(relay.upstream_after_block.is_set)
        with pytest.raises(CacheTimeoutError):
            await task
        assert relay.downstream_blocked.is_set()
        assert dispatches == [1]
        assert store._worker.faulted.is_set()
        rows = await asyncio.to_thread(
            admin, "SELECT cache_key FROM semantix_entries", name=name
        )
        assert rows == (
            [(value.cache_key.encode("ascii"),)] if operation == "put" else []
        )
        retry = store.put(value) if operation == "put" else store.clear_all()
        with pytest.raises(CacheStoreError):
            await retry
        assert dispatches == [1]
    finally:
        await asyncio.gather(task, return_exceptions=True)
        await store.aclose()
        await asyncio.to_thread(relay.close)


@pytest.mark.parametrize("operation", ["put", "clear_all"])
async def test_cancel_after_commit_dispatch_preserves_uncertainty(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None}
    await MySQLStore.initialize_schema(**config)
    fixture = settings()
    relay = Relay((fixture["address"], fixture["port"]))
    store = await MySQLStore.connect(**(config | {"port": relay.port}))
    value = entry("cancel after dispatch")
    if operation == "clear_all":
        await store.put(value)
    original = pymysql.Connection.commit
    dispatches = []

    def commit(connection: Any) -> None:
        dispatches.append(1)
        relay.block_downstream.set()
        original(connection)

    monkeypatch.setattr(pymysql.Connection, "commit", commit)
    task = asyncio.create_task(
        store.put(value) if operation == "put" else store.clear_all()
    )
    try:
        await until(relay.upstream_after_block.is_set)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await until(lambda: not store._worker.pending)
        assert dispatches == [1]
        assert store._worker.faulted.is_set()
        rows = await asyncio.to_thread(
            admin, "SELECT cache_key FROM semantix_entries", name=name
        )
        assert rows == (
            [(value.cache_key.encode("ascii"),)] if operation == "put" else []
        )
    finally:
        await asyncio.gather(task, return_exceptions=True)
        await store.aclose()
        await asyncio.to_thread(relay.close)


async def test_close_cancellation_and_timeout_keep_shared_cleanup(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = mysql_store._worker
    worker.config = replace(worker.config, close_timeout=0.05)
    entered, release = threading.Event(), threading.Event()
    original = worker.retire
    threads = []

    def close() -> None:
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        original()

    monkeypatch.setattr(worker, "retire", close)
    first = asyncio.create_task(mysql_store.aclose())
    try:
        await until(entered.is_set)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        cleanup = worker.cleanup
        with pytest.raises(CacheTimeoutError):
            await mysql_store.aclose()
        assert cleanup is worker.cleanup
        assert cleanup is not None
        assert not cleanup.done()
        release.set()
        await until(cleanup.done)
        await mysql_store.aclose()
        assert len(threads) == 1
        assert worker.thread is not None
        assert not worker.thread.is_alive()
    finally:
        release.set()
        await until(lambda: worker.cleanup is not None and worker.cleanup.done())


async def test_read_cleanup_failure_never_recovers(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = mysql_store._worker
    original = worker.retire
    failures = []

    def broken() -> None:
        original()
        failures.append(1)
        raise OSError("synthetic-private-cleanup-marker")

    with monkeypatch.context() as patch:
        patch.setattr(worker, "retire", broken)
        with pytest.raises(CacheTimeoutError):
            await worker.run(
                lambda job: job.rows("SELECT SLEEP(1)"),
                readonly=True,
                budget_seconds=0.05,
            )
        await until(lambda: not worker.pending)
        assert worker.faulted.is_set()
        assert failures == [1]
    with pytest.raises(CacheStoreError) as caught:
        await mysql_store.find_nearest((1, 0), namespace="default")
    assert "synthetic-private-cleanup-marker" not in "".join(
        traceback.format_exception(caught.value)
    )


async def test_partial_startup_shutdown_observes_thread() -> None:
    name = await new_database()
    configuration = MySQLStore._configuration(
        address=options(name)["address"],
        port=options(name)["port"],
        tls_hostname=options(name)["tls_hostname"],
        ca_file=options(name)["ca_file"],
        user=options(name)["user"],
        password=options(name)["password"],
        database=name,
        space=SPACE,
        capacity=32,
        ttl=None,
        operation_timeout=5.0,
        close_timeout=5.0,
    )
    worker = Worker(configuration)
    with pytest.raises(CacheTimeoutError):
        await worker.run(lambda job: None, readonly=True, budget_seconds=1e-300)
    await worker.close()
    assert worker.thread is not None
    assert not worker.thread.is_alive()


async def test_failed_close_retains_owner_until_explicit_disposal_retry(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = mysql_store._worker
    owner = worker.thread
    original = pymysql.Connection.close
    attempts = []

    def fail(connection: Any) -> None:
        attempts.append(threading.current_thread())
        raise OSError("private-close-failure")

    with monkeypatch.context() as patch:
        patch.setattr(pymysql.Connection, "close", fail)
        with pytest.raises(CacheStoreError) as caught:
            await mysql_store.aclose()
        assert caught.value.__context__ is None
        assert "private-close-failure" not in str(caught.value)
        assert worker.faulted.is_set()
        assert worker.last_failure is not None
        assert worker.connection is not None
        assert worker.connection.open
        assert worker.duplicate is not None
        assert owner is not None
        assert owner.is_alive()
        assert attempts == [owner]
    assert pymysql.Connection.close is original
    await mysql_store.aclose()
    assert worker.connection is None
    assert worker.duplicate is None
    assert not owner.is_alive()


async def test_cancelled_cpu_work_retains_bounded_admission(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await mysql_store.put(entry("numeric"))
    worker = mysql_store._worker
    async with block_lookup(mysql_store, monkeypatch) as entered:
        task = asyncio.create_task(
            mysql_store.find_nearest((1, 0), namespace="default")
        )
        await asyncio.wait_for(entered.wait(), 3)
        old = worker.current
        assert old is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert worker.admitted == 1
        assert len(worker.pending) == 1
        waiters = [
            asyncio.create_task(mysql_store.clear(namespace="other")) for _ in range(31)
        ]
        await asyncio.sleep(0)
        assert worker.admitted == 32
        with pytest.raises(CacheStoreError, match="admission"):
            await mysql_store.clear(namespace="other")
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        assert worker.admitted == 1
        assert not worker.faulted.is_set()
    async with block_lookup(mysql_store, monkeypatch) as entered:
        next_task = asyncio.create_task(
            mysql_store.find_nearest((1, 0), namespace="default")
        )
        await asyncio.wait_for(entered.wait(), 3)
        assert worker.current is not old
        worker.interrupt(old)
    assert await next_task is not None


async def test_wrong_loop_rejected_before_database_io(mysql_store: MySQLStore) -> None:
    async def other_loop() -> None:
        with pytest.raises(
            CacheConfigurationError, match="creating process and event loop"
        ):
            await mysql_store.find_nearest((1, 0), namespace="default")

    await asyncio.to_thread(asyncio.run, other_loop())
    assert await mysql_store.find_nearest((1, 0), namespace="default") is None
