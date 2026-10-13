"""One owned worker and connection, retained until actual I/O and cleanup finish."""

from __future__ import annotations

import asyncio
import os
import socket
import threading
from collections.abc import Callable, Generator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.metadata import version
from time import monotonic
from typing import Any, TypeVar, cast

try:
    import pymysql
except ModuleNotFoundError as error:
    if error.name != "pymysql":
        raise
    raise ImportError(
        "MySQLStore requires the optional semantix-cache[mysql] extra"
    ) from None

from .._lifecycle import Lifecycle
from ..errors import (
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    SemantixCacheError,
)
from ._mysql_config import (
    CONNECT_TIMEOUT,
    IO_TIMEOUT,
    SETUP_READ_TIMEOUT,
    Configuration,
)
from ._mysql_format import safe
from ._mysql_transport import Resources

T = TypeVar("T")
Row = tuple[Any, ...]
Failure = tuple[type[SemantixCacheError], str]


def timed_out(error: BaseException) -> bool:
    return (
        isinstance(error, TimeoutError)
        or isinstance(error.__context__, TimeoutError)
        or (
            isinstance(error, pymysql.OperationalError)
            and bool(error.args)
            and error.args[0] in {1205, 3024}
        )
    )


@dataclass(eq=False)
class Job:
    owner: Worker
    deadline: float
    readonly: bool
    stopped: threading.Event = field(default_factory=threading.Event)
    committing: bool = False
    transaction_active: bool = False
    started: bool = False
    affected: int = 0

    def check(self) -> None:
        if self.stopped.is_set() or monotonic() >= self.deadline:
            raise CacheTimeoutError("MySQL operation stopped or timed out")

    @property
    def connection(self) -> pymysql.Connection:
        if self.owner.connection is None:
            raise CacheStoreError("MySQL connection is unavailable")
        return self.owner.connection

    def rows(self, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        self.check()
        with self.connection.cursor() as cursor:
            encoded = cursor.mogrify(sql, tuple(parameters))
            if len(encoded.encode("utf8")) > 4 * 1024 * 1024 - 1024:
                raise CacheStoreError(
                    "MySQL statement exceeds the supported packet budget"
                )
            cursor.execute(sql, tuple(parameters))
            self.affected = cursor.rowcount
            rows = cast(list[Row], list(cursor.fetchall()))
        self.check()
        return rows

    @contextmanager
    def transaction(self, *, write: bool = False) -> Generator[None, None, None]:
        self.rows(
            "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
            if write
            else "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
        )
        self.rows(
            "START TRANSACTION READ WRITE"
            if write
            else "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY"
        )
        self.transaction_active = True
        yield
        # Cancellation and COMMIT dispatch share one guard; no network I/O under it.
        with self.owner.guard:
            self.check()
            self.committing = True
        self.connection.commit()
        self.transaction_active = False
        self.committing = False
        self.check()


class Worker:
    def __init__(self, config: Configuration) -> None:
        if version("PyMySQL") != "1.2.3":
            raise CacheConfigurationError("MySQLStore requires verified PyMySQL 1.2.3")
        self.config = config
        self.loop = asyncio.get_running_loop()
        self.pid = os.getpid()
        self.state = Lifecycle()
        self.slot = asyncio.Semaphore(1)
        self.pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="semantix-mysql"
        )
        self.thread: threading.Thread | None = None
        self.connection: pymysql.Connection | None = None
        self.duplicate: socket.socket | None = None
        self.guard = threading.Lock()
        self.current: Job | None = None
        self.faulted = threading.Event()
        self.pending: set[asyncio.Future[Any]] = set()
        self.admitted = 0
        self.cleanup: asyncio.Task[None] | None = None
        self.revalidate: Callable[[Job], None] | None = None
        self.interrupt_failed = False
        self.last_failure: Failure | None = None
        self.resources: Resources | None = None
        self.terminal_cleanup = True
        self.initializing = False
        self.disposal: Future[Failure | None] | None = None
        self.disposal_guard = threading.Lock()
        self.pool_stopped = False
        self.cleanup_failure: Failure | None = None

    def check_owner(self) -> None:
        if os.getpid() != self.pid or asyncio.get_running_loop() is not self.loop:
            raise CacheConfigurationError(
                "MySQLStore belongs to its creating process and event loop"
            )

    def connect(self, job: Job) -> None:
        job.check()
        self.resources = Resources()
        raw = self.resources.raw
        context = self.resources.context(str(self.config.ca_file))
        raw.settimeout(min(CONNECT_TIMEOUT, max(0.001, job.deadline - monotonic())))
        raw.connect((self.config.address, self.config.port))
        # Only this plain duplicate is touched by the event-loop thread.
        with self.guard:
            job.check()
            self.duplicate = raw.dup()
        raw.settimeout(IO_TIMEOUT)
        connection = pymysql.Connection(
            host=self.config.tls_hostname,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            binary_prefix=True,
            autocommit=True,
            local_infile=False,
            ssl=context,
            connect_timeout=CONNECT_TIMEOUT,
            read_timeout=SETUP_READ_TIMEOUT if self.initializing else IO_TIMEOUT,
            write_timeout=IO_TIMEOUT,
            defer_connect=True,
        )
        self.connection = connection
        connection.connect(sock=raw)
        job.check()

    def interrupt(self, job: Job) -> None:
        with self.guard:
            job.stopped.set()
            if job.started and not job.readonly:
                self.faulted.set()
            if self.current is job and self.duplicate is not None:
                try:
                    self.duplicate.shutdown(socket.SHUT_RDWR)
                except OSError:
                    # Preserve the diagnostic; capped I/O still bounds owner cleanup.
                    self.interrupt_failed = True

    @property
    def remaining(self) -> tuple[str, ...]:
        return self.resources.remaining if self.resources is not None else ()

    def retire(self) -> None:
        connection = self.connection
        with self.guard:
            duplicate = self.duplicate
        failed = False
        if not self.terminal_cleanup and connection is not None and connection.open:
            connection.close()
        if self.resources is not None:
            failed = self.resources.retire(duplicate)
            closed = self.resources.handles_closed
        else:
            closed = duplicate is None and connection is None
        if (
            self.terminal_cleanup
            and closed
            and connection is not None
            and connection.open
        ):
            try:
                connection.close()
            except Exception:  # noqa: BLE001 -- physical retirement is independent of driver state disposal
                failed = True
        if closed and not self.remaining:
            self.connection = None
            with self.guard:
                self.duplicate = None
        if failed:
            raise CacheStoreError(
                "MySQL physical retirement failed or reported a close error"
            )

    def _work(
        self, job: Job, action: Callable[[Job], T]
    ) -> tuple[T | None, Failure | None]:
        self.thread = threading.current_thread()
        result: T | None = None
        failure: Failure | None = None
        broken = False
        with self.guard:
            self.current = job
            job.started = True
        try:
            job.check()
            if self.faulted.is_set():
                raise CacheStoreError("MySQLStore is faulted; close and reopen it")
            if self.connection is None:
                self.connect(job)
                if self.revalidate is not None:
                    try:
                        self.revalidate(job)
                    except Exception:
                        self.faulted.set()
                        raise
            result = action(job)
            job.check()
            if job.transaction_active:
                raise CacheStoreError("MySQL transaction was left active")
        except (pymysql.Error, OSError) as error:
            broken = True
            failure = (
                (CacheTimeoutError, "MySQL operation timed out")
                if job.stopped.is_set()
                or monotonic() >= job.deadline
                or timed_out(error)
                else (CacheStoreError, "MySQL transport or database operation failed")
            )
        except (ValueError, TypeError, OverflowError, RecursionError):
            failure = (CacheStoreError, "MySQL input or persisted data is invalid")
        except (
            CacheStoreError,
            CacheTimeoutError,
            CacheConfigurationError,
            CacheValidationError,
        ) as error:
            failure = (type(error), str(error))
        except Exception:  # noqa: BLE001 -- never deliver internal SQL-bearing frames to asyncio
            self.faulted.set()
            failure = (
                CacheStoreError,
                "Unexpected MySQL worker failure; store is faulted",
            )
        finally:
            with self.guard:
                self.current = None
            stopped = job.stopped.is_set() or monotonic() >= job.deadline
            if (broken or stopped or job.committing) and not job.readonly:
                self.faulted.set()
            try:
                if broken or stopped or self.faulted.is_set():
                    self.retire()
                elif job.transaction_active:
                    job.connection.rollback()
                    job.transaction_active = False
            except Exception:  # noqa: BLE001 -- cleanup failures must remain sanitized and owned
                self.faulted.set()
                failure = (CacheStoreError, "MySQL cleanup failed; store is faulted")
        # Driver exceptions and their SQL-bearing tracebacks never cross the boundary.
        if failure is not None:
            self.last_failure = failure
        return (None, failure) if failure is not None else (result, None)

    async def run(
        self,
        action: Callable[[Job], T],
        *,
        readonly: bool = False,
        budget_seconds: float | None = None,
    ) -> T:
        self.check_owner()
        self.state.check_open()
        if self.faulted.is_set():
            raise CacheStoreError("MySQLStore is faulted; close and reopen it")
        if self.admitted >= 32:
            raise CacheStoreError("MySQLStore admission limit reached")
        job = Job(
            self,
            monotonic()
            + (self.config.timeout if budget_seconds is None else budget_seconds),
            readonly,
        )
        self.admitted += 1
        submitted = acquired = False
        deadline = asyncio.timeout_at(
            self.loop.time() + max(0, job.deadline - monotonic())
        )
        with self.state.operation():
            try:
                async with deadline:
                    await self.slot.acquire()
                    acquired = True
                    job.check()
                    future = self.loop.run_in_executor(
                        self.pool, self._work, job, action
                    )
                    self.pending.add(future)
                    submitted = True

                    def completed(
                        done: asyncio.Future[tuple[T | None, Failure | None]],
                    ) -> None:
                        self.admitted -= 1
                        self.pending.discard(done)
                        self.slot.release()
                        if not done.cancelled():
                            done.exception()

                    future.add_done_callback(completed)
                    result, failure = await asyncio.shield(future)
                    if failure is not None:
                        kind, message = failure
                        safe(kind(message))
                    return cast(T, result)
            except asyncio.CancelledError:
                self.interrupt(job)
                raise
            except TimeoutError:
                self.interrupt(job)
                if deadline.expired():
                    safe(
                        CacheTimeoutError(
                            "MySQL operation timed out; cleanup remains owned"
                        )
                    )
                raise
            finally:
                if not submitted:
                    self.admitted -= 1
                    if acquired:
                        self.slot.release()

    def _close(self) -> Failure | None:
        self.thread = threading.current_thread()
        failure: Failure | None = None
        try:
            self.retire()
        except Exception:  # noqa: BLE001 -- retain only sanitized diagnostics and resource ownership
            self.faulted.set()
            failure = CacheStoreError, "MySQL owned connection close failed"
            self.last_failure = failure
            self.cleanup_failure = failure
        if self.resources is None or self.resources.handles_closed:
            self.pool.shutdown(wait=False, cancel_futures=False)
            self.pool_stopped = True
        return failure

    def submit_cleanup(self, *, terminal: bool = False) -> Future[Failure | None]:
        with self.disposal_guard:
            self.terminal_cleanup = self.terminal_cleanup or terminal
            if self.disposal is None or (
                self.disposal.done() and not self.pool_stopped
            ):
                # The same single-worker queue drains work even after its loop closes.
                self.disposal = self.pool.submit(self._close)
            return self.disposal

    async def _cleanup(self) -> None:
        if self.disposal is None:
            safe(CacheStoreError("MySQL cleanup was not submitted"))
        future = asyncio.wrap_future(self.disposal)
        await asyncio.wait({future})
        failure = future.result()
        if self.pool_stopped:
            while self.thread is not None and self.thread.is_alive():  # noqa: ASYNC110 -- observe actual termination without a second thread
                await asyncio.sleep(0.005)
            if self.thread is not None:
                self.thread.join(timeout=0)
        if failure is not None:
            kind, message = failure
            safe(kind(message))

    def start_cleanup(self, *, startup: bool = False) -> asyncio.Task[None]:
        retry = (
            self.cleanup is not None and self.cleanup.done() and not self.pool_stopped
        )
        if self.cleanup is None or retry:
            if startup:
                self.state.closed = True
            else:
                self.state.close(workers=bool(self.pending))
            self.submit_cleanup(terminal=startup or retry)
            self.cleanup = asyncio.create_task(self._cleanup())
            self.cleanup.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        return self.cleanup

    async def close(self) -> None:
        self.check_owner()
        task = self.start_cleanup()
        done, _ = await asyncio.wait({task}, timeout=self.config.close_timeout)
        if not done:
            safe(CacheTimeoutError("MySQL close timed out; cleanup remains owned"))
        task.result()
