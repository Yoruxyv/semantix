"""Explicit non-atomic DDL refusal, runtime grants and partial-startup ownership."""

import asyncio
import threading
import traceback
from typing import Any

import pymysql
import pytest

from examples.store_conformance import SPACE, StoreFactory
from semantix_cache import CacheStoreError, CacheTimeoutError
from semantix_cache.stores import _mysql_schema as schema
from semantix_cache.stores._mysql_worker import Job
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import admin, new_database, options, settings, store_factory
from .mysql_relay import Relay
from .test_mysql_faults import until
from .test_mysql_lifecycle import observe, retired

__all__ = ["store_factory"]
pytestmark = pytest.mark.mysql


@pytest.mark.parametrize("stage", range(4))
async def test_failure_after_each_ddl_preserves_incomplete_schema(
    monkeypatch: pytest.MonkeyPatch, stage: int
) -> None:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None}
    original = Job.rows
    fired = []

    def rows(job: Job, sql: str, parameters: Any = ()) -> Any:
        result = original(job, sql, parameters)
        if sql == schema.STATEMENTS[stage]:
            fired.append(job.owner)
            raise pymysql.OperationalError(2013, "private-partial-ddl-marker")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)
        with pytest.raises(CacheStoreError):
            await MySQLStore.initialize_schema(**config)
    assert len(fired) == 1
    assert fired[0].thread is not None
    assert not fired[0].thread.is_alive()
    before = await asyncio.to_thread(admin, "SHOW TABLES", name=name)
    assert len(before) == stage + 1
    for operation in (MySQLStore.connect, MySQLStore.initialize_schema):
        with pytest.raises(CacheStoreError):
            await operation(**config)
    assert await asyncio.to_thread(admin, "SHOW TABLES", name=name) == before


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM semantix_bindings",
        "UPDATE semantix_schema_migrations SET state='READY'",
        "DROP TABLE semantix_payloads",
        "CREATE TABLE app_data(value INT)",
        "INSERT INTO semantix_bindings SELECT * FROM semantix_bindings",
    ],
)
async def test_runtime_user_cannot_change_schema_or_revision_ledger(
    store_factory: StoreFactory, sql: str
) -> None:
    case = await store_factory()
    store = case.store
    assert isinstance(store, MySQLStore)
    with pytest.raises(CacheStoreError):
        await store._worker.run(lambda job: job.rows(sql))
    assert store._worker.faulted.is_set()
    assert (
        len(await asyncio.to_thread(admin, "SHOW TABLES", name=store._config.database))
        == 4
    )
    assert await asyncio.to_thread(
        admin, "SELECT count(*) FROM semantix_bindings", name=store._config.database
    ) == [(1,)]


async def test_cancellation_during_authenticated_startup_retains_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None}
    await MySQLStore.initialize_schema(**config)
    entered, release = threading.Event(), threading.Event()
    original = Job.rows
    workers = []

    def rows(job: Job, sql: str, parameters: Any = ()) -> Any:
        result = original(job, sql, parameters)
        if sql.startswith("SELECT @@version,"):
            workers.append(job.owner)
            entered.set()
            assert release.wait(5)
        return result

    monkeypatch.setattr(Job, "rows", rows)
    task = asyncio.create_task(MySQLStore.connect(**config))
    try:
        await until(entered.is_set)
        worker = workers[0]
        task.cancel()
        await until(lambda: worker.cleanup is not None)
        assert worker.pending
        assert worker.admitted == 1
        assert worker.cleanup is not None
        assert not worker.cleanup.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert worker.thread is not None
        assert not worker.thread.is_alive()
        assert worker.connection is None
        assert worker.duplicate is None
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("stage", ["table", "verifier"])
async def test_startup_io_timeout_is_not_replaced_by_closed_connection_cleanup(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    name = await new_database()
    config = options(name) | {"embedding_space": SPACE, "default_ttl_seconds": None}
    fixture = settings()
    relay = Relay((fixture["address"], fixture["port"]))
    workers = observe(monkeypatch)
    statement = schema.STATEMENTS[1] if stage == "table" else schema.VERIFIER_SQL
    original = pymysql.cursors.Cursor.execute
    dispatches = []

    def execute(cursor: Any, sql: str, args: Any = None) -> Any:
        if sql == statement:
            dispatches.append(1)
            relay.block_downstream.set()
        return original(cursor, sql, args)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(pymysql.cursors.Cursor, "execute", execute)
            with pytest.raises(CacheTimeoutError) as caught:
                await MySQLStore.initialize_schema(**(config | {"port": relay.port}))
        assert dispatches == [1]
        assert relay.upstream_after_block.is_set()
        assert caught.value.__context__ is None
        formatted = "".join(traceback.format_exception(caught.value))
        assert fixture["password"] not in formatted
        assert "CREATE TABLE semantix_bindings" not in formatted
        retired(workers[0])
        expected = [(1, b"INITIALIZING")]
        if stage == "verifier":
            expected.append((2, b"INITIALIZING"))
        assert (
            await asyncio.to_thread(
                admin,
                "SELECT version,state FROM semantix_schema_migrations ORDER BY version",
                name=name,
            )
            == expected
        )
        before = await asyncio.to_thread(admin, "SHOW TABLES", name=name)
        for operation in (MySQLStore.connect, MySQLStore.initialize_schema):
            with pytest.raises(CacheStoreError):
                await operation(**config)
        assert await asyncio.to_thread(admin, "SHOW TABLES", name=name) == before
        assert dispatches == [1]
        for worker in workers:
            retired(worker)
    finally:
        await asyncio.to_thread(relay.close)
