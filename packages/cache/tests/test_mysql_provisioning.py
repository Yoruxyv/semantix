"""Real server DDL delay/ambiguity; ordinary cache deadlines stay unchanged."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import sha256
from time import monotonic
from typing import Any

import pytest

from examples.store_conformance import SPACE
from semantix_cache import CacheStoreError, CacheTimeoutError
from semantix_cache.stores._backends.mysql import schema
from semantix_cache.stores._backends.mysql.worker import Job, Worker
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import admin, admin_connection, new_database, options, settings
from .mysql_relay import Relay
from .test_mysql_lifecycle import observe, retired

pytestmark = pytest.mark.mysql


def _thread_id(job: Job) -> int:
    # The pinned driver's public method lacks a return annotation in its stubs.
    connection: Any = job.connection
    value = connection.thread_id()
    assert type(value) is int
    assert value > 0
    return int(value)


@asynccontextmanager
async def backup_lock() -> AsyncIterator[None]:
    """The fixture admin owns acquisition and release on one thread."""
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()

    def held() -> None:
        with admin_connection() as connection, connection.cursor() as cursor:
            cursor.execute("LOCK INSTANCE FOR BACKUP")
            try:
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(10), "Test did not release its backup lock"
            finally:
                cursor.execute("UNLOCK INSTANCE")

    task = asyncio.create_task(asyncio.to_thread(held))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        yield
    finally:
        release.set()
        await task


async def ddl_waiting(connection_id: int, statement: str, minimum_ms: int) -> None:
    deadline = monotonic() + 3
    while True:
        rows = await asyncio.to_thread(
            admin,
            "SELECT e.TIMER_WAIT FROM performance_schema.events_statements_current e JOIN performance_schema.threads t USING(THREAD_ID) WHERE t.PROCESSLIST_ID=%s AND e.EVENT_NAME='statement/sql/create_table' AND SHA2(e.SQL_TEXT,256)=%s AND EXISTS (SELECT 1 FROM performance_schema.metadata_locks l WHERE l.OWNER_THREAD_ID=e.THREAD_ID AND l.LOCK_STATUS='PENDING')",
            (connection_id, sha256(statement.encode()).hexdigest()),
        )
        if rows and rows[0][0] >= minimum_ms * 1000000000:
            return
        assert monotonic() < deadline, "Expected real pending DDL was not observed"
        await asyncio.sleep(0.005)


@pytest.mark.parametrize("stage", [0, 1])
async def test_setup_accepts_delayed_server_ddl_acknowledgement(
    monkeypatch: pytest.MonkeyPatch, stage: int
) -> None:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE}
    statement = schema.STATEMENTS[stage]
    reached = asyncio.Event()
    dispatch = threading.Event()
    connection_ids: list[int] = []
    original = Job.rows
    loop = asyncio.get_running_loop()

    def rows(job: Job, sql: str, parameters: Any = ()) -> Any:
        if sql == statement:
            connection_ids.append(_thread_id(job))
            loop.call_soon_threadsafe(reached.set)
            assert dispatch.wait(5), "Test did not dispatch its CREATE"
        return original(job, sql, parameters)

    monkeypatch.setattr(Job, "rows", rows)
    task = asyncio.create_task(MySQLStore.initialize_schema(**config))
    try:
        await asyncio.wait_for(reached.wait(), 3)
        async with backup_lock():
            dispatch.set()
            # The real server's statement timer and pending metadata lock are
            # the barrier, rather than an arbitrary sleep before release.
            await ddl_waiting(connection_ids[0], statement, 600)
            assert not task.done(), "The old 0.5-second bound preempted valid DDL"
        await task
        assert len(connection_ids) == 1
        assert await asyncio.to_thread(
            admin,
            "SELECT version,state FROM semantix_schema_migrations ORDER BY version",
            name=name,
        ) == [(1, b"READY"), (2, b"READY")]
        async with await MySQLStore.connect(**config) as store:
            assert await store.find_nearest((1, 0), namespace="default") is None
    finally:
        dispatch.set()
        await asyncio.gather(task, return_exceptions=True)


@asynccontextmanager
async def paused_setup(
    monkeypatch: pytest.MonkeyPatch,
    stage: int,
    *,
    budget: float = 30,
    relay_port: int | None = None,
) -> AsyncIterator[
    tuple[
        asyncio.Task[None],
        dict[str, Any],
        int,
        threading.Event,
        list[Worker],
        list[int],
    ]
]:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE}
    started = asyncio.Event()
    dispatch = threading.Event()
    loop = asyncio.get_running_loop()
    ids: list[int] = []
    workers = observe(monkeypatch)
    original = Job.rows

    def rows(job: Job, sql: str, parameters: Any = ()) -> Any:
        if sql == schema.STATEMENTS[stage]:
            ids.append(_thread_id(job))
            loop.call_soon_threadsafe(started.set)
            assert dispatch.wait(5), "Test did not dispatch its CREATE"
        return original(job, sql, parameters)

    monkeypatch.setattr(Job, "rows", rows)
    actual = config | {"operation_timeout_seconds": budget}
    if relay_port is not None:
        actual["port"] = relay_port
    task = asyncio.create_task(MySQLStore.initialize_schema(**actual))
    try:
        await asyncio.wait_for(started.wait(), 3)
        yield task, config, ids[0], dispatch, workers, ids
    finally:
        dispatch.set()
        await asyncio.gather(task, return_exceptions=True)


async def table_exists(name: str, table: str) -> None:
    deadline = monotonic() + 3
    while True:
        if await asyncio.to_thread(
            admin,
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
            (name, table),
        ) == [(1,)]:
            return
        assert monotonic() < deadline, "The server did not execute the target CREATE"
        await asyncio.sleep(0.005)


@pytest.mark.parametrize("stage", [0, 1])
async def test_setup_server_lock_timeout_before_execution_has_no_replay(
    monkeypatch: pytest.MonkeyPatch, stage: int
) -> None:
    async with paused_setup(monkeypatch, stage) as (
        task,
        config,
        connection_id,
        dispatch,
        workers,
        ids,
    ):
        async with backup_lock():
            dispatch.set()
            await ddl_waiting(connection_id, schema.STATEMENTS[stage], 0)
            with pytest.raises(CacheTimeoutError) as error:
                await task
            assert error.value.__context__ is None
        assert len(ids) == 1
        assert await asyncio.to_thread(
            admin,
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
            (config["database"], schema.STATEMENTS[stage].split()[2]),
        ) == [(0,)]
        retired(workers[0])
        if stage == 1:
            assert await asyncio.to_thread(
                admin,
                "SELECT state FROM semantix_schema_migrations",
                name=config["database"],
            ) == [(b"INITIALIZING",)]
            with pytest.raises(CacheStoreError):
                await MySQLStore.initialize_schema(**config)
            assert len(ids) == 1


@pytest.mark.parametrize("stage", [0, 1])
async def test_setup_lost_ack_after_observed_execution_preserves_partial_schema(
    monkeypatch: pytest.MonkeyPatch, stage: int
) -> None:
    fixture = settings()
    relay = Relay((fixture["address"], fixture["port"]))
    try:
        async with paused_setup(monkeypatch, stage, relay_port=relay.port) as (
            task,
            config,
            _connection_id,
            dispatch,
            workers,
            ids,
        ):
            relay.block_downstream.set()
            dispatch.set()
            await table_exists(config["database"], schema.STATEMENTS[stage].split()[2])
            assert not task.done(), "DDL execution must be observed before timeout"
            with pytest.raises(CacheTimeoutError) as error:
                await task
            assert error.value.__context__ is None
            assert relay.upstream_after_block.is_set()
            retired(workers[0])
            expected = [] if stage == 0 else [(1, b"INITIALIZING")]
            assert (
                await asyncio.to_thread(
                    admin,
                    "SELECT version,state FROM semantix_schema_migrations ORDER BY version",
                    name=config["database"],
                )
                == expected
            )
            for operation in (MySQLStore.initialize_schema, MySQLStore.connect):
                with pytest.raises(CacheStoreError):
                    await operation(**config)
            assert len(ids) == 1
            for worker in workers:
                retired(worker)
    finally:
        await asyncio.to_thread(relay.close)


@pytest.mark.parametrize("stop", ["cancel", "deadline", "failed_interrupt"])
async def test_setup_blocked_io_cancellation_and_deadline_retire_owner(
    monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    budget = 0.6 if stop == "deadline" else 30
    async with paused_setup(monkeypatch, 1, budget=budget) as (
        task,
        config,
        connection_id,
        dispatch,
        workers,
        ids,
    ):
        worker = workers[0]
        async with backup_lock():
            dispatch.set()
            await ddl_waiting(connection_id, schema.STATEMENTS[1], 0)
            if stop == "failed_interrupt":
                assert worker.duplicate is not None

                def refused(how: int) -> None:
                    raise OSError("deliberate-interrupt-refusal")

                monkeypatch.setattr(worker.duplicate, "shutdown", refused)
            began = monotonic()
            if stop == "deadline":
                with pytest.raises(CacheTimeoutError):
                    await task
            else:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert monotonic() - began < 2.5
            retired(worker)
            assert worker.interrupt_failed == (stop == "failed_interrupt")
            # Keep the server lock until its abandoned statement has also ended.
            deadline = monotonic() + 3
            while await asyncio.to_thread(
                admin,
                "SELECT COUNT(*) FROM performance_schema.threads WHERE PROCESSLIST_ID=%s",
                (connection_id,),
            ) != [(0,)]:
                assert monotonic() < deadline, "Abandoned DDL did not leave the server"
                await asyncio.sleep(0.005)
        assert len(ids) == 1
        assert await asyncio.to_thread(
            admin,
            "SELECT state FROM semantix_schema_migrations",
            name=config["database"],
        ) == [(b"INITIALIZING",)]
        with pytest.raises(CacheStoreError):
            await MySQLStore.connect(**config)


async def test_runtime_read_stall_budget_is_unchanged() -> None:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE}
    await MySQLStore.initialize_schema(**config)
    async with await MySQLStore.connect(**config) as store:
        began = monotonic()
        with pytest.raises(CacheTimeoutError):
            await store._worker.run(
                lambda job: job.rows("SELECT SLEEP(1)"),
                readonly=True,
                budget_seconds=5,
            )
        assert 0.4 <= monotonic() - began < 1
        assert await store.find_nearest((1, 0), namespace="default") is None
