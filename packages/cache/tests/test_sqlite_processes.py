"""Independent spawn processes share real WAL authority, including crash boundaries."""

import asyncio
import json
import multiprocessing
import sqlite3
import sys
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from multiprocessing.process import BaseProcess
from pathlib import Path
from time import monotonic_ns, perf_counter
from typing import Any, Protocol
from unittest.mock import Mock

import pytest

from examples.store_conformance import SPACE
from examples.store_conformance.cases import entry
from semantix_cache import CacheStoreError, CacheTimeoutError
from semantix_cache.stores._backends.sqlite.format import micros
from semantix_cache.stores._backends.sqlite.worker import Job, Row
from semantix_cache.stores.sqlite import SQLiteStore

from . import sqlite_helpers
from .sqlite_helpers import connection

sqlite_store = sqlite_helpers.sqlite_store


class Channel(Protocol):
    def send(self, value: object) -> None: ...
    def recv(self) -> Any: ...
    def poll(self, timeout: float = 0.0) -> bool: ...
    def close(self) -> None: ...


REVISION = datetime(2020, 1, 1, tzinfo=UTC)


# One writer per buffer; the parent also retains observations after an abrupt exit.
DIAGNOSTIC_LIMIT = 64
DIAGNOSTIC_HEADER = 4  # records written, phase, command sequence, command kind
DIAGNOSTIC_FIELDS = (
    "statement",
    "rows_start_ns",
    "statement_start_ns",
    "finish_ns",
    "deadline_ns",
    "busy_timeout_ms",
    "transaction_before",
    "transaction_after",
    "sqlite_code",
    "stopped",
    "command_sequence",
    "command",
)


def report_sqlite_diagnostics(
    pid: int | None, exitcode: int | None, data: Any, stage: str
) -> None:
    width = len(DIAGNOSTIC_FIELDS)
    total = int(data[0])
    records = []
    for sequence in range(max(0, total - DIAGNOSTIC_LIMIT), total):
        offset = DIAGNOSTIC_HEADER + sequence % DIAGNOSTIC_LIMIT * width
        record = dict(
            zip(DIAGNOSTIC_FIELDS, data[offset : offset + width], strict=True)
        )
        record["sequence"] = sequence
        record["remaining_at_finish_ns"] = (
            record["deadline_ns"] - record["finish_ns"] if record["finish_ns"] else -1
        )
        records.append(record)
    sys.stdout.write(
        "SQLite process diagnostics "
        + json.dumps(
            {
                "pid": pid,
                "exitcode": exitcode,
                "stage": stage,
                "phase": data[1],
                "commands_received": data[2],
                "records_written": total,
                "statements": {
                    1: "BEGIN IMMEDIATE",
                    2: "COMMIT",
                    3: "other failed statement",
                },
                "phases": {
                    0: "not started",
                    1: "connecting",
                    2: "idle",
                    3: "operation",
                    4: "closing",
                    5: "closed",
                },
                "commands": {1: "put", 2: "hit", 3: "other"},
                "records": records,
            }
        )
        + "\n"
    )
    sys.stdout.flush()


def diagnostic_phase(data: Any, phase: int, command: str | None = None) -> None:
    if data is not None:
        data[1] = phase
        if command is not None:
            data[2] += 1
            data[3] = {"put": 1, "hit": 2}.get(command, 3)


def capture_sqlite_failures(pipe: Channel, data: Any = None) -> None:
    original_rows = Job.rows
    installed = False
    active: int | None = None

    def trace(statement: str) -> None:
        if active is None:
            return
        # SQLite supplies expanded SQL; retain only these fixed, parameter-free forms.
        if statement.startswith("PRAGMA busy_timeout="):
            data[active + 5] = int(statement.partition("=")[2])
        elif statement in ("BEGIN IMMEDIATE", "COMMIT"):
            data[active + 2] = monotonic_ns()

    def start(job: Job, kind: int, started: int) -> int:
        width = len(DIAGNOSTIC_FIELDS)
        sequence = int(data[0])
        offset = DIAGNOSTIC_HEADER + sequence % DIAGNOSTIC_LIMIT * width
        data[offset : offset + width] = [
            kind,
            started,
            0,
            0,
            int(job.deadline * 1e9),
            -1,
            int(job.connection.in_transaction),
            -1,
            0,
            int(job.stopped.is_set()),
            int(data[2]),
            int(data[3]),
        ]
        data[0] = sequence + 1
        return offset

    def finish(job: Job) -> None:
        if active is not None and not data[active + 3]:
            data[active + 7] = int(job.connection.in_transaction)
            data[active + 9] = int(job.stopped.is_set())
            data[active + 3] = monotonic_ns()

    def reported_rows(
        job: Job, sql: str, parameters: Sequence[object] = ()
    ) -> list[Row]:
        nonlocal installed, active
        started = monotonic_ns()
        if data is not None:
            if not installed:
                job.connection.set_trace_callback(trace)
                installed = True
            if sql in ("BEGIN IMMEDIATE", "COMMIT"):
                active = start(job, 1 if sql == "BEGIN IMMEDIATE" else 2, started)
        try:
            return original_rows(job, sql, parameters)
        except sqlite3.Error as error:
            if data is not None:
                if active is None:
                    active = start(job, 3, started)
                data[active + 8] = error.sqlite_errorcode
                finish(job)
            pipe.send(
                {
                    "sqlite_failure": error.sqlite_errorname,
                    "statement": sql.split(maxsplit=1)[0],
                }
            )
            raise
        finally:
            finish(job)
            active = None

    diagnostics = pytest.MonkeyPatch()
    diagnostics.setattr(Job, "rows", reported_rows)


def child(
    path: str, pipe: Channel, crash: str | None = None, diagnostics: Any = None
) -> None:
    diagnostic_phase(diagnostics, 1)

    async def run() -> None:
        store = await SQLiteStore.connect(
            path, embedding_space=SPACE, default_ttl_seconds=None
        )
        diagnostic_phase(diagnostics, 2)
        capture_sqlite_failures(pipe, diagnostics)
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
                diagnostic_phase(diagnostics, 3, command)
                started = perf_counter()
                if command == "put":
                    await store.put(entry("shared", created_at=REVISION))
                    result: object = 1
                elif command == "hit":
                    candidate = await store.find_nearest((1, 0), namespace="default")
                    assert candidate
                    result = await store.record_hit(
                        candidate.entry.cache_key,
                        namespace="default",
                        expected_created_at=candidate.entry.created_at,
                    )
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
                diagnostic_phase(diagnostics, 2)
                pipe.send((result, perf_counter() - started))
        finally:
            diagnostic_phase(diagnostics, 4)
            await store.aclose()
            diagnostic_phase(diagnostics, 5)

    try:
        asyncio.run(run())
    finally:
        pipe.close()


def receive(pipe: Channel, seconds: float = 20) -> Any:
    assert pipe.poll(seconds), "Child did not reach expected IPC barrier"
    result = pipe.recv()
    assert not isinstance(result, dict), f"Child storage failure: {result}"
    return result


def spawn(
    path: Path, crash: str | None = None, *, diagnostics: Any = None
) -> tuple[BaseProcess, Channel]:
    context = multiprocessing.get_context("spawn")
    parent, remote = context.Pipe()
    process = context.Process(
        target=child, args=(str(path), remote, crash, diagnostics)
    )
    process.start()
    remote.close()
    return process, parent


def stop(process: BaseProcess, pipe: Channel, diagnostics: Any = None) -> None:
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
    if diagnostics is not None:
        report_sqlite_diagnostics(
            process.pid, process.exitcode, diagnostics, "after stop"
        )
    process.close()


@pytest.mark.parametrize("count", [2, 4])
async def test_process_revision_and_hit_serialization(
    tmp_path: Path, count: int
) -> None:
    path = tmp_path / "processes.db"
    await SQLiteStore.initialize_schema(
        path, embedding_space=SPACE, default_ttl_seconds=None
    )
    context = multiprocessing.get_context("spawn")
    buffers = [
        context.RawArray(
            "q", DIAGNOSTIC_HEADER + DIAGNOSTIC_LIMIT * len(DIAGNOSTIC_FIELDS)
        )
        for _ in range(count)
    ]
    children = [spawn(path, diagnostics=data) for data in buffers]
    failed = True
    try:
        assert [receive(pipe) for _, pipe in children] == ["ready"] * count
        # Barrier each round: SQLite's bounded busy wait does not promise fairness
        # across repeated writers; lock-budget exhaustion is tested separately.
        for _ in range(8):
            for _, pipe in children:
                pipe.send("put")
            assert [receive(pipe)[0] for _, pipe in children] == [1] * count
        with connection(path) as db:
            assert db.execute(
                "SELECT last_revision_us,access_counter FROM binding_state"
            ).fetchone() == (micros(REVISION) + count * 8 - 1, count * 8)
            assert db.execute("SELECT count(*) FROM cache_entries").fetchone() == (1,)
        for _ in range(8):
            for _, pipe in children:
                pipe.send("hit")
            assert [receive(pipe)[0] for _, pipe in children] == [True] * count
        with connection(path) as db:
            assert db.execute("SELECT hit_count FROM cache_entries").fetchone() == (
                count * 8,
            )
            assert db.execute(
                "SELECT access_counter FROM binding_state"
            ).fetchone() == (count * 16,)
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        failed = False
    finally:
        if failed:
            for (process, _), data in zip(children, buffers, strict=True):
                report_sqlite_diagnostics(
                    process.pid, process.exitcode, data, "before stop"
                )
        for (process, pipe), data in zip(children, buffers, strict=True):
            stop(process, pipe, data if failed else None)


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


async def test_process_diagnostics_are_bounded_and_sanitized(
    sqlite_store: SQLiteStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = multiprocessing.get_context("spawn").RawArray(
        "q", DIAGNOSTIC_HEADER + DIAGNOSTIC_LIMIT * len(DIAGNOSTIC_FIELDS)
    )
    pipe = Mock(spec=Channel)
    monkeypatch.setattr(Job, "rows", Job.rows)
    capture_sqlite_failures(pipe, data)

    def action(job: Job) -> None:
        for _ in range(DIAGNOSTIC_LIMIT // 2 + 1):
            with job.transaction(write=True):
                job.rows("SELECT ?", ("private-payload-sentinel",))
        job.rows(
            "SELECT ? FROM nonexistent_diagnostic_table", ("private-payload-sentinel",)
        )

    with pytest.raises(CacheStoreError):
        await sqlite_store._worker.run(action)
    assert data[0] == DIAGNOSTIC_LIMIT + 3
    assert pipe.send.call_args.args[0] == {
        "sqlite_failure": "SQLITE_ERROR",
        "statement": "SELECT",
    }
    report_sqlite_diagnostics(123, 1, data, "after stop")
    output = capsys.readouterr().out
    assert "private-payload-sentinel" not in output
    report = json.loads(output.removeprefix("SQLite process diagnostics "))
    assert len(report["records"]) == DIAGNOSTIC_LIMIT
    assert report["records"][0]["sequence"] == 3
    assert report["records"][-1]["sqlite_code"] == sqlite3.SQLITE_ERROR
    boundaries = report["records"][:-1]
    assert all(r["busy_timeout_ms"] == 1000 for r in boundaries)
    assert all(r["statement_start_ns"] >= r["rows_start_ns"] for r in boundaries)
    assert all(r["remaining_at_finish_ns"] > 0 for r in boundaries)
