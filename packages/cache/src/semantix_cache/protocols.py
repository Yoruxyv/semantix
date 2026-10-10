"""Structural extension contracts; applications own their implementations.

GenerationCallable is the async prompt-to-completed-text type used by resolve.
Supply an async function or an object with async __call__; synchronous factories
that only return awaitables are not accepted by the facade. Generation receives
the canonical prompt before optional matching normalization. The application owns
context, credentials, output approval and any dependencies. Callback exceptions
propagate unchanged; invalid returned text is a GenerationError.

Optional coalescing requires the exact same callable object and an explicit key
attesting to immutable generation inputs. Callable identity alone cannot prove
context equivalence; rotate the key for changed closures, ContextVars, permissions,
model or tool inputs. Bind a method once if calls are intended to share it. See
AsyncSemanticCache.resolve for the complete identity and cancellation contract.
"""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Protocol, TypeAlias

from .models import CacheEntry, CacheMatch, EmbeddingSpace

GenerationCallable: TypeAlias = Callable[[str], Awaitable[str]]


class EmbeddingAdapter(Protocol):
    """Application-owned async embeddings in one stable vector space.

    No inheritance is required. Identity must distinguish model/revision,
    preprocessing and pooling so all vectors in a space are compatible; equal
    dimensions alone are insufficient. The facade borrows this adapter and does
    not close it or its clients. Implementations own their failure handling and
    should propagate cancellation.
    """

    @property
    def embedding_space(self) -> EmbeddingSpace:
        """Return valid identity/dimensions that remain stable during facade use."""
        ...

    async def embed(self, text: str) -> Sequence[float]:
        """Embed canonical matching text asynchronously.

        Args:
            text: Valid prompt after the facade's optional matching normalization.

        Returns:
            Finite, nonzero numeric vector with exactly embedding_space.dimensions
            components. The facade normalizes it for cosine matching.
        """
        ...


class CacheStore(Protocol):
    """Structural authoritative storage for one embedding space.

    Implementations need no subclass or registry. Isolate entries by both space
    identity/dimensions and namespace, and validate vectors against the binding.
    Namespaces are partitions, not authentication. Candidates must be detached
    snapshots; a threshold decision alone does not confirm a hit.

    Stores own expiry, revision allocation, capacity and LRU state. Never reuse
    a revision after deletion/clear/reinsertion within a binding. Resource owners
    initialize and close the store; the facade only borrows it. Transaction,
    durability, timeout, cancellation and owned/borrowed resource details remain
    backend-specific. Failures must stay errors rather than becoming misses.

    Optional inspection, clear_all and backend diagnostics are not members of
    this protocol. See docs/cache-store-conformance.md for the source-based kit
    and the limits of its evidence.
    """

    @property
    def embedding_space(self) -> EmbeddingSpace:
        """Return the stable identity and dimensions used to isolate this binding."""
        ...

    @property
    def default_ttl_seconds(self) -> float | None:
        """Return None for no default expiry, or a finite TTL in (0, 31,536,000].

        Per-write None inherits this default; explicit TTLs cannot extend it.
        """
        ...

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        """Find a detached nearest candidate without applying a facade threshold.

        Args:
            embedding: Finite, nonzero vector compatible with the bound space.
            namespace: Exact namespace to search; never return foreign entries.

        Returns:
            Nearest live candidate with cosine score in [-1, 1], or None if none
            is available. It can become stale/expired before record_hit. Search
            does not count a hit or promote LRU order; expiry cleanup is allowed.
        """
        ...

    async def record_hit(
        self, cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        """Atomically confirm a live revision and apply successful-hit effects.

        Args:
            cache_key: Candidate key to confirm within the bound embedding space.
            namespace: Candidate namespace; a foreign entry must not confirm.
            expected_created_at: Timezone-aware revision from candidate.entry.

        Returns:
            True only for the same current, unexpired revision. Success promotes
            LRU order and updates hit/access metadata where exposed, without
            extending TTL. False rejects absent, expired, foreign or replaced
            candidates without applying successful-hit effects.
        """
        ...

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        """Write a validated detached entry, replacing its key within the binding.

        Assign an increasing created_at revision, reset expiry and any exposed
        hit metadata, and promote LRU order subject to capacity. Reusing the same
        input entry must not reuse an old revision, including after delete/clear.

        Args:
            entry: Valid payload/key/namespace with a vector matching this space's
                dimensions. Keep caller-owned models detached from stored state.
            ttl_seconds: None inherits default_ttl_seconds. A positive finite TTL
                up to 31,536,000 seconds can shorten but not extend a finite
                default. Both values None permit no expiry; hits never renew it.
        """
        ...

    async def delete_entry(self, cache_key: str, *, namespace: str) -> bool:
        """Remove only this key in the given namespace and bound embedding space.

        Returns:
            True if an entry was removed; False if none was available in scope.
        """
        ...

    async def clear(self, *, namespace: str) -> int:
        """Clear only this namespace within the bound embedding space.

        Returns:
            Nonnegative removal count under the backend's expiry-cleanup rules.
            Revision allocation must survive this operation.
        """
        ...

    async def aclose(self) -> None:
        """Close an idle store and release owned resources, leaving borrowed ones.

        Successful close is idempotent; subsequent storage operations must reject
        closed state. Drain admitted work first. Pending-work checks and cleanup
        failure/cancellation details belong to the backend's documented contract.
        """
        ...
