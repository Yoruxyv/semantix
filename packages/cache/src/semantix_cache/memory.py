import asyncio
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from time import monotonic
from types import TracebackType
from typing import Self, cast

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
from .inspection import (
    InspectionEntry,
    InspectionPage,
    InspectionSort,
    inspection_arguments,
    inspection_namespaces,
    inspection_page,
    preview,
)
from .models import CacheEntry, CacheMatch, EmbeddingSpace


@dataclass(frozen=True)
class _Item:
    entry: CacheEntry
    expires_monotonic: float | None
    expires_at: datetime | None
    hit_count: int = 0
    last_accessed_at: datetime | None = None


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
    """Bounded process-local storage with exact float64 cosine search.

    One instance holds one embedding space; capacity and confirmed-hit LRU span
    all its namespaces. Entries and inspection counters are non-durable. The
    caller authorizes namespaces and supplies vectors from the declared space.
    Search returns detached candidates; record_hit confirms a current revision.
    Monotonic time controls expiry, while UTC expires_at is display metadata.

    Reuse the store across requests. It owns its state and numerical workers;
    async context exit calls aclose and requires idle operations and workers.
    Direct store calls have no internal operation deadline; the facade or caller
    supplies one. Cancellation cannot stop an admitted numerical thread.
    """

    def __init__(
        self,
        *,
        embedding_space: EmbeddingSpace,
        max_size: int = 500,
        default_ttl_seconds: float | None = 3600.0,
    ) -> None:
        """Create an empty store bound to a validated embedding space.

        Args:
            embedding_space: Stable identity and dimensions for all stored vectors.
            max_size: Entry capacity across namespaces, from 1 through 5,000.
                Defaults to 500; this is an entry count, not a byte budget.
            default_ttl_seconds: Positive finite retention up to 31,536,000 seconds,
                defaulting to 3,600. None permits writes without expiry.

        Raises:
            CacheConfigurationError: If the space, capacity or default TTL is invalid.
        """

        try:
            if not isinstance(cast(object, embedding_space), EmbeddingSpace):
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
        self._evictions = 0
        self._expirations = 0
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
            self._expirations += 1

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
        """Search one namespace using a detached float64 numerical snapshot.

        Search neither applies a threshold nor records a hit or promotes LRU.
        Only one numerical worker is admitted at a time. Caller cancellation
        propagates, but a started thread retains the slot until it finishes; close
        remains busy meanwhile. Scoped mutations invalidate reusable snapshots.

        Args:
            embedding: Finite, nonzero vector with the bound space's dimensions.
            namespace: Exact namespace to search; authorization is caller-owned.

        Returns:
            Nearest live candidate with score in [-1, 1], or None for an empty
            scope or a winner expired/replaced/deleted before the final recheck.
            Ties use ascending created_at, then key. A result can become stale
            afterward and must still pass record_hit before reuse as a hit.

        Raises:
            CacheValidationError: If the vector or namespace is invalid.
        """

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
        """Confirm the expected live revision and update hit metadata under the lock.

        Args:
            cache_key: Candidate key within this store.
            namespace: Exact candidate namespace.
            expected_created_at: Timezone-aware revision from the candidate entry.

        Returns:
            True after incrementing process-local hit_count, setting last access
            and promoting LRU. Revision and expiry stay unchanged. False for an
            absent, expired, foreign or replaced candidate, without hit effects.

        Raises:
            CacheValidationError: If key, namespace or revision is invalid.
        """

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
                self._items[key] = replace(
                    item,
                    hit_count=item.hit_count + 1,
                    last_accessed_at=datetime.now(UTC),
                )
                self._items.move_to_end(key)
                return True

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        """Store a detached normalized entry and enforce cross-namespace capacity.

        Replacement resets hit metadata and TTL, promotes LRU and advances the
        created_at revision when needed. Revision history survives delete/clear.
        Expired entries are purged before the least recently used entries are
        evicted to enforce capacity. Hits never renew retention.

        Args:
            entry: Valid CacheEntry from this embedding space. Dimensions are
                checked, but entries have no identity tag to verify provenance.
            ttl_seconds: None inherits the default; a positive finite value up to
                31,536,000 seconds is capped by a finite default. Both values None
                mean no expiry. TTL starts at this write's monotonic time.

        Raises:
            CacheStoreError: If the entry, vector dimensions or TTL is invalid.
        """

        with self._state.operation():
            try:
                if not isinstance(cast(object, entry), CacheEntry):
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
                    self._evictions += 1

    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool:
        """Remove a live key only if its namespace matches.

        Returns:
            True if removed; False if absent, expired or outside the namespace.
            Expired entries are purged first; revision history is retained.

        Raises:
            CacheValidationError: If the key or namespace is invalid.
        """

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
        """Remove this namespace's live entries without resetting revision history.

        Returns:
            Number removed from the namespace after expired entries are purged.
            Other namespaces' live entries are preserved.

        Raises:
            CacheValidationError: If the namespace is invalid.
        """

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

    def _inspection_entry(
        self, item: _Item, rank: int, *, observed_at: float, include_response: bool
    ) -> InspectionEntry:
        return InspectionEntry(
            cache_key=item.entry.cache_key,
            namespace=item.entry.namespace,
            prompt=item.entry.prompt,
            response_preview=preview(item.entry.response),
            response_preview_truncated=len(item.entry.response) > 240,
            response=item.entry.response if include_response else None,
            created_at=item.entry.created_at,
            expires_at=item.expires_at,
            remaining_ttl_seconds=None
            if item.expires_monotonic is None
            else max(0.0, item.expires_monotonic - observed_at),
            hit_count=item.hit_count,
            last_accessed_at=item.last_accessed_at,
            recency_rank=rank,
        )

    async def inspect_entries(
        self,
        *,
        namespace: str | None = None,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
        sort: InspectionSort = "newest",
    ) -> InspectionPage:
        """Observe live metadata without purging entries or changing hits/LRU.

        This optional API scans bounded memory. Prompts and 240-character response
        previews remain sensitive; the caller authorizes the requested scope.

        Args:
            namespace: Exact namespace, or None for all namespaces in this store.
            offset: Nonnegative live offset; concurrent changes can shift pages.
            limit: Page size from 1 through 100.
            search: Optional prompt substring, trimmed and casefolded, at most
                2,000 characters. Blank text leaves results unfiltered.
            sort: newest, oldest, most_hit or nearest_expiry.

        Returns:
            Detached page without vectors and with response=None. Counts, remaining
            TTL and process-local hit/access metadata describe this observation.

        Raises:
            CacheValidationError: If pagination, scope, search or sort is invalid.
        """

        with self._state.operation():
            inspection_arguments(namespace, offset, limit, search, sort)
            async with self._lock:
                now = monotonic()
                items = [
                    item
                    for item in reversed(self._items.values())
                    if (item.expires_monotonic is None or item.expires_monotonic > now)
                    and (namespace is None or item.entry.namespace == namespace)
                ]
                metadata = [
                    self._inspection_entry(
                        item, rank, observed_at=now, include_response=False
                    )
                    for rank, item in enumerate(items, 1)
                ]
                return inspection_page(
                    metadata, offset=offset, limit=limit, search=search, sort=sort
                )

    async def inspect_entry(
        self, cache_key: str, *, namespaces: tuple[str, ...] | None
    ) -> InspectionEntry | None:
        """Observe one live entry, including its sensitive full response.

        Args:
            cache_key: Canonical key to inspect.
            namespaces: Caller-authorized namespace tuple; () allows none and
                None allows every namespace in this store. This is a filter,
                not authentication.

        Returns:
            Detached detail or None if absent, expired or outside the scope.
            This neither purges entries nor confirms a hit or changes LRU.

        Raises:
            CacheValidationError: If the key or namespace scope is invalid.
        """

        with self._state.operation():
            try:
                key = cache_key_value(cache_key)
            except ValueError:
                raise CacheValidationError("Invalid inspection key") from None
            inspection_namespaces(namespaces)
            async with self._lock:
                now = monotonic()
                live = (
                    item
                    for item in reversed(self._items.values())
                    if (item.expires_monotonic is None or item.expires_monotonic > now)
                    and (namespaces is None or item.entry.namespace in namespaces)
                )
                for rank, item in enumerate(live, 1):
                    if item.entry.cache_key == key:
                        return self._inspection_entry(
                            item, rank, observed_at=now, include_response=True
                        )
                return None

    async def clear_all(self) -> int:
        """Administratively remove live entries across this store's namespaces.

        Returns:
            Number removed after expiry cleanup. Revision history and lifetime
            removal counters remain. Authorization belongs to the caller; this
            optional mutation is outside the mandatory CacheStore protocol.
        """
        with self._state.operation():
            async with self._lock:
                self._purge()
                count = len(self._items)
                self._items.clear()
                self._snapshots.clear()
                return count

    @property
    def inspection_events(self) -> tuple[int, int]:
        """Process-local observed removals; not cache authority."""
        return self._evictions, self._expirations

    async def aclose(self) -> None:
        """Close an idle store and discard its entries and retained snapshots.

        Repeated close is harmless; later operations raise CacheClosedError.
        This does not wait for or cancel work. Async context exit uses this same
        close path and propagates body exceptions when close succeeds.

        Raises:
            CacheBusyError: If admitted operations or numerical workers remain;
                the store stays open so the caller can drain work and retry.
        """

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
