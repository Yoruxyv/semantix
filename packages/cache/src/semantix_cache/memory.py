import asyncio
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import monotonic
from types import TracebackType
from typing import Self

import numpy as np
from numpy.typing import NDArray

from ._lifecycle import Lifecycle
from ._semantics import (
    MAX_MEMORY_CACHE_SIZE,
    cache_key_value,
    namespace_value,
    normalized_vector,
    resolve_ttl,
)
from .errors import CacheConfigurationError, CacheStoreError, CacheValidationError
from .models import CacheEntry, CacheMatch, EmbeddingSpace


@dataclass(frozen=True)
class _Item:
    entry: CacheEntry
    expires_monotonic: float | None
    expires_at: datetime | None


@dataclass
class _Snapshot:
    """Detached candidates with a lazily built, owned float64 matrix.

    Only the admitted numerical worker prepares this snapshot. Once prepared,
    its (N, D) C-contiguous matrix is read-only and keeps the exact stored tuple
    values and revision/key ordering. Reusing it avoids Python-float conversion
    on repeated searches. The first search leaves the matrix worker-local; only
    reuse retains 8*N*D bytes until a scoped mutation invalidates it, avoiding
    retained buffers for write-heavy scopes. A running worker can retain an
    invalidated snapshot until it drains.

    Row norms use the original float64 reduction over stored values; normalized
    tuples are not assumed to have an exactly unit norm. Read-only (N,) norms
    retain another 8*N bytes and avoid repeating the (N, D) square temporary on
    unchanged scopes. First-use allocation still includes matrix/norm creation.
    """

    items: tuple[_Item, ...] = field(repr=False)
    matrix: NDArray[np.float64] | None = field(default=None, repr=False)
    norms: NDArray[np.float64] | None = field(default=None, repr=False)
    used: bool = False

    def prepare(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        if self.matrix is None or self.norms is None:
            items = tuple(
                sorted(
                    self.items,
                    key=lambda item: (item.entry.created_at, item.entry.cache_key),
                )
            )
            matrix = np.asarray(
                [item.entry.embedding for item in items], dtype=np.float64
            )
            matrix.setflags(write=False)
            norms = np.linalg.norm(matrix, axis=1)
            norms.setflags(write=False)
            self.items = items
            if self.used:
                self.matrix = matrix
                self.norms = norms
            self.used = True
            return matrix, norms
        return self.matrix, self.norms


def _nearest(
    query: NDArray[np.float64], items: tuple[_Item, ...] | _Snapshot
) -> CacheMatch:
    snapshot = _Snapshot(items) if isinstance(items, tuple) else items
    matrix, norms = snapshot.prepare()
    # Reuse candidate norms while preserving the original float64 arithmetic.
    if np.any(norms <= np.finfo(np.float64).eps):
        raise ValueError("Embedding has zero or invalid magnitude")
    scores = (matrix @ query) / (norms * float(np.linalg.norm(query)))
    index = int(np.argmax(scores))
    score = max(-1.0, min(1.0, float(scores[index])))
    return CacheMatch(
        entry=snapshot.items[index].entry,
        similarity_score=score,
        expires_at=snapshot.items[index].expires_at,
    )


class MemoryStore:
    """Bounded process memory, exact cosine matching and cross-namespace LRU."""

    def __init__(
        self,
        *,
        embedding_space: EmbeddingSpace,
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
    ) -> None:
        try:
            if not isinstance(embedding_space, EmbeddingSpace):
                raise CacheConfigurationError("Invalid memory store configuration")
            self._space = EmbeddingSpace.model_validate(embedding_space.model_dump())
            if (
                isinstance(max_size, bool)
                or not isinstance(max_size, int)
                or not 1 <= max_size <= MAX_MEMORY_CACHE_SIZE
            ):
                raise ValueError("Invalid capacity")
            self._ttl = resolve_ttl(None, default_ttl_seconds)
        except ValueError:
            raise CacheConfigurationError(
                "Invalid memory store configuration"
            ) from None
        self._max_size = max_size
        self._items: OrderedDict[str, _Item] = OrderedDict()
        self._snapshots: dict[str, _Snapshot] = {}
        self._last_revision: datetime | None = None
        self._lock = asyncio.Lock()
        self._slot = asyncio.Semaphore(1)
        self._workers: set[asyncio.Task[CacheMatch]] = set()
        self._state = Lifecycle()

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self._space

    @property
    def default_ttl_seconds(self) -> float | None:
        return self._ttl

    def _discard(self, key: str) -> None:
        item = self._items.pop(key)
        self._snapshots.pop(item.entry.namespace, None)

    def _purge(self) -> None:
        now = monotonic()
        for key in [
            key
            for key, item in self._items.items()
            if item.expires_monotonic is not None and now >= item.expires_monotonic
        ]:
            self._discard(key)

    @staticmethod
    def _scope(cache_key: str, namespace: str) -> tuple[str, str]:
        try:
            return cache_key_value(cache_key), namespace_value(namespace)
        except ValueError:
            raise CacheValidationError("Invalid cache key or namespace") from None

    def _worker_done(self, worker: asyncio.Task[CacheMatch]) -> None:
        self._workers.remove(worker)
        self._slot.release()
        # Retrieve errors even when the caller was cancelled. Awaiters still see them.
        if not worker.cancelled():
            worker.exception()

    async def find_nearest(
        self,
        embedding: Sequence[float],
        *,
        namespace: str,
    ) -> CacheMatch | None:
        with self._state.operation():
            try:
                namespace = namespace_value(namespace)
                query = normalized_vector(embedding, dimensions=self._space.dimensions)
            except ValueError:
                raise CacheValidationError(
                    "Invalid query vector or namespace"
                ) from None
            await self._slot.acquire()
            worker: asyncio.Task[CacheMatch] | None = None
            try:
                async with self._lock:
                    self._purge()
                    snapshot = self._snapshots.get(namespace)
                    if snapshot is None:
                        items = tuple(
                            item
                            for item in self._items.values()
                            if item.entry.namespace == namespace
                        )
                        if not items:
                            return None
                        snapshot = _Snapshot(items)
                        self._snapshots[namespace] = snapshot
                worker = asyncio.create_task(
                    asyncio.to_thread(_nearest, query, snapshot)
                )
                self._workers.add(worker)
                worker.add_done_callback(self._worker_done)
                match = await asyncio.shield(worker)
            finally:
                # A running numerical worker owns the slot, including cancellation.
                if worker is None:
                    self._slot.release()
            async with self._lock:
                self._purge()
                current = self._items.get(match.entry.cache_key)
                if (
                    current is None
                    or current.entry.created_at != match.entry.created_at
                ):
                    return None
            return match

    async def record_hit(
        self,
        cache_key: str,
        *,
        namespace: str,
        expected_created_at: datetime,
    ) -> bool:
        with self._state.operation():
            key, namespace = self._scope(cache_key, namespace)
            if (
                not isinstance(expected_created_at, datetime)
                or expected_created_at.tzinfo is None
            ):
                raise CacheValidationError("Expected revision must be timezone-aware")
            async with self._lock:
                self._purge()
                item = self._items.get(key)
                if (
                    item is None
                    or item.entry.namespace != namespace
                    or item.entry.created_at != expected_created_at
                ):
                    return False
                self._items.move_to_end(key)
                return True

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        with self._state.operation():
            try:
                if not isinstance(entry, CacheEntry):
                    raise CacheStoreError("Invalid stored entry")
                entry = CacheEntry.model_validate(entry.model_dump())
                embedding = normalized_vector(
                    entry.embedding, dimensions=self._space.dimensions
                )
                ttl = resolve_ttl(ttl_seconds, self._ttl)
            except ValueError:
                raise CacheStoreError("Invalid stored entry or TTL") from None
            async with self._lock:
                self._purge()
                revision = entry.created_at
                if self._last_revision is not None and revision <= self._last_revision:
                    revision = self._last_revision + timedelta(microseconds=1)
                self._last_revision = revision
                entry = entry.model_copy(
                    update={
                        "created_at": revision,
                        "embedding": tuple(float(value) for value in embedding),
                    }
                )
                now = monotonic()
                previous = self._items.get(entry.cache_key)
                if previous is not None:
                    self._snapshots.pop(previous.entry.namespace, None)
                self._snapshots.pop(entry.namespace, None)
                self._items[entry.cache_key] = _Item(
                    entry=entry,
                    expires_monotonic=None if ttl is None else now + ttl,
                    expires_at=None
                    if ttl is None
                    else datetime.now(UTC) + timedelta(seconds=ttl),
                )
                self._items.move_to_end(entry.cache_key)
                while len(self._items) > self._max_size:
                    self._discard(next(iter(self._items)))

    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool:
        with self._state.operation():
            key, namespace = self._scope(cache_key, namespace)
            async with self._lock:
                self._purge()
                item = self._items.get(key)
                if item is None or item.entry.namespace != namespace:
                    return False
                self._discard(key)
                return True

    async def clear(self, *, namespace: str) -> int:
        with self._state.operation():
            try:
                namespace = namespace_value(namespace)
            except ValueError:
                raise CacheValidationError("Invalid namespace") from None
            async with self._lock:
                self._purge()
                keys = [
                    key
                    for key, item in self._items.items()
                    if item.entry.namespace == namespace
                ]
                for key in keys:
                    self._discard(key)
                return len(keys)

    async def aclose(self) -> None:
        self._state.close(workers=bool(self._workers))
        self._items.clear()
        self._snapshots.clear()

    async def __aenter__(self) -> Self:
        self._state.check_open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
