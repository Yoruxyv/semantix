"""Real lock waits, deadlocks, atomic failure paths and paginated snapshot races."""

import asyncio
import threading
from typing import Any

import numpy as np
import pymysql
import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache import CacheStoreError, CacheTimeoutError
from semantix_cache._semantics import nearest_index, normalized_vector
from semantix_cache.stores._backends.mysql import database
from semantix_cache.stores._backends.mysql.worker import Job
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import admin, admin_connection, new_database, options
from .test_mysql import mysql_store
from .test_mysql_faults import until

__all__ = ["mysql_store"]
pytestmark = pytest.mark.mysql


def persisted(name: str) -> list[list[tuple[Any, ...]]]:
    return [
        admin("SELECT * FROM " + table + " ORDER BY 1,2", name=name)  # noqa: S608 -- fixed table allowlist
        for table in ("semantix_bindings", "semantix_entries", "semantix_payloads")
    ]


@pytest.mark.parametrize(
    ("operation", "point"),
    [
        ("put", "INSERT INTO semantix_entries"),
        ("put", "INSERT INTO semantix_payloads"),
        ("put", "UPDATE semantix_bindings"),
        ("put", "SELECT count(*) FROM semantix_entries"),
        ("hit", "UPDATE semantix_entries SET hit_count"),
        ("hit", "UPDATE semantix_bindings SET access_counter"),
        ("delete", "DELETE FROM semantix_entries"),
        ("clear", "DELETE FROM semantix_entries"),
    ],
)
async def test_business_failure_rolls_back_without_replay(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch, operation: str, point: str
) -> None:
    value = entry("original")
    await mysql_store.put(value)
    match = await mysql_store.find_nearest((1, 0), namespace="default")
    assert match
    name = mysql_store._config.database
    before = await asyncio.to_thread(persisted, name)
    original = Job.rows
    fired: list[int] = []

    def rows(job: Job, sql: str, parameters: Any = ()) -> Any:
        result = original(job, sql, parameters)
        if sql.startswith(point) and not fired:
            fired.append(1)
            raise pymysql.OperationalError(
                2013, "private-response-sql-credential-marker"
            )
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", rows)

        async def mutate() -> None:
            if operation == "put":
                await mysql_store.put(entry("replacement"))
            elif operation == "hit":
                await mysql_store.record_hit(
                    value.cache_key,
                    namespace="default",
                    expected_created_at=match.entry.created_at,
                )
            elif operation == "delete":
                await mysql_store.delete_entry(value.cache_key, namespace="default")
            else:
                await mysql_store.clear(namespace="default")

        with pytest.raises(CacheStoreError) as caught:
            await mutate()
    assert fired == [1]
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert "private-" not in str(caught.value)
    assert mysql_store._worker.faulted.is_set()
    assert mysql_store._worker.connection is None
    assert await asyncio.to_thread(persisted, name) == before


async def test_failed_rollback_retains_terminal_owned_connection(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = mysql_store._worker
    owner = worker.thread
    attempts = []

    def rollback(connection: Any) -> None:
        attempts.append(threading.current_thread())
        raise RuntimeError("private-rollback-marker")

    def action(job: Job) -> None:
        with job.transaction(write=True):
            job.rows("UPDATE semantix_bindings SET access_counter=1")
            raise ValueError("private-data-marker")

    with monkeypatch.context() as patch:
        patch.setattr(pymysql.Connection, "rollback", rollback)
        with pytest.raises(CacheStoreError) as caught:
            await worker.run(action)
    assert attempts == [owner]
    assert caught.value.__context__ is None
    assert "private" not in str(caught.value)
    assert worker.faulted.is_set()
    assert worker.last_failure is not None
    assert worker.connection is not None
    await mysql_store.aclose()
    assert owner is not None
    assert not owner.is_alive()
    assert await asyncio.to_thread(
        admin,
        "SELECT access_counter FROM semantix_bindings",
        name=mysql_store._config.database,
    ) == [(0,)]


async def test_socket_read_timeout_is_typed_and_read_session_recovers(
    mysql_store: MySQLStore,
) -> None:
    worker = mysql_store._worker
    with pytest.raises(CacheTimeoutError):
        await worker.run(lambda job: job.rows("SELECT SLEEP(2)"), readonly=True)
    assert not worker.faulted.is_set()
    assert worker.connection is None
    assert await mysql_store.find_nearest((1, 0), namespace="default") is None


async def test_real_lock_wait_is_bounded_and_mutation_is_not_retried(
    mysql_store: MySQLStore,
) -> None:
    name = mysql_store._config.database
    held, release = threading.Event(), threading.Event()

    def hold() -> None:
        with admin_connection(name) as connection, connection.cursor() as cursor:
            connection.begin()
            cursor.execute("SELECT binding_id FROM semantix_bindings FOR UPDATE", ())
            held.set()
            assert release.wait(5)
            connection.rollback()

    holder = asyncio.create_task(asyncio.to_thread(hold))
    task = None
    try:
        await until(held.is_set)
        task = asyncio.create_task(mysql_store.put(entry("blocked")))
        observed = False
        for _ in range(30):
            waits = await asyncio.to_thread(
                admin, "SELECT count(*) FROM performance_schema.data_lock_waits"
            )
            if waits[0][0] > 0:
                observed = True
                break
            await asyncio.sleep(0.005)
        assert observed, "Must observe a real InnoDB lock wait"
        with pytest.raises(CacheTimeoutError):
            await task
        assert mysql_store._worker.faulted.is_set()
    finally:
        release.set()
        await holder
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
    assert await asyncio.to_thread(
        admin, "SELECT count(*) FROM semantix_entries", name=name
    ) == [(0,)]


async def test_real_deadlock_rolls_back_adapter_and_faults_without_retry(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    for number in range(20):
        await mysql_store.put(entry(str(number)))
    name = mysql_store._config.database
    before = await asyncio.to_thread(persisted, name)
    held, release, cycle = threading.Event(), threading.Event(), threading.Event()
    codes = []
    original = Job.rows

    def rows(job: Job, sql: str, parameters: Any = ()) -> Any:
        try:
            return original(job, sql, parameters)
        except pymysql.OperationalError as error:
            codes.append(error.args[0])
            raise

    def hold() -> None:
        with admin_connection(name) as connection, connection.cursor() as cursor:
            connection.begin()
            cursor.execute(
                "UPDATE semantix_entries SET hit_count=hit_count+1,last_accessed_at_us=0",
                (),
            )
            held.set()
            assert cycle.wait(5)
            cursor.execute("SELECT binding_id FROM semantix_bindings FOR UPDATE", ())
            release.set()
            connection.rollback()

    holder = asyncio.create_task(asyncio.to_thread(hold))
    task = None
    try:
        await until(held.is_set)
        monkeypatch.setattr(Job, "rows", rows)
        task = asyncio.create_task(mysql_store.put(entry("deadlock victim")))
        observed = False
        for _ in range(30):
            if (
                await asyncio.to_thread(
                    admin, "SELECT count(*) FROM performance_schema.data_lock_waits"
                )
            )[0][0]:
                observed = True
                break
            await asyncio.sleep(0.005)
        assert observed
        cycle.set()
        with pytest.raises(CacheStoreError):
            await task
        assert codes == [1213]
        assert mysql_store._worker.faulted.is_set()
    finally:
        cycle.set()
        await holder
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
    assert release.is_set()
    assert await asyncio.to_thread(persisted, name) == before


async def test_keyset_pages_share_one_complete_snapshot(
    mysql_store: MySQLStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = await new_database()
    config = options(name) | {
        "embedding_space": SPACE,
        "max_size": 200,
        "default_ttl_seconds": None,
    }
    await MySQLStore.initialize_schema(**config)
    first = await MySQLStore.connect(**config)
    second = await MySQLStore.connect(**config)
    for number in range(130):
        await first.put(entry(str(number), vector=(1, number / 1000)))
    entered, release = threading.Event(), threading.Event()
    original_rows, original_nearest = Job.rows, nearest_index
    pages, scored = [], []

    def rows(job: Job, sql: str, parameters: Any = ()) -> Any:
        result = original_rows(job, sql, parameters)
        if job.owner is first._worker and sql.startswith(
            "SELECT cache_key,revision_us,vector_blob"
        ):
            pages.append(len(result))
            if len(pages) == 1:
                entered.set()
                assert release.wait(5)
        return result

    def nearest(query: Any, matrix: Any) -> Any:
        scored.append(np.array(matrix, copy=True))
        return original_nearest(query, matrix)

    monkeypatch.setattr(Job, "rows", rows)
    monkeypatch.setattr(database, "nearest_index", nearest)
    task = asyncio.create_task(first.find_nearest((1, 0), namespace="default"))
    try:
        await until(entered.is_set)
        assert await second.delete_entry(entry("129").cache_key, namespace="default")
        await second.put(entry("newer", vector=(0, 1)))
        release.set()
        match = await task
        assert match is not None
        assert match.entry.prompt == "0"
        assert pages == [64, 64, 2, 0]
        assert len(scored) == 1
        assert scored[0].shape == (130, 2)
        expected = np.array(
            [
                normalized_vector((1, number / 1000), dimensions=2)
                for number in range(130)
            ]
        )
        np.testing.assert_array_equal(scored[0], expected)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await first.aclose()
        await second.aclose()
