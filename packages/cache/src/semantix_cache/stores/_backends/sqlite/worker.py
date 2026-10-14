"""One retained SQLite job per owned thread, including transaction cleanup."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from collections.abc import Callable, Generator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, TypeVar, cast

from ...._lifecycle import Lifecycle
from ....errors import (
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
)
from .format import Configuration, safe, sqlite3

T = TypeVar("T")
Row = tuple[Any, ...]


@dataclass(eq=False)
class Job:
    owner: Worker
    deadline: float
    stopped: threading.Event = field(default_factory=threading.Event)
    committing: bool = False

    def check(self) -> None:
        if self.stopped.is_set() or monotonic() >= self.deadline:
            raise CacheTimeoutError("SQLite operation stopped or timed out")

    @property
    def connection(self) -> sqlite3.Connection:
        connection = self.owner.connection
        if connection is None:
            raise CacheStoreError("SQLite connection is unavailable")
        return connection

    def prepare(self) -> None:
        self.check()
        remaining_ms = max(0, min(1000, int((self.deadline - monotonic()) * 1000)))
        self.connection.execute(f"PRAGMA busy_timeout={remaining_ms}").close()

    def rows(self, sql: str, parameters: Sequence[object] = ()) -> list[Row]:
        self.prepare()
        if sql == "COMMIT":
            self.committing = True
        cursor = self.connection.execute(sql, parameters)
        try:
            return cursor.fetchall()
        finally:
            cursor.close()

    @contextmanager
    def transaction(self, *, write: bool = False) -> Generator[None, None, None]:
        self.rows("BEGIN IMMEDIATE" if write else "BEGIN")
        yield
        self.check()
        self.rows("COMMIT")
        self.committing = False
        if self.connection.in_transaction:
            self.owner.faulted.set()
            raise CacheStoreError("SQLite transaction completion is uncertain")


class Worker:
    def __init__(self, config: Configuration) -> None:
        self.config = config
        self.loop = asyncio.get_running_loop()
        self.pid = os.getpid()
        self.state = Lifecycle()
        self.slot = asyncio.Semaphore(1)
        self.pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="semantix-sqlite"
        )
        self.connection: sqlite3.Connection | None = None
        self.guard = threading.Lock()
        self.current: Job | None = None
        self.faulted = threading.Event()
        self.pending: set[asyncio.Future[Any]] = set()
        self.admitted = 0
        self.cleanup: asyncio.Task[None] | None = None

    def check_owner(self) -> None:
        if os.getpid() != self.pid or asyncio.get_running_loop() is not self.loop:
            raise CacheConfigurationError(
                "SQLiteStore must be used in its creating process and event loop"
            )

    def bind(self, connection: sqlite3.Connection) -> None:
        with self.guard:
            self.connection = connection

    def interrupt(self, job: Job) -> None:
        job.stopped.set()
        with self.guard:
            if self.current is job and self.connection is not None:
                self.connection.interrupt()

    def _work(
        self, job: Job, action: Callable[[Job], T]
    ) -> tuple[T | None, BaseException | None]:
        failure: BaseException | None = None
        result: T | None = None
        try:
            if self.faulted.is_set():
                raise CacheStoreError("SQLiteStore is faulted; close and reopen it")
            with self.guard:
                self.current = job
            job.check()
            if self.connection is not None:
                self.connection.set_progress_handler(
                    lambda: int(job.stopped.is_set() or monotonic() >= job.deadline),
                    1000,
                )
            result = action(job)
            job.check()
            if self.connection is not None and self.connection.in_transaction:
                self.faulted.set()
                raise CacheStoreError("SQLite transaction was left active")
        except (
            sqlite3.Error,
            OSError,
            ValueError,
            TypeError,
            OverflowError,
            RecursionError,
        ):
            failure = (
                CacheTimeoutError("SQLite operation timed out")
                if job.stopped.is_set() or monotonic() >= job.deadline
                else CacheStoreError(
                    "SQLite storage operation failed or persisted data is invalid"
                )
            )
        except (
            CacheStoreError,
            CacheTimeoutError,
            CacheConfigurationError,
            CacheValidationError,
        ) as error:
            failure = error
        finally:
            # Deregister before rollback so a delayed interrupt cannot cancel cleanup.
            with self.guard:
                self.current = None
            connection = self.connection
            if connection is not None:
                try:
                    if job.committing and (
                        failure is not None or sys.exception() is not None
                    ):
                        self.faulted.set()
                    cleanup_deadline = monotonic() + self.config.close_timeout
                    connection.set_progress_handler(
                        lambda: int(monotonic() >= cleanup_deadline), 1000
                    )
                    if connection.in_transaction:
                        connection.execute("PRAGMA busy_timeout=1000").close()
                        connection.execute("ROLLBACK").close()
                    if connection.in_transaction:
                        raise CacheStoreError("SQLite rollback did not complete")
                    connection.set_progress_handler(None, 0)
                except (sqlite3.Error, OSError, CacheStoreError):
                    self.faulted.set()
                    failure = CacheStoreError(
                        "SQLite transaction cleanup failed; store is faulted"
                    )
        if failure is not None:
            return None, failure
        return result, None

    async def run(
        self, action: Callable[[Job], T], *, budget_seconds: float | None = None
    ) -> T:
        self.check_owner()
        self.state.check_open()
        if self.faulted.is_set():
            raise CacheStoreError("SQLiteStore is faulted; close and reopen it")
        if self.admitted >= 32:
            raise CacheStoreError("SQLiteStore admission limit reached")
        job = Job(
            self,
            monotonic()
            + (self.config.timeout if budget_seconds is None else budget_seconds),
        )
        self.admitted += 1
        submitted = False
        acquired = False
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
                        done: asyncio.Future[tuple[T | None, BaseException | None]],
                    ) -> None:
                        self.admitted -= 1
                        self.pending.discard(done)
                        self.slot.release()
                        if not done.cancelled():
                            done.exception()

                    future.add_done_callback(completed)
                    result, failure = await asyncio.shield(future)
                    if failure is not None:
                        if isinstance(failure, (CacheStoreError, CacheTimeoutError)):
                            safe(failure)
                        raise failure
                    return cast(T, result)
            except asyncio.CancelledError:
                self.interrupt(job)
                raise
            except TimeoutError:
                self.interrupt(job)
                if deadline.expired():
                    safe(CacheTimeoutError("SQLite operation timed out"))
                raise
            finally:
                if not submitted:
                    self.admitted -= 1
                    if acquired:
                        self.slot.release()

    def _close_connection(self) -> None:
        with self.guard:
            connection = self.connection
        if connection is not None:
            connection.close()
            with self.guard:
                self.connection = None

    async def _cleanup(self) -> None:
        failure = False
        try:
            if self.pending:
                await asyncio.gather(*tuple(self.pending), return_exceptions=True)
            await self.loop.run_in_executor(self.pool, self._close_connection)
        except (sqlite3.Error, OSError):
            failure = True
        finally:
            await asyncio.to_thread(self.pool.shutdown, wait=True, cancel_futures=False)
        if failure:
            safe(CacheStoreError("SQLite owned connection cleanup failed"))

    def start_cleanup(self, *, startup: bool = False) -> asyncio.Task[None]:
        if self.cleanup is None:
            if startup:
                self.state.closed = True
            else:
                self.state.close(workers=bool(self.pending))
            self.cleanup = asyncio.create_task(self._cleanup())
            self.cleanup.add_done_callback(
                lambda task: None if task.cancelled() else task.exception()
            )
        return self.cleanup

    async def close(self) -> None:
        self.check_owner()
        task = self.start_cleanup()
        try:
            async with asyncio.timeout(self.config.close_timeout):
                await asyncio.shield(task)
        except TimeoutError:
            safe(
                CacheTimeoutError(
                    "SQLite close timed out; owned cleanup remains tracked"
                )
            )
