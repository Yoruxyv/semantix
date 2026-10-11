"""Independent spawn processes share real WAL authority, including crash boundaries."""

import asyncio
import multiprocessing
import sqlite3
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from multiprocessing.process import BaseProcess
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache import CacheStoreError, CacheTimeoutError
from semantix_cache.stores._sqlite_format import micros
from semantix_cache.stores._sqlite_worker import Job, Row
from semantix_cache.stores.sqlite import SQLiteStore

from .sqlite_helpers import connection


class Channel(Protocol):
    def send(self, value: object) -> None: ...
    def recv(self) -> Any: ...
    def poll(self, timeout: float = 0.0) -> bool: ...
    def close(self) -> None: ...


REVISION = datetime(2020, 1, 1, tzinfo=UTC)


def capture_sqlite_failures(pipe: Channel) -> None:
    original_rows = Job.rows

    def reported_rows(
        job: Job, sql: str, parameters: Sequence[object] = ()
    ) -> list[Row]:
        try:
            return original_rows(job, sql, parameters)
        except sqlite3.Error as error:
            pipe.send(
                {
                    "sqlite_failure": error.sqlite_errorname,
                    "statement": sql.split(maxsplit=1)[0],
                }
            )
            raise

    diagnostics = pytest.MonkeyPatch()
    diagnostics.setattr(Job, "rows", reported_rows)


def child(path: str, pipe: Channel, crash: str | None = None) -> None:
    async def run() -> None:
        store = await SQLiteStore.connect(
            path, embedding_space=SPACE, default_ttl_seconds=None
        )
        capture_sqlite_failures(pipe)
        if crash is not None:
            original = Job.rows

            def rows(
                job: Job, sql: str, parameters: Sequence[object] = ()
            ) -> list[Row]:
                if sql == "COMMIT":
                    result = original(job, sql, parameters) if crash == "after" else []
                    pipe.send("commit boundary")
                    pipe.recv()  # parent terminates this disposable process
                    return (
                        result if crash == "after" else original(job, sql, parameters)
                    )
                return original(job, sql, parameters)

            patch = pytest.MonkeyPatch()
            patch.setattr(Job, "rows", rows)
            await store.put(entry("crash", created_at=REVISION))
            return
        pipe.send("ready")
        try:
            while True:
                command = pipe.recv()
                if command == "stop":
                    break
                started = perf_counter()
                if command == "put":
                    for _ in range(8):
                        await store.put(entry("shared", created_at=REVISION))
                    result: object = 8
                elif command == "hit":
                    candidate = await store.find_nearest((1, 0), namespace="default")
                    assert candidate
                    result = [
                        await store.record_hit(
                            candidate.entry.cache_key,
                            namespace="default",
                            expected_created_at=candidate.entry.created_at,
                        )
                        for _ in range(8)
                    ]
                elif command == "replace":
                    await store.put(
                        entry(
                            "shared",
                            response="process replacement",
                            created_at=REVISION,
                        )
                    )
                    result = True
                elif command == "delete":
                    result = await store.delete_entry(
                        entry("shared").cache_key, namespace="default"
                    )
                elif command == "clear":
                    result = await store.clear(namespace="default")
                elif command == "hold":
                    db = sqlite3.connect(path, isolation_level=None)
                    try:
                        db.execute("BEGIN IMMEDIATE")
                        pipe.send("locked")
                        assert pipe.recv() == "release"
                        db.execute("ROLLBACK")
                    finally:
                        db.close()
                    result = True
                else:
                    raise AssertionError(command)
                pipe.send((result, perf_counter() - started))
        finally:
            await store.aclose()

    try:
        asyncio.run(run())
    finally:
        pipe.close()


def receive(pipe: Channel, seconds: float = 20) -> Any:
    assert pipe.poll(seconds), "Child did not reach expected IPC barrier"
    result = pipe.recv()
    assert not isinstance(result, dict), f"Child storage failure: {result}"
    return result


def spawn(path: Path, crash: str | None = None) -> tuple[BaseProcess, Channel]:
    context = multiprocessing.get_context("spawn")
    parent, remote = context.Pipe()
    process = context.Process(target=child, args=(str(path), remote, crash))
    process.start()
    remote.close()
    return process, parent


def stop(process: BaseProcess, pipe: Channel) -> None:
    if process.is_alive():
        # Preserve the primary child failure while its owned cleanup/traceback ends.
        with suppress(BrokenPipeError, EOFError):
            pipe.send("stop")
        process.join(10)
    if process.is_alive():
        process.terminate()
        process.join(10)
    pipe.close()
    assert not process.is_alive()
    process.close()


@pytest.mark.parametrize("count", [2, 4])
async def test_process_revision_and_hit_serialization(
    tmp_path: Path, count: int
) -> None:
    path = tmp_path / "processes.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    children = [spawn(path) for _ in range(count)]
    try:
        assert [receive(pipe) for _, pipe in children] == ["ready"] * count
        for _, pipe in children:
            pipe.send("put")
        assert [receive(pipe)[0] for _, pipe in children] == [8] * count
        with connection(path) as db:
            assert db.execute(
                "SELECT last_revision_us,access_counter FROM binding_state"
            ).fetchone() == (micros(REVISION) + count * 8 - 1, count * 8)
            assert db.execute("SELECT count(*) FROM cache_entries").fetchone() == (1,)
        for _, pipe in children:
            pipe.send("hit")
        assert [receive(pipe)[0] for _, pipe in children] == [[True] * 8] * count
        with connection(path) as db:
            assert db.execute("SELECT hit_count FROM cache_entries").fetchone() == (
                count * 8,
            )
            assert db.execute(
                "SELECT access_counter FROM binding_state"
            ).fetchone() == (count * 16,)
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        for process, pipe in children:
            stop(process, pipe)


@pytest.mark.parametrize("mutation", ["replace", "delete", "clear"])
async def test_independent_process_invalidates_candidate(
    tmp_path: Path, mutation: str
) -> None:
    path = tmp_path / "candidate.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    async with await SQLiteStore.connect(
        path, embedding_space=SPACE, default_ttl_seconds=None
    ) as store:
        await store.put(entry("shared", created_at=REVISION))
        candidate = await store.find_nearest((1, 0), namespace="default")
        assert candidate
        process, pipe = spawn(path)
        try:
            assert receive(pipe) == "ready"
            pipe.send(mutation)
            assert receive(pipe)[0]
            assert not await store.record_hit(
                candidate.entry.cache_key,
                namespace="default",
                expected_created_at=candidate.entry.created_at,
            )
            with connection(path) as db:
                assert db.execute(
                    "SELECT coalesce(sum(hit_count),0) FROM cache_entries"
                ).fetchone() == (0,)
        finally:
            stop(process, pipe)


async def test_process_writer_lock_deadline_and_later_success(tmp_path: Path) -> None:
    path = tmp_path / "lock.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    process, pipe = spawn(path)
    try:
        assert receive(pipe) == "ready"
        pipe.send("hold")
        assert receive(pipe) == "locked"
        async with await SQLiteStore.connect(
            path,
            embedding_space=SPACE,
            default_ttl_seconds=None,
            operation_timeout_seconds=0.2,
        ) as store:
            with pytest.raises((CacheTimeoutError, CacheStoreError)):
                await store.put(entry("busy"))
            pipe.send("release")
            assert receive(pipe)[0] is True
            await store.put(entry("later"))
            with connection(path) as db:
                assert db.execute("SELECT cache_key FROM cache_entries").fetchall() == [
                    (entry("later").cache_key,)
                ]
    finally:
        stop(process, pipe)


@pytest.mark.parametrize("boundary", ["before", "after"])
async def test_killed_process_before_and_after_commit_recovers(
    tmp_path: Path, boundary: str
) -> None:
    path = tmp_path / "crash.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    process, pipe = spawn(path, boundary)
    try:
        assert receive(pipe) == "commit boundary"
        process.terminate()
        process.join(10)
        assert not process.is_alive()
        with connection(path) as db:
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("SELECT count(*) FROM cache_entries").fetchone() == (
                int(boundary == "after"),
            )
            assert db.execute("SELECT count(*) FROM cache_payloads").fetchone() == (
                int(boundary == "after"),
            )
        async with await SQLiteStore.connect(
            path, embedding_space=SPACE, default_ttl_seconds=None
        ) as store:
            await store.put(entry("crash", created_at=REVISION))
            candidate = await store.find_nearest((1, 0), namespace="default")
            assert candidate
            assert candidate.entry.created_at == REVISION + timedelta(
                microseconds=int(boundary == "after")
            )
    finally:
        stop(process, pipe)
