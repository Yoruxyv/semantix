"""Failed construction owns every resource, including permanent close failure."""

from __future__ import annotations

import asyncio
import gc
import socket
import sys
import threading
import traceback
import weakref
from typing import Any

import pymysql
import pytest

from examples.store_conformance import SPACE
from semantix_cache import (
    CacheBusyError,
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
)
from semantix_cache.stores._backends.mysql import schema
from semantix_cache.stores._backends.mysql.cleanup import LIMIT
from semantix_cache.stores._backends.mysql.database import Database
from semantix_cache.stores._backends.mysql.transport import Resources
from semantix_cache.stores._backends.mysql.worker import Worker
from semantix_cache.stores.mysql import MySQLStore

from .mysql_helpers import admin, new_database, options
from .test_mysql_faults import until

pytestmark = pytest.mark.mysql


@pytest.fixture
async def configuration() -> dict[str, Any]:
    name = await new_database()
    config = options(name) | {
        "embedding_space": SPACE,
        "max_size": 32,
        "default_ttl_seconds": None,
    }
    await MySQLStore.initialize_schema(**config)
    return config


def observe(monkeypatch: pytest.MonkeyPatch) -> list[Worker]:
    workers = []
    original = Worker.__init__

    def create(self: Worker, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        workers.append(self)

    monkeypatch.setattr(Worker, "__init__", create)
    return workers


def retired(worker: Worker) -> None:
    assert worker.connection is None
    assert worker.duplicate is None
    assert worker.thread is not None
    assert not worker.thread.is_alive()
    assert worker.pool_stopped
    assert not worker.remaining
    if worker.resources is not None:
        assert all(item.closed for _, item in worker.resources.files)
        assert all(item.fileno() == -1 for _, item in worker.resources.sockets)


async def recover() -> None:
    for item in MySQLStore.failed_cleanups():
        if item.state in {"retained", "pending"}:
            await MySQLStore.retry_cleanup(item.cleanup_id)


@pytest.mark.parametrize(
    "stage", ["context", "authentication", "session", "schema", "binding"]
)
async def test_failed_startup_stages_retire_every_resource(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    workers = observe(monkeypatch)
    config = dict(configuration)
    if stage == "context":
        config["ca_file"] = str(configuration["ca_file"]) + ".missing"
    elif stage == "authentication":
        config["password"] = "intentionally-incorrect"  # noqa: S105 -- deliberate authentication rejection
    elif stage == "session":
        original = Worker.connect

        def fail(self: Worker, job: Any) -> None:
            original(self, job)
            raise pymysql.OperationalError(2013, "private-startup-marker")

        monkeypatch.setattr(Worker, "connect", fail)
    elif stage == "schema":

        def invalid(job: Any) -> None:
            raise pymysql.OperationalError(2013, "private-startup-marker")

        monkeypatch.setattr(schema, "validate", invalid)
    else:
        config["max_size"] = 33
    with pytest.raises((CacheStoreError, CacheConfigurationError)) as caught:
        await MySQLStore.connect(**config)
    assert "private-startup-marker" not in "".join(
        traceback.format_exception(caught.value)
    )
    retired(workers[-1])


@pytest.mark.parametrize("after", [False, True])
async def test_public_close_failure_cannot_abandon_physically_retired_startup(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch, after: bool
) -> None:
    workers = observe(monkeypatch)
    original = pymysql.Connection.close
    owners = []

    def fail(connection: Any) -> None:
        if threading.current_thread().name.startswith("semantix-mysql"):
            owners.append(threading.get_ident())
            if after:
                original(connection)
            raise OSError("private-public-close-marker")
        original(connection)

    with monkeypatch.context() as patch:
        patch.setattr(pymysql.Connection, "close", fail)
        with pytest.raises(CacheConfigurationError) as caught:
            await MySQLStore.connect(**(configuration | {"max_size": 33}))
        worker = workers[-1]
        retired(worker)
        assert worker.resources is not None
        assert owners == [worker.resources.owner]
        assert any("construction cleanup" in note for note in caught.value.__notes__)
        assert "private-public-close-marker" not in "".join(
            traceback.format_exception(caught.value)
        )
    assert any(
        item.state == "retired" and item.failure
        for item in MySQLStore.failed_cleanups()
    )


def inject_resource_failure(
    worker: Worker, patch: pytest.MonkeyPatch, target: str
) -> None:
    assert worker.resources is not None
    resources = dict(worker.resources.files + worker.resources.sockets)
    resources["duplicate"] = worker.duplicate
    resource = resources[target]
    original = resource.close

    def close() -> None:
        raise OSError("private-physical-close-marker")

    # Only the selected owned object is affected; all other close calls remain real.
    patch.setattr(resource, "close", close)
    assert callable(original)


@pytest.mark.parametrize(
    "target", ["tls-socket", "tls-file", "handshake-file", "duplicate", "raw-socket"]
)
async def test_partial_physical_disposal_retains_discoverable_owner_and_recovers(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    workers = observe(monkeypatch)
    original = Worker.connect
    with monkeypatch.context() as patch:
        if target == "raw-socket":
            original_context = Resources.context

            def context(self: Resources, ca_file: str) -> Any:
                original_context(self, ca_file)
                patch.setattr(
                    self.raw,
                    "close",
                    lambda: (_ for _ in ()).throw(OSError("private-raw-marker")),
                )
                raise OSError("injected failure before dialing")

            patch.setattr(Resources, "context", context)
        else:

            def connect(self: Worker, job: Any) -> None:
                original(self, job)
                inject_resource_failure(self, patch, target)

            patch.setattr(Worker, "connect", connect)
        try:
            with pytest.raises((CacheConfigurationError, CacheStoreError)) as caught:
                await MySQLStore.connect(**(configuration | {"max_size": 33}))
            statuses = [
                item
                for item in MySQLStore.failed_cleanups()
                if item.state == "retained"
            ]
            assert len(statuses) == 1
            status = statuses[0]
            assert target in status.resources
            assert "private-" not in repr(status)
            assert status.cleanup_id in "".join(caught.value.__notes__)
            worker = workers.pop()
            reference = weakref.ref(worker)
            thread = worker.thread
            resources = worker.resources
            del worker
            gc.collect()
            assert reference() is not None
            assert thread is not None
            assert thread.is_alive()
            assert resources is not None
            assert len(status.resources) <= 2
            assert all(
                item.closed
                for name, item in resources.files
                if name != target and not (target == "tls-file" and name == "tls-file")
            )
        finally:
            patch.undo()
            await recover()
    recovered = reference()
    if recovered is not None:
        retired(recovered)
    assert thread is not None
    assert not thread.is_alive()


async def test_permanent_failures_have_fixed_admission_and_retained_resource_budget(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    workers = observe(monkeypatch)
    original = Worker.connect
    references = []
    threads = []
    with monkeypatch.context() as patch:

        def connect(self: Worker, job: Any) -> None:
            original(self, job)
            inject_resource_failure(self, patch, "tls-socket")

        patch.setattr(Worker, "connect", connect)
        try:
            for _ in range(LIMIT):
                with pytest.raises(CacheConfigurationError):
                    await MySQLStore.connect(**(configuration | {"max_size": 33}))
                worker = workers.pop()
                references.append(weakref.ref(worker))
                threads.append(worker.thread)
                del worker
            gc.collect()
            pending = [
                item
                for item in MySQLStore.failed_cleanups()
                if item.state == "retained"
            ]
            assert len(pending) == LIMIT == 8
            assert all(ref() is not None for ref in references)
            with pytest.raises(CacheBusyError, match="cleanup capacity"):
                await MySQLStore.connect(**configuration)
            assert not workers, "Admission must reject before allocating a worker"
            for reference in references:
                retained = reference()
                assert retained is not None
                assert retained.resources is not None
                assert (
                    len(retained.resources.files) + len(retained.resources.sockets) + 1
                    <= 5
                )
            assert len(MySQLStore.failed_cleanups()) <= 2 * LIMIT
        finally:
            patch.undo()
            await recover()
    assert all(thread is not None and not thread.is_alive() for thread in threads)
    assert not [
        item for item in MySQLStore.failed_cleanups() if item.state != "retired"
    ]


@pytest.mark.parametrize("close_fails", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
async def test_constructor_cleanup_timeout_or_cancellation_keeps_owner_and_observes_errors(
    configuration: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
    close_fails: bool,
) -> None:
    workers = observe(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = Worker.retire
    original_close = pymysql.Connection.close
    if close_fails:

        def close(connection: Any) -> None:
            if threading.current_thread().name.startswith("semantix-mysql"):
                raise OSError("private-cancelled-cleanup-marker")
            original_close(connection)

        monkeypatch.setattr(pymysql.Connection, "close", close)
    diagnostics = []
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: diagnostics.append(context))

    def retire(self: Worker) -> None:
        if self.state.closed:
            entered.set()
            assert release.wait(3)
        original(self)

    monkeypatch.setattr(Worker, "retire", retire)
    task = asyncio.create_task(
        MySQLStore.connect(
            **(configuration | {"max_size": 33, "close_timeout_seconds": 0.03})
        )
    )
    try:
        await until(entered.is_set)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError) as caught:
                await task
            assert any(
                "CacheConfigurationError" in note for note in caught.value.__notes__
            )
        else:
            with pytest.raises(CacheConfigurationError):
                await task
        pending = [
            item for item in MySQLStore.failed_cleanups() if item.state == "pending"
        ]
        assert len(pending) == 1
        assert workers[-1].thread is not None
        assert workers[-1].thread.is_alive()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await until(
            lambda: workers[-1].thread is not None and not workers[-1].thread.is_alive()
        )
        await recover()
        loop.set_exception_handler(previous_handler)
    retired(workers[-1])
    gc.collect()
    await asyncio.sleep(0)
    assert not diagnostics


async def test_initializer_close_failure_is_also_owned(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    workers = observe(monkeypatch)
    original = pymysql.Connection.close

    def fail(connection: Any) -> None:
        if threading.current_thread().name.startswith("semantix-mysql"):
            raise OSError("private-setup-close-marker")
        original(connection)

    with monkeypatch.context() as patch:
        patch.setattr(pymysql.Connection, "close", fail)
        with pytest.raises(CacheStoreError) as caught:
            await MySQLStore.initialize_schema(**configuration)
        assert "private-setup-close-marker" not in "".join(
            traceback.format_exception(caught.value)
        )
        retired(workers[-1])


async def test_closed_resource_objects_cannot_close_replacement_sockets(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    workers = observe(monkeypatch)
    with pytest.raises(CacheConfigurationError):
        await MySQLStore.connect(**(configuration | {"max_size": 33}))
    retired(workers[-1])
    old_resources = workers[-1].resources
    worker_ref = weakref.ref(workers.pop())
    replacements = [socket.socket() for _ in range(16)]
    try:
        for sock in replacements:
            sock.bind(("127.0.0.1", 0))
        gc.collect()
        await asyncio.sleep(0)
        assert worker_ref() is None
        assert old_resources is not None
        assert all(item.fileno() == -1 for _, item in old_resources.sockets)
        assert all(sock.fileno() >= 0 and sock.getsockname() for sock in replacements)
    finally:
        for sock in replacements:
            sock.close()


async def test_cleanup_management_rejects_unknown_identity() -> None:
    with pytest.raises(CacheConfigurationError, match="Unknown"):
        await MySQLStore.retry_cleanup("not-an-owned-cleanup")


@pytest.mark.parametrize("pending", [False, True])
def test_failed_startup_owner_survives_original_loop_shutdown(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch, pending: bool
) -> None:
    workers = observe(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original_connect, original_retire = Worker.connect, Worker.retire
    with monkeypatch.context() as patch:
        if pending:

            def retire(self: Worker) -> None:
                if self.state.closed:
                    entered.set()
                    assert release.wait(5)
                original_retire(self)

            patch.setattr(Worker, "retire", retire)
        else:

            def connect(self: Worker, job: Any) -> None:
                original_connect(self, job)
                inject_resource_failure(self, patch, "tls-socket")

            patch.setattr(Worker, "connect", connect)

        async def failed() -> None:
            with pytest.raises(CacheConfigurationError):
                await MySQLStore.connect(
                    **(configuration | {"max_size": 33, "close_timeout_seconds": 1.0})
                )

        try:
            asyncio.run(failed())
            statuses = [
                item for item in MySQLStore.failed_cleanups() if item.state != "retired"
            ]
            assert len(statuses) == 1
            assert statuses[0].loop_closed
            assert workers[-1].thread is not None
            assert workers[-1].thread.is_alive()
            owner = workers[-1].thread.ident
        finally:
            release.set()
            patch.undo()
            asyncio.run(recover())
    retired(workers[-1])
    assert workers[-1].thread is not None
    assert workers[-1].thread.ident == owner


async def test_cancelled_and_timed_out_recovery_coalesce_without_abandoning_owner(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    workers = observe(monkeypatch)
    original_connect = Worker.connect
    with monkeypatch.context() as patch:

        def connect(self: Worker, job: Any) -> None:
            original_connect(self, job)
            inject_resource_failure(self, patch, "tls-socket")

        patch.setattr(Worker, "connect", connect)
        with pytest.raises(CacheConfigurationError):
            await MySQLStore.connect(
                **(configuration | {"max_size": 33, "close_timeout_seconds": 1.0})
            )
    item = next(
        item for item in MySQLStore.failed_cleanups() if item.state == "retained"
    )
    worker = workers[-1]
    entered, release = threading.Event(), threading.Event()
    original_retire = worker.retire
    attempts = []
    diagnostics = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: diagnostics.append(context))

    def retire() -> None:
        attempts.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        original_retire()

    monkeypatch.setattr(worker, "retire", retire)
    first = asyncio.create_task(MySQLStore.retry_cleanup(item.cleanup_id))
    try:
        await until(entered.is_set)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(CacheTimeoutError):
            await MySQLStore.retry_cleanup(item.cleanup_id)
        assert len(attempts) == 1
        assert any(
            status.cleanup_id == item.cleanup_id and status.state == "pending"
            for status in MySQLStore.failed_cleanups()
        )
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)
        await MySQLStore.retry_cleanup(item.cleanup_id)
        loop.set_exception_handler(previous)
    retired(worker)
    assert worker.resources is not None
    assert attempts == [worker.resources.owner]
    gc.collect()
    await asyncio.sleep(0)
    assert not diagnostics


async def test_physical_retirement_transitions_only_on_original_owner_thread(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    workers = observe(monkeypatch)
    original = Worker.connect
    transitions = []
    with monkeypatch.context() as patch:

        def connect(self: Worker, job: Any) -> None:
            original(self, job)
            assert self.resources is not None
            items = (
                list(self.resources.files)
                + list(self.resources.sockets)
                + [("duplicate", self.duplicate)]
            )
            for name, resource in items:
                original_close = resource.close

                def close(
                    name: str = name,
                    resource: Any = resource,
                    original_close: Any = original_close,
                ) -> None:
                    active = (
                        not resource.closed
                        if name.endswith("file")
                        else resource.fileno() >= 0
                    )
                    original_close()
                    if active:
                        transitions.append((name, id(resource), threading.get_ident()))

                patch.setattr(resource, "close", close)

        patch.setattr(Worker, "connect", connect)
        with pytest.raises(CacheConfigurationError):
            await MySQLStore.connect(**(configuration | {"max_size": 33}))
        worker = workers[-1]
        retired(worker)
        assert worker.resources is not None
        assert {name for name, _, _ in transitions} == {
            "handshake-file",
            "tls-file",
            "tls-socket",
            "duplicate",
        }
        assert all(ident == worker.resources.owner for _, _, ident in transitions)
        assert len({identity for _, identity, _ in transitions}) == len(transitions)


async def test_repeated_fully_retired_failures_release_worker_and_resource_ownership(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    workers = observe(monkeypatch)
    original = pymysql.Connection.close
    references = []

    def close(connection: Any) -> None:
        if threading.current_thread().name.startswith("semantix-mysql"):
            raise OSError("private-repeated-close-marker")
        original(connection)

    with monkeypatch.context() as patch:
        patch.setattr(pymysql.Connection, "close", close)
        for _ in range(3 * LIMIT):
            with pytest.raises(CacheConfigurationError):
                await MySQLStore.connect(**(configuration | {"max_size": 33}))
            retired(workers[-1])
            references.append(weakref.ref(workers.pop()))
    gc.collect()
    await asyncio.sleep(0)
    assert all(reference() is None for reference in references)
    assert all(item.state == "retired" for item in MySQLStore.failed_cleanups())
    assert len(MySQLStore.failed_cleanups()) <= LIMIT
    assert not [
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("semantix-mysql")
    ]


@pytest.mark.parametrize("invalid", [None, [], {}, 0])
async def test_cleanup_inspection_rejects_invalid_identifier_types(
    invalid: Any,
) -> None:
    with pytest.raises(CacheConfigurationError, match="Unknown"):
        await MySQLStore.retry_cleanup(invalid)


async def test_partial_constructed_store_close_retains_caller_owner_until_retry(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = await MySQLStore.connect(**configuration)
    worker = store._worker
    assert worker.resources is not None
    file = dict(worker.resources.files)["tls-file"]
    with monkeypatch.context() as patch:
        patch.setattr(
            file,
            "close",
            lambda: (_ for _ in ()).throw(OSError("private-partial-file-marker")),
        )
        with pytest.raises(CacheStoreError):
            await store.aclose()
        assert worker.thread is not None
        assert worker.thread.is_alive()
        assert store._worker is worker
    # PyMySQL marks close before closing its buffer; the explicit retry must not
    # depend on calling that already-marked driver close successfully.
    with pytest.raises(CacheStoreError):
        await store.aclose()
    retired(worker)


async def test_failure_before_worker_allocation_is_sanitized_and_releases_admission(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    workers = observe(monkeypatch)
    with monkeypatch.context() as patch:

        def fail(self: Database, *args: Any, **kwargs: Any) -> None:
            raise pymysql.OperationalError(2013, "private-preallocation-marker")

        patch.setattr(Database, "__init__", fail)
        for _ in range(2 * LIMIT):
            with pytest.raises(
                CacheStoreError, match="before worker allocation"
            ) as caught:
                await MySQLStore.connect(**configuration)
            assert "private-preallocation-marker" not in "".join(
                traceback.format_exception(caught.value)
            )
            assert caught.value.__context__ is None
            assert not workers
    store = await MySQLStore.connect(**configuration)
    await store.aclose()
    retired(workers[-1])


async def test_invalidated_handle_failure_is_discoverable_and_requires_escalation(
    configuration: dict[str, Any],
) -> None:
    # An unrecoverable receipt intentionally consumes admission until process exit.
    # Use a child so this negative case cannot contaminate other fixtures.
    script = r"""
import asyncio
import json
import threading
from examples.store_conformance import SPACE
from semantix_cache import CacheConfigurationError, CacheStoreError
from semantix_cache.stores._backends.mysql.worker import Worker
from semantix_cache.stores.mysql import MySQLStore
from tests.mysql_helpers import options
import sys

workers = []
original = Worker.connect
def connect(self, job):
    original(self, job)
    workers.append(self)
    file = dict(self.resources.files)["tls-file"]
    public_close = file.close
    def fail_after_close():
        assert threading.get_ident() == self.resources.owner
        public_close()
        raise OSError("private-invalidated-close-marker")
    file.close = fail_after_close
    self.restore_file_close = lambda: setattr(file, "close", public_close)
Worker.connect = connect

async def main():
    try:
        await MySQLStore.connect(**(options(sys.argv[1]) | {
            "embedding_space": SPACE, "max_size": 33, "default_ttl_seconds": None,
        }))
    except CacheConfigurationError as error:
        assert "construction cleanup" in "".join(error.__notes__)
    else:
        raise AssertionError("Expected binding policy refusal")
    worker = workers.pop()
    assert worker.thread is not None and not worker.thread.is_alive()
    assert worker.pool_stopped and worker.resources is not None
    assert all(file.closed for _, file in worker.resources.files)
    assert all(sock.fileno() == -1 for _, sock in worker.resources.sockets)
    status, = MySQLStore.failed_cleanups()
    assert status.state == "escalation-required"
    assert status.resources == ("unconfirmed-tls-file",)
    assert "private-" not in repr(status)
    thread_id = worker.thread.ident
    try:
        await MySQLStore.retry_cleanup(status.cleanup_id)
    except CacheStoreError as error:
        assert "controlled process restart" in str(error)
    else:
        raise AssertionError("An invalidated handle must not be blindly retried")
    assert MySQLStore.failed_cleanups() == (status,)
    assert worker.connection is not None
    worker.restore_file_close()
    assert MySQLStore.failed_cleanups() == (status,)
    assert worker.thread.ident == thread_id and not worker.thread.is_alive()
    print(json.dumps({"state": status.state, "worker_terminated": True, "physical_handles_closed": True}))
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-X",
        "utf8",
        "-B",
        "-c",
        script,
        configuration["database"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    assert process.returncode == 0, stderr.decode("utf8")
    assert not stderr
    assert b'"escalation-required"' in stdout
    assert b'"worker_terminated": true' in stdout
    assert b'"physical_handles_closed": true' in stdout


async def test_active_io_close_failure_stays_with_caller_and_explicit_retry_retires(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    store = await MySQLStore.connect(**configuration)
    worker = store._worker
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    original = pymysql.Connection.close
    attempts = []

    def close(connection: Any) -> None:
        if threading.current_thread() is worker.thread:
            attempts.append(threading.get_ident())
            raise OSError("private-active-close-marker")
        original(connection)

    def action(job: Any) -> None:
        loop.call_soon_threadsafe(entered.set)
        job.rows("SELECT SLEEP(1)")

    with monkeypatch.context() as patch:
        patch.setattr(pymysql.Connection, "close", close)
        assert worker.resources is not None
        file = dict(worker.resources.files)["tls-file"]
        patch.setattr(
            file,
            "close",
            lambda: (_ for _ in ()).throw(OSError("private-active-file-marker")),
        )
        task = asyncio.create_task(worker.run(action, readonly=True))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            observed = False
            for _ in range(30):
                rows = await asyncio.to_thread(
                    admin,
                    "SELECT count(*) FROM information_schema.PROCESSLIST WHERE DB=%s AND INFO='SELECT SLEEP(1)'",
                    (configuration["database"],),
                )
                if rows == [(1,)]:
                    observed = True
                    break
                await asyncio.sleep(0.005)
            assert observed, "Cancellation must interrupt server-observed I/O"
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await until(lambda: not worker.pending)
            assert worker.faulted.is_set()
            with pytest.raises(CacheStoreError) as caught:
                await store.aclose()
            assert "private-active-close-marker" not in "".join(
                traceback.format_exception(caught.value)
            )
            assert worker.thread is not None
            assert worker.thread.is_alive()
            assert worker.connection is not None
            assert worker.duplicate is not None
        finally:
            await asyncio.gather(task, return_exceptions=True)
            patch.undo()
            await store.aclose()
    retired(worker)
    assert worker.resources is not None
    assert attempts
    assert all(ident == worker.resources.owner for ident in attempts)


async def test_tls_allocation_failure_before_handshake_keeps_physical_cleanup_owner(
    configuration: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    workers = observe(monkeypatch)
    original = Resources.context
    with monkeypatch.context() as patch:

        def context(self: Resources, ca_file: str) -> Any:
            result = original(self, ca_file)

            def peer(socket: Any) -> Any:
                raise OSError("private-before-handshake-marker")

            def close(socket: Any) -> None:
                raise OSError("private-before-handshake-close-marker")

            patch.setattr(self.tls_type, "getpeername", peer)
            patch.setattr(self.tls_type, "close", close)
            return result

        patch.setattr(Resources, "context", context)
        try:
            with pytest.raises(CacheStoreError) as caught:
                await MySQLStore.connect(**configuration)
            worker = workers[-1]
            assert worker.resources is not None
            tls = dict(worker.resources.sockets)["tls-socket"]
            assert tls.fileno() >= 0
            assert worker.thread is not None
            assert worker.thread.is_alive()
            (status,) = (
                item
                for item in MySQLStore.failed_cleanups()
                if item.state == "retained"
            )
            assert "tls-socket" in status.resources
            assert "private-" not in repr(status)
            assert "private-" not in "".join(traceback.format_exception(caught.value))
        finally:
            patch.undo()
            await recover()
    retired(workers[-1])
