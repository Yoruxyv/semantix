"""Owned verified-TLS MySQL storage using the optional pinned synchronous driver."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from .._semantics import cache_key_value, namespace_value
from ..errors import (
    CacheConfigurationError,
    CacheStoreError,
    CacheValidationError,
    SemantixCacheError,
)
from ..models import CacheEntry, CacheMatch, EmbeddingSpace
from ._backends.mysql import cleanup as startup_cleanup
from ._backends.mysql.config import Configuration, timeout
from ._backends.mysql.database import Database
from ._backends.mysql.format import micros, safe
from ._backends.mysql.worker import Worker
from ._mysql_cleanup import MySQLCleanupStatus


class MySQLStore:
    """One owned connection/worker for a marked, dedicated MySQL 8.4 database.

    Setup is explicit. Runtime connects with a pre-registered binding and exact
    capacity/TTL policy. Requires numeric IPv4 dial address, independent TLS name
    and a trusted CA file; certificate/hostname verification cannot be disabled.
    Immutable 0.5-second normal reads/writes and 2-second initialization reads
    constrain network stalls separately from total deadlines. At most 32 admitted
    operations share one worker.

    Cancellation retains actual work/cleanup ownership. Interrupted proven reads
    retire their session; a later independent call may open/revalidate a fresh
    session. Cancelled reads are never replayed. Uncertain mutations, COMMIT or
    cleanup terminally fault the store. Reopening does not resolve an uncertain
    operation and never authorizes automatic business replay. Drain before close.
    """

    def __init__(self, configuration: Configuration) -> None:
        self._config = configuration
        self._database = Database(configuration)
        self._worker = Worker(configuration)

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self._config.space

    @property
    def default_ttl_seconds(self) -> float | None:
        return self._config.ttl

    @classmethod
    async def _open(
        cls, configuration: Configuration, *, initialize: bool, connect_timeout: float
    ) -> Self:
        reservation = startup_cleanup.reserve()
        store: Self | None = None
        try:
            store = cls(configuration)
            startup_cleanup.attach(reservation, store._worker)
            store._worker.initializing = initialize
            await store._worker.run(
                lambda job: store._database.open(job, initialize=initialize),
                readonly=not initialize,
                budget_seconds=connect_timeout,
            )
            store._worker.revalidate = store._database.open
            if initialize:
                await store.aclose()
            else:
                store._worker.terminal_cleanup = False
        except BaseException as error:
            if store is None:
                startup_cleanup.release(reservation)
                if isinstance(error, Exception) and not isinstance(
                    error, SemantixCacheError
                ):
                    safe(
                        CacheStoreError(
                            "MySQL construction failed before worker allocation"
                        )
                    )
                raise
            startup_cleanup.retain(reservation)
            cleanup = store._worker.start_cleanup(startup=True)
            failed = False
            cancelled: asyncio.CancelledError | None = None
            try:
                done, _ = await asyncio.wait(
                    {cleanup}, timeout=configuration.close_timeout
                )
                if done:
                    cleanup.result()
                else:
                    failed = True
            except asyncio.CancelledError as cancellation:
                failed = True
                cancelled = cancellation
            except CacheStoreError:
                failed = True
            if cancelled is not None and not isinstance(error, asyncio.CancelledError):
                cancelled.add_note(
                    "MySQL construction originally failed with " + type(error).__name__
                )
            reported = cancelled if cancelled is not None else error
            if failed:
                reported.add_note(
                    "MySQL construction cleanup "
                    + reservation
                    + " reported an error or remains pending; inspect MySQLStore.failed_cleanups() "
                    + "and await MySQLStore.retry_cleanup(cleanup_id)."
                )
            startup_cleanup.statuses()
            if cancelled is not None:
                try:
                    raise cancelled from None
                except asyncio.CancelledError:
                    cancelled.__context__ = None
                    raise
            raise
        startup_cleanup.release(reservation)
        return store

    @staticmethod
    def failed_cleanups() -> tuple[MySQLCleanupStatus, ...]:
        """Inspect process-local failed construction without exposing credentials.

        At most eight constructions/retained owners are admitted per process;
        capacity is reserved before allocating a worker. Completed error receipts
        occupy a separate eight-item ring without workers or configuration;
        retired IDs expire when that ring evicts them. A
        pending/retained owner survives its original loop and exception. Resources
        are disposed only on the original thread. Inspect on application shutdown;
        do not close a loop while ordinary cache operations are still admitted.
        """
        return startup_cleanup.statuses()

    @staticmethod
    async def retry_cleanup(cleanup_id: str) -> None:
        """Make one explicit disposal attempt; never repeat a cache operation.

        May run on another loop in the same process after the creating loop exits.
        Pending attempts coalesce. Waiting uses the original finite close timeout;
        cancellation does not cancel owned disposal. Permanent failure retains an
        inspectable owner and its admission slot. Drain or explicitly retry before
        shutdown. If an owned handle keeps failing, stop new construction, drain
        ordinary stores and arrange an operator-controlled restart if explicit
        retry cannot retire it. No background retry or automatic process exit occurs.
        If a failing OS close invalidated its handle, the receipt requires
        a controlled process restart: no integer descriptor is reused or closed.
        This API never terminates the application or silently clears that receipt.
        """
        await startup_cleanup.retry(cleanup_id)

    @classmethod
    async def initialize_schema(
        cls,
        *,
        address: str,
        tls_hostname: str,
        ca_file: str | Path,
        user: str,
        password: str | bytes,
        database: str,
        embedding_space: EmbeddingSpace,
        port: int = 3306,
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
        operation_timeout_seconds: float = 30.0,
    ) -> None:
        """Explicit setup with a privileged account, never normal runtime DDL.

        The operator first provisions a dedicated empty database. MySQL DDL is
        not rollbackable as a multi-statement unit: setup leaves an owned
        INITIALIZING marker until complete structural validation. Foreign or
        incomplete schemas are rejected and preserved, never repaired/adopted.
        Existing valid schema can explicitly register another binding under a
        finite database-wide setup lock. Runtime accounts need no DDL privilege.

        Before setup, an account administrator provisions the locked local account
        semantix_schema_verifier@localhost with direct SELECT, TRIGGER, EXECUTE and
        EVENT grants on this database only. It has no application login or DML
        writes. The static, no-argument SQL SECURITY DEFINER procedure returns
        verification status and its own definition digest; it exposes no rows,
        caller SQL or configurable object names. Runtime additionally needs only
        EXECUTE on this procedure. Setup needs authoritative metadata privileges,
        CREATE ROUTINE and SET_ANY_DEFINER as well as its table-creation/DML grants;
        SET_ANY_DEFINER can be revoked after creation. Account provisioning stays
        outside this method. The original table migration remains immutable; the
        verifier has a separate checksummed version. Version-1-only schemas are
        preserved and refused, never upgraded implicitly.

        Drain stores before privileged DDL or definer maintenance. Verification
        observes metadata at a check, not an atomic schema lock: repeatable-read
        operations can retain an earlier catalog view. It cannot protect against
        an administrator maliciously replacing both schema and verifier.
        """
        config = cls._configuration(
            address,
            port,
            tls_hostname,
            ca_file,
            user,
            password,
            database,
            embedding_space,
            max_size,
            default_ttl_seconds,
            operation_timeout_seconds,
            operation_timeout_seconds,
        )
        await cls._open(config, initialize=True, connect_timeout=config.timeout)

    @classmethod
    async def connect(
        cls,
        *,
        address: str,
        tls_hostname: str,
        ca_file: str | Path,
        user: str,
        password: str | bytes,
        database: str,
        embedding_space: EmbeddingSpace,
        port: int = 3306,
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
        connect_timeout_seconds: float = 10.0,
        operation_timeout_seconds: float = 30.0,
        close_timeout_seconds: float = 30.0,
    ) -> Self:
        """Connect to existing READY tables with a least-privileged runtime user.

        No DNS resolution, IPv6, pool, borrowed connection, failover or replay.
        Create the store in its using process/event loop. Capacity is 1â€“5,000,
        dimensions 1â€“16,000, capacity*dimensions*8 <=64MiB. RSS exceeds this matrix
        bound; full exact searches transfer every candidate vector. Hits acquire
        the binding-wide InnoDB writer lock. There is no inspection/clear_all API.
        TTL uses server UTC microseconds and never slides; clock rollback can
        extend retention. Restore requires a new binding generation to avoid
        historical revision reuse. Namespace partitioning is not authorization.
        """
        config = cls._configuration(
            address,
            port,
            tls_hostname,
            ca_file,
            user,
            password,
            database,
            embedding_space,
            max_size,
            default_ttl_seconds,
            operation_timeout_seconds,
            close_timeout_seconds,
        )
        try:
            budget = timeout(connect_timeout_seconds)
        except (ValueError, TypeError):
            safe(CacheConfigurationError("Invalid MySQL connection timeout"))
        return await cls._open(config, initialize=False, connect_timeout=budget)

    @staticmethod
    def _configuration(
        address: str,
        port: int,
        tls_hostname: str,
        ca_file: str | Path,
        user: str,
        password: str | bytes,
        database: str,
        space: EmbeddingSpace,
        capacity: int,
        ttl: float | None,
        operation_timeout: float,
        close_timeout: float,
    ) -> Configuration:
        try:
            encoded = password.encode("utf8") if isinstance(password, str) else password
            return Configuration(
                address,
                port,
                tls_hostname,
                Path(ca_file),
                user,
                encoded,
                database,
                space,
                capacity,
                ttl,
                operation_timeout,
                close_timeout,
            )
        except (ValueError, TypeError, OSError):
            safe(CacheConfigurationError("Invalid MySQL store configuration"))

    @staticmethod
    def _scope(namespace: str, key: str | None = None) -> str:
        try:
            if key is not None:
                cache_key_value(key)
            return namespace_value(namespace)
        except (ValueError, TypeError):
            safe(CacheValidationError("Invalid MySQL namespace or cache key"))

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        namespace = self._scope(namespace)
        try:
            if len(embedding) != self.embedding_space.dimensions:
                raise ValueError("Wrong dimensions")
            detached = tuple(embedding)
        except (TypeError, ValueError):
            safe(CacheValidationError("Invalid MySQL query embedding"))
        return await self._worker.run(
            lambda job: self._database.find(job, detached, namespace), readonly=True
        )

    async def record_hit(
        self, cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        namespace = self._scope(namespace, cache_key)
        try:
            expected = micros(expected_created_at)
        except (ValueError, TypeError, OverflowError):
            safe(CacheValidationError("Invalid MySQL expected revision"))
        return await self._worker.run(
            lambda job: self._database.record_hit(job, cache_key, namespace, expected)
        )

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        try:
            detached = entry.model_copy(deep=True)
        except AttributeError:
            safe(CacheValidationError("Invalid MySQL entry"))
        await self._worker.run(
            lambda job: self._database.put(job, detached, ttl_seconds)
        )

    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool:
        namespace = self._scope(namespace, cache_key)
        return await self._worker.run(
            lambda job: self._database.delete(job, cache_key, namespace)
        )

    async def clear(self, *, namespace: str) -> int:
        namespace = self._scope(namespace)
        return await self._worker.run(lambda job: self._database.clear(job, namespace))

    async def aclose(self) -> None:
        """Close idle ownership once; cancellation/deadline retains shared cleanup."""
        await self._worker.close()

    async def __aenter__(self) -> Self:
        self._worker.check_owner()
        self._worker.state.check_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
