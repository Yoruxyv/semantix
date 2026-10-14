"""Owned local-file SQLite storage. Setup is explicit; searches are bounded and exact."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from datetime import datetime
from types import TracebackType
from typing import Self

from .._semantics import cache_key_value, namespace_value
from ..errors import CacheConfigurationError, CacheStoreError, CacheValidationError
from ..models import CacheEntry, CacheMatch, EmbeddingSpace
from ._backends.sqlite.database import Database
from ._backends.sqlite.format import Configuration, micros, safe, timeout
from ._backends.sqlite.worker import Worker


class SQLiteStore:
    """CacheStore backed by a dedicated marked WAL file on trusted local disk.

    Use initialize_schema once explicitly, then connect. Each instance owns one
    connection and one worker; callers drain operations before aclose. The facade
    borrows this store. Namespace partitioning is not authorization. Every hit
    writes under SQLite's file-wide writer lock; no business operation is retried.

    Requires thread-capable SQLite >=3.51.3 except withdrawn 3.52.0. Python's linked
    runtime matters, not just its version. No additional package extra is needed.
    Capacity is 1-5,000 (default 500), dimensions 1-16,000, with capacity*D*8 <=64MiB.
    Total RSS exceeds the vector bound. Only owned ordinary files are supported.
    """

    def __init__(self, configuration: Configuration) -> None:
        self._config = configuration
        self._worker = Worker(configuration)
        self._database = Database(configuration)

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
        store = cls(configuration)
        try:
            await store._worker.run(
                lambda job: store._database.open(job, initialize=initialize),
                budget_seconds=connect_timeout,
            )
        except BaseException:
            cleanup = store._worker.start_cleanup(startup=True)
            try:
                async with asyncio.timeout(configuration.close_timeout):
                    await asyncio.shield(cleanup)
            except (asyncio.CancelledError, TimeoutError, CacheStoreError):
                pass
            raise
        return store

    @classmethod
    async def initialize_schema(
        cls,
        path: str | os.PathLike[str],
        *,
        embedding_space: EmbeddingSpace,
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
        operation_timeout_seconds: float = 30.0,
    ) -> None:
        """Create an absent dedicated file or register a binding in a valid cache.

        Never adopts unmarked files or repairs partial setup. Failed new setup
        preserves the owned partial file for diagnosis. Parent directory must
        exist and be private. Existing clients must be drained for schema changes.
        No DDL or binding registration occurs in connect or ordinary operations.
        """
        config = Configuration.create(
            path,
            embedding_space,
            max_size,
            default_ttl_seconds,
            operation_timeout_seconds,
            operation_timeout_seconds,
        )
        store = await cls._open(config, initialize=True, connect_timeout=config.timeout)
        await store.aclose()

    @classmethod
    async def connect(
        cls,
        path: str | os.PathLike[str],
        *,
        embedding_space: EmbeddingSpace,
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
        connect_timeout_seconds: float = 10.0,
        operation_timeout_seconds: float = 30.0,
        close_timeout_seconds: float = 30.0,
    ) -> Self:
        """Open an existing initialized file with an exactly matching binding policy.

        Deadlines are finite positive seconds <=86,400, including admission and
        worker completion. At most 32 operations may be admitted. Lock waits are
        capped at one second and the remaining deadline. Cancelled/timed-out work
        remains owned until cleanup finishes; a mutation may commit without its
        result reaching the caller. It is never replayed. A failed rollback faults
        the store. Close may remain tracked beyond its caller's deadline.

        TTL uses the host UTC wall clock at microsecond representation, floors
        fractional durations, expires inclusively, and never slides on hits.
        Clock rollback may extend retention. File restore requires a new embedding
        identity/cache generation to avoid historical revision reuse. Plaintext
        files/sidecars require private permissions; clear is not secure erase.
        """
        config = Configuration.create(
            path,
            embedding_space,
            max_size,
            default_ttl_seconds,
            operation_timeout_seconds,
            close_timeout_seconds,
        )
        try:
            connect_timeout = timeout(connect_timeout_seconds)
        except (ValueError, TypeError):
            safe(CacheConfigurationError("Invalid SQLite connection timeout"))
        return await cls._open(
            config, initialize=False, connect_timeout=connect_timeout
        )

    @staticmethod
    def _scope(namespace: str, key: str | None = None) -> str:
        try:
            if key is not None:
                cache_key_value(key)
            return namespace_value(namespace)
        except (ValueError, TypeError):
            safe(CacheValidationError("Invalid SQLite namespace or cache key"))

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        namespace = self._scope(namespace)
        try:
            if len(embedding) != self.embedding_space.dimensions:
                raise ValueError("Wrong dimensions")
            detached = tuple(embedding)
        except (TypeError, ValueError):
            safe(CacheValidationError("Invalid SQLite query embedding"))
        return await self._worker.run(
            lambda job: self._database.find(job, detached, namespace)
        )

    async def record_hit(
        self, cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        namespace = self._scope(namespace, cache_key)
        try:
            expected = micros(expected_created_at)
        except (ValueError, TypeError, OverflowError):
            safe(CacheValidationError("Invalid SQLite expected revision"))
        return await self._worker.run(
            lambda job: self._database.record_hit(job, cache_key, namespace, expected)
        )

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        try:
            detached = entry.model_copy(deep=True)
        except AttributeError:
            safe(CacheValidationError("Invalid SQLite entry"))
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
        """Close an idle owned store; concurrent callers share shielded cleanup.

        Busy close rejects without sealing admission. A failed/timed-out close
        never reports success or starts a second cleanup attempt.
        """
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
