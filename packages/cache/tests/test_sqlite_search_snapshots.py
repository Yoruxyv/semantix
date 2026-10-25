"""Warm SQLite snapshots remain derived, bounded and transaction-qualified."""

import asyncio
import gc
import threading
import weakref
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
from numpy.typing import NDArray

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache import (
    CacheBusyError,
    CacheMatch,
    CacheStoreError,
    CacheTimeoutError,
)
from semantix_cache.stores._backends.sqlite import database
from semantix_cache.stores._backends.sqlite.format import decode_vector, vector_blob
from semantix_cache.stores._backends.sqlite.worker import Job, Row, Worker
from semantix_cache.stores.sqlite import SQLiteStore

from . import sqlite_helpers
from .sqlite_helpers import block_lookup, connection, drain_workers
from .test_sqlite_processes import receive, spawn, stop

sqlite_store = sqlite_helpers.sqlite_store


async def test_reuse_preserves_confirmation_and_avoids_vector_redecode(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sqlite_store.put(entry("first"))
    await sqlite_store.put(entry("second", vector=(0, 1)))
    calls = 0
    original = decode_vector

    def decode(blob: bytes, dimensions: int) -> NDArray[np.float64]:
        nonlocal calls
        calls += 1
        return original(blob, dimensions)

    monkeypatch.setattr(database, "decode_vector", decode)
    match = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert match is not None
    assert match.entry.prompt == "first"
    snapshot = sqlite_store._database._snapshot
    assert snapshot is not None
    assert calls == 2
    assert snapshot.matrix.dtype == np.float64
    assert snapshot.matrix.flags.c_contiguous
    assert snapshot.matrix.flags.owndata
    assert not snapshot.matrix.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        snapshot.matrix[0, 0] = 0
    for _ in range(4):
        assert await sqlite_store.find_nearest((1, 0), namespace="default") == match
        assert await sqlite_store.record_hit(
            match.entry.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
        assert sqlite_store._database._snapshot is snapshot
    assert calls == 2
    assert await sqlite_store.find_nearest((1, 0), namespace="empty") is None
    assert sqlite_store._database._snapshot is snapshot
    with connection(sqlite_store._config.path) as db:
        assert db.execute(
            "SELECT hit_count FROM cache_entries WHERE cache_key=?",
            (match.entry.cache_key,),
        ).fetchone() == (4,)


@pytest.mark.parametrize(
    "mutation", ["replace", "insert", "delete", "clear", "clear_all"]
)
async def test_local_mutation_retires_warm_snapshot(
    sqlite_store: SQLiteStore, mutation: str
) -> None:
    await sqlite_store.put(entry("old", vector=(0.8, 0.6)))
    await sqlite_store.put(entry("runner", vector=(0, 1)))
    old = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert old is not None
    assert old.entry.prompt == "old"
    snapshot = sqlite_store._database._snapshot
    assert snapshot is not None
    retired = weakref.ref(snapshot)
    del snapshot
    expected: str | None
    if mutation == "replace":
        await sqlite_store.put(entry("old", vector=(-1, 0)))
        expected = "runner"
    elif mutation == "insert":
        await sqlite_store.put(entry("new"))
        expected = "new"
    elif mutation == "delete":
        assert await sqlite_store.delete_entry(old.entry.cache_key, namespace="default")
        expected = "runner"
    elif mutation == "clear":
        assert await sqlite_store.clear(namespace="default") == 2
        expected = None
    else:
        assert await sqlite_store.clear_all() == 2
        expected = None
    assert sqlite_store._database._snapshot is None
    gc.collect()
    assert retired() is None
    match = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert (None if match is None else match.entry.prompt) == expected
    if mutation != "insert":
        assert not await sqlite_store.record_hit(
            old.entry.cache_key,
            namespace="default",
            expected_created_at=old.entry.created_at,
        )


async def test_single_scope_retention_eviction_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "bounded.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, max_size=2, default_ttl_seconds=None
    )
    store = await SQLiteStore.connect(
        path, embedding_space=SPACE, max_size=2, default_ttl_seconds=None
    )
    await store.put(entry("a", namespace="a"))
    await store.put(entry("b", namespace="b"))
    assert await store.find_nearest((1, 0), namespace="a") is not None
    first_snapshot = store._database._snapshot
    assert first_snapshot is not None
    old = weakref.ref(first_snapshot)
    del first_snapshot
    assert await store.find_nearest((1, 0), namespace="b") is not None
    gc.collect()
    assert old() is None
    snapshot = store._database._snapshot
    assert snapshot is not None
    assert snapshot.matrix.nbytes == 2 * 8
    del snapshot
    await store.put(entry("new", namespace="b"))
    assert await store.find_nearest((1, 0), namespace="a") is None
    match = await store.find_nearest((1, 0), namespace="b")
    assert match is not None
    last_snapshot = store._database._snapshot
    assert last_snapshot is not None
    retained = weakref.ref(last_snapshot)
    del last_snapshot
    await store.aclose()
    gc.collect()
    assert retained() is None
    async with await SQLiteStore.connect(
        path, embedding_space=SPACE, max_size=2, default_ttl_seconds=None
    ) as reopened:
        assert reopened._database._snapshot is None
        assert await reopened.find_nearest((1, 0), namespace="b") == match


@pytest.mark.parametrize("mutation", ["put", "replace", "delete", "clear", "hit"])
async def test_independent_process_commit_invalidates_warm_search(
    sqlite_store: SQLiteStore, mutation: str
) -> None:
    value = entry("runner", vector=(0.8, 0.6)) if mutation == "put" else entry("shared")
    await sqlite_store.put(value)
    before = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert before is not None
    snapshot = sqlite_store._database._snapshot
    with connection(sqlite_store._config.path) as db:
        revision = db.execute("SELECT last_revision_us FROM binding_state").fetchone()
    process, pipe = spawn(sqlite_store._config.path)
    try:
        assert receive(pipe) == "ready"
        pipe.send(mutation)
        assert receive(pipe)[0]
        after = await sqlite_store.find_nearest((1, 0), namespace="default")
        assert sqlite_store._database._snapshot is not snapshot
        if mutation in {"clear", "delete"}:
            assert after is None
            with connection(sqlite_store._config.path) as db:
                assert (
                    db.execute("SELECT last_revision_us FROM binding_state").fetchone()
                    == revision
                )
        else:
            assert after is not None
            assert after.entry.prompt == "shared"
            if mutation == "replace":
                assert after.entry.response == "process replacement"
                assert after.entry.created_at != before.entry.created_at
    finally:
        assert stop(process, pipe) == 0


@pytest.mark.parametrize("mutation", ["replace", "delete", "clear"])
async def test_process_mutation_between_warm_capture_and_winner_read(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    await sqlite_store.put(entry("shared"))
    before = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert before is not None
    process, pipe = spawn(sqlite_store._config.path)
    try:
        assert receive(pipe) == "ready"
        async with block_lookup(sqlite_store, monkeypatch) as entered:
            task = asyncio.create_task(
                sqlite_store.find_nearest((1, 0), namespace="default")
            )
            await asyncio.wait_for(entered.wait(), 5)
            pipe.send(mutation)
            assert receive(pipe)[0]
        assert await task is None
        assert not await sqlite_store.record_hit(
            before.entry.cache_key,
            namespace="default",
            expected_created_at=before.entry.created_at,
        )
    finally:
        assert stop(process, pipe) == 0


@pytest.mark.parametrize("boundary", ["capture", "hit_commit"])
async def test_process_commit_at_change_token_fences(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    await sqlite_store.put(entry("shared"))
    before = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert before is not None
    loop = asyncio.get_running_loop()
    entered, release = asyncio.Event(), threading.Event()
    rows = Job.rows
    armed = True

    def paused(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        nonlocal armed
        result = rows(job, sql, parameters)
        target = "PRAGMA data_version" if boundary == "capture" else "COMMIT"
        if armed and job.owner is sqlite_store._worker and sql == target:
            armed = False
            if boundary == "capture":
                assert job.connection.in_transaction
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(10):
                raise RuntimeError("Change-token test was not released")
        return result

    process, pipe = spawn(sqlite_store._config.path)
    try:
        assert receive(pipe) == "ready"
        with monkeypatch.context() as patch:
            patch.setattr(Job, "rows", paused)
            task: asyncio.Task[CacheMatch | bool | None]
            if boundary == "capture":
                task = asyncio.create_task(
                    sqlite_store.find_nearest((1, 0), namespace="default")
                )
            else:
                task = asyncio.create_task(
                    sqlite_store.record_hit(
                        before.entry.cache_key,
                        namespace="default",
                        expected_created_at=before.entry.created_at,
                    )
                )
            await asyncio.wait_for(entered.wait(), 5)
            pipe.send("replace")
            assert receive(pipe)[0]
            release.set()
            result = await task
            assert result is None if boundary == "capture" else result is True
        assert sqlite_store._database._snapshot is None
        current = await sqlite_store.find_nearest((1, 0), namespace="default")
        assert current is not None
        assert current.entry.response == "process replacement"
    finally:
        release.set()
        await drain_workers(sqlite_store)
        assert stop(process, pipe) == 0


@pytest.mark.parametrize("commit", [False, True])
async def test_external_transaction_visibility(
    sqlite_store: SQLiteStore, commit: bool
) -> None:
    await sqlite_store.put(entry("shared"))
    before = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert before is not None
    snapshot = sqlite_store._database._snapshot
    with connection(sqlite_store._config.path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM cache_entries")
        assert await sqlite_store.find_nearest((1, 0), namespace="default") == before
        assert sqlite_store._database._snapshot is snapshot
        db.execute("COMMIT" if commit else "ROLLBACK")
    after = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert after is None if commit else after == before
    assert (sqlite_store._database._snapshot is snapshot) is not commit


@pytest.mark.parametrize("rollback", [False, True])
async def test_unexpected_local_dml_cannot_reuse_cache(
    sqlite_store: SQLiteStore, rollback: bool
) -> None:
    await sqlite_store.put(entry("first"))
    await sqlite_store.put(entry("runner", vector=(0, 1)))
    before = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert before is not None
    snapshot = sqlite_store._database._snapshot

    def mutate(job: Job) -> None:
        with job.transaction(write=True):
            job.rows(
                "UPDATE cache_entries SET vector_blob=? WHERE cache_key=?",
                (vector_blob(np.asarray([-1.0, 0.0])), before.entry.cache_key),
            )
            if rollback:
                raise ValueError("Rollback this controlled mutation")

    if rollback:
        with pytest.raises(CacheStoreError):
            await sqlite_store._worker.run(mutate)
    else:
        await sqlite_store._worker.run(mutate)
    after = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert after is not None
    assert after.entry.prompt == ("first" if rollback else "runner")
    assert sqlite_store._database._snapshot is not snapshot


async def test_unexpected_change_during_hit_does_not_advance_cache_token(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sqlite_store.put(entry("first"))
    await sqlite_store.put(entry("runner", vector=(0, 1)))
    match = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert match is not None
    rows = Job.rows

    def extra_write(job: Job, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        result = rows(job, sql, parameters)
        if sql.startswith("WITH observation"):
            rows(
                job,
                "UPDATE cache_entries SET vector_blob=? WHERE cache_key=?",
                (vector_blob(np.asarray([-1.0, 0.0])), match.entry.cache_key),
            )
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Job, "rows", extra_write)
        assert await sqlite_store.record_hit(
            match.entry.cache_key,
            namespace="default",
            expected_created_at=match.entry.created_at,
        )
    assert sqlite_store._database._snapshot is None
    after = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert after is not None
    assert after.entry.prompt == "runner"


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE cache_entries SET vector_blob=zeroblob(28)",
        "DELETE FROM cache_payloads",
        "UPDATE binding_state SET last_revision_us=NULL",
        "UPDATE binding_state SET access_counter=0",
        "UPDATE cache_entries SET hit_count=-1",
        "UPDATE schema_migrations SET owner='foreign'",
    ],
)
async def test_corruption_after_warmup_is_an_error(
    sqlite_store: SQLiteStore, mutation: str
) -> None:
    await sqlite_store.put(entry("shared"))
    assert await sqlite_store.find_nearest((1, 0), namespace="default") is not None
    with connection(sqlite_store._config.path) as db:
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute(mutation)
    with pytest.raises(CacheStoreError):
        await sqlite_store.find_nearest((1, 0), namespace="default")


async def test_expiry_window_and_clock_rollback_rebuild_live_set(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1700000000000000]
    monkeypatch.setattr(database, "now_us", lambda: clock[0])
    await sqlite_store._worker.run(
        lambda job: job.connection.create_function(
            "semantix_now_us", 0, lambda: clock[0]
        )
    )
    await sqlite_store.put(entry("runner", vector=(0, 1)))
    await sqlite_store.put(entry("short"), ttl_seconds=1)
    first = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert first is not None
    assert first.entry.prompt == "short"
    snapshot = sqlite_store._database._snapshot
    expiry = clock[0] + 1000000
    clock[0] = expiry - 1
    assert await sqlite_store.find_nearest((1, 0), namespace="default") == first
    assert sqlite_store._database._snapshot is snapshot
    clock[0] = expiry
    expired = await sqlite_store.find_nearest((1, 0), namespace="default")
    assert expired is not None
    assert expired.entry.prompt == "runner"
    assert sqlite_store._database._snapshot is not snapshot
    clock[0] = expiry - 1
    assert await sqlite_store.find_nearest((1, 0), namespace="default") == first


async def test_failed_build_never_publishes_partial_matrix(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sqlite_store.put(entry("first"))
    assert await sqlite_store.find_nearest((1, 0), namespace="default") is not None
    await sqlite_store.put(entry("second", vector=(0, 1)))
    original = decode_vector
    calls = 0

    def fails(blob: bytes, dimensions: int) -> NDArray[np.float64]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("Controlled second vector failure")
        return original(blob, dimensions)

    with monkeypatch.context() as patch:
        patch.setattr(database, "decode_vector", fails)
        with pytest.raises(CacheStoreError):
            await sqlite_store.find_nearest((1, 0), namespace="default")
    assert sqlite_store._database._snapshot is None
    assert await sqlite_store.find_nearest((1, 0), namespace="default") is not None


async def test_busy_close_keeps_active_snapshot(
    sqlite_store: SQLiteStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    await sqlite_store.put(entry("first"))
    assert await sqlite_store.find_nearest((1, 0), namespace="default") is not None
    snapshot = sqlite_store._database._snapshot
    async with block_lookup(sqlite_store, monkeypatch) as entered:
        task = asyncio.create_task(
            sqlite_store.find_nearest((1, 0), namespace="default")
        )
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(CacheBusyError):
            await sqlite_store.aclose()
        assert sqlite_store._database._snapshot is snapshot
    assert await task is not None


@pytest.mark.parametrize("cancel", [False, True])
async def test_late_close_cleanup_releases_retained_matrix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    path = tmp_path / "close.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    store = await SQLiteStore.connect(
        path,
        embedding_space=SPACE,
        default_ttl_seconds=None,
        close_timeout_seconds=5 if cancel else 0.05,
    )
    await store.put(entry("first"))
    assert await store.find_nearest((1, 0), namespace="default") is not None
    last_snapshot = store._database._snapshot
    assert last_snapshot is not None
    retained = weakref.ref(last_snapshot)
    del last_snapshot
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    original = Worker._close_connection

    def close(worker: Worker) -> None:
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(5):
            raise RuntimeError("Close was not released")
        original(worker)

    monkeypatch.setattr(Worker, "_close_connection", close)
    task = asyncio.create_task(store.aclose())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(CacheTimeoutError):
                await task
    finally:
        release.set()
        assert store._worker.cleanup is not None
        await asyncio.wait_for(asyncio.shield(store._worker.cleanup), 5)
        await asyncio.sleep(0)
        gc.collect()
        assert retained() is None
        assert store._database._validated is None
        await store.aclose()
