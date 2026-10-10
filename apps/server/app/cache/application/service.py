"""Apply server matching policy through borrowed embedding and backend ports.

SemanticCache owns threshold decisions and revision-confirmed hit evidence;
the backend owns entries, expiry, capacity and store hit effects. Namespace
arguments are partition identities already authorized by HTTP callers, not
authentication credentials. Inspection and management delegate through the
server CacheBackend port rather than a second storage engine.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from app.cache.api.schemas import (
    CacheEntryListResponse,
    CacheEntryMetadata,
    CacheEntrySort,
    CacheStatsResponse,
)
from app.cache.domain.keys import prompt_cache_key
from app.cache.domain.models import CacheEntry, CacheLookupResult
from app.cache.domain.namespaces import (
    DEFAULT_CACHE_NAMESPACE,
    AuthorizedNamespaceScope,
)
from app.cache.domain.protocols import CacheBackend, CacheEventRecorder, ThresholdStore
from app.core.exceptions import CacheEntryNotFoundError
from app.providers.protocols import EmbeddingGenerator
from semantix_cache._semantics import resolve_ttl, threshold_eligible


def _preserve_prompt(prompt: str) -> str:
    return prompt


class SemanticCache:
    """Coordinate embedding lookup, confirmed reuse and explicit cache writes.

    Dependencies are borrowed and are not closed here. Optional normalization
    changes embedding text only; entries keep the application prompt. Local
    threshold state is separate from an optional shared ThresholdStore. Global
    threshold authorization belongs to the HTTP boundary, not this service.
    """

    def __init__(
        self,
        embedding_service: EmbeddingGenerator,
        backend: CacheBackend,
        similarity_threshold: float,
        *,
        prompt_normalizer: Callable[[str], str] = _preserve_prompt,
        events: CacheEventRecorder | None = None,
        threshold_store: ThresholdStore | None = None,
    ) -> None:
        """Bind borrowed ports and validate the initial process-local threshold.

        Args:
            embedding_service: Provider/service used to embed matching text.
            backend: Bound server storage, inspection and telemetry port.
            similarity_threshold: Initial local value between zero and one.
            prompt_normalizer: Synchronous matching-text transform, identity by default.
            events: Optional process-level hit/miss recorder.
            threshold_store: Optional shared authority used by async threshold operations.

        Raises:
            ValueError: The initial threshold is outside zero through one.
        """
        if not 0 <= similarity_threshold <= 1:
            raise ValueError("similarity_threshold must be between 0 and 1")

        self._embedding_service = embedding_service
        self._backend = backend
        self._similarity_threshold = similarity_threshold
        self._prompt_normalizer = prompt_normalizer
        self._events = events
        self._threshold_store = threshold_store

    @property
    def similarity_threshold(self) -> float:
        """Read the local value without consulting an injected shared threshold store."""
        return self._similarity_threshold

    def resolve_ttl(self, requested_ttl_seconds: float | None) -> float | None:
        """Validate an override and cap it by a finite backend default.

        Args:
            requested_ttl_seconds: Positive bounded TTL, or None to inherit the default.

        Returns:
            Effective TTL: the request capped by a finite default, the default when
            omitted, or None only when neither request nor backend imposes expiry.

        Raises:
            ValueError: Requested or default TTL is outside the supported range.
        """
        try:
            return resolve_ttl(requested_ttl_seconds, self._backend.default_ttl_seconds)
        except ValueError:
            raise ValueError(
                "cache_ttl_seconds is outside the supported range"
            ) from None

    def update_similarity_threshold(self, threshold: float) -> float:
        """Validate and replace only the process-local threshold.

        This does not write an injected ThresholdStore; async reads still use that
        store when present. Returns the local value or raises ValueError if invalid.
        """
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")

        self._similarity_threshold = threshold
        return self._similarity_threshold

    async def read_similarity_threshold(self) -> float:
        """Read the injected shared authority, falling back to local state.

        The shared value is not copied into the synchronous local property. Storage
        errors propagate; they are not replaced with a stale local fallback.
        """
        if self._threshold_store is not None:
            return await self._threshold_store.read_threshold()
        return self._similarity_threshold

    async def write_similarity_threshold(self, threshold: float) -> float:
        """Validate and write the shared authority, or update local state if absent.

        Shared writes do not update the local property. ValueError rejects out-of-range
        values; shared-store failures propagate. Callers enforce global-admin access.
        """
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")
        if self._threshold_store is not None:
            return await self._threshold_store.write_threshold(threshold)
        return self.update_similarity_threshold(threshold)

    async def lookup(
        self,
        prompt: str,
        *,
        namespace: str = DEFAULT_CACHE_NAMESPACE,
    ) -> CacheLookupResult:
        """Embed matching text and confirm a threshold-eligible live revision.

        Read one effective threshold, normalize for embedding and request a nearest
        candidate in the namespace. A qualifying score is only provisional: backend
        record_hit must confirm the candidate's created_at revision before reuse.
        Stale, expired, replaced or otherwise rejected candidates become misses,
        retaining only their similarity score. Backend miss accounting precedes the
        optional application miss event; confirmed backend hits precede hit events.
        Provider, confirmation and telemetry failures propagate rather than becoming
        successful hits or misses.

        Args:
            prompt: Application text; normalization changes only the embedding input.
            namespace: Already-authorized partition for candidate search/confirmation.

        Returns:
            Lookup evidence with the computed embedding. Only confirmed hits include
            response/matched identity; misses may still contain candidate similarity.
        """
        similarity_threshold = await self.read_similarity_threshold()
        matching_prompt = self._prompt_normalizer(prompt)
        embedding = [
            float(value)
            for value in await self._embedding_service.embed(matching_prompt)
        ]
        candidate = await self._backend.find_nearest(
            embedding,
            namespace=namespace,
        )

        if (
            candidate is not None
            and threshold_eligible(candidate.similarity_score, similarity_threshold)
            and await self._backend.record_hit(
                candidate.entry.cache_key,
                namespace=namespace,
                expected_created_at=candidate.entry.created_at,
            )
        ):
            if self._events is not None:
                self._events.record_cache_hit()
            return CacheLookupResult(
                cache_hit=True,
                response=candidate.entry.response,
                similarity_score=candidate.similarity_score,
                similarity_threshold=similarity_threshold,
                matched_prompt=candidate.entry.prompt,
                matched_cache_key=candidate.entry.cache_key,
                cache_entry_created_at=candidate.entry.created_at,
                embedding=embedding,
            )

        await self._backend.record_miss(namespace)
        if self._events is not None:
            self._events.record_cache_miss()
        return CacheLookupResult(
            cache_hit=False,
            response=None,
            similarity_score=(
                None if candidate is None else candidate.similarity_score
            ),
            similarity_threshold=similarity_threshold,
            matched_prompt=None,
            matched_cache_key=None,
            cache_entry_created_at=None,
            embedding=embedding,
        )

    async def store(
        self,
        prompt: str,
        response: str,
        embedding: Sequence[float] | None = None,
        *,
        namespace: str = DEFAULT_CACHE_NAMESPACE,
        ttl_seconds: float | None = None,
    ) -> bool:
        """Write a nonblank response under the namespace-aware prompt key.

        Reuse a supplied embedding or embed normalized matching text. Store the
        original application prompt with an aware timestamp; the package store may
        advance that timestamp as revision identity. The backend enforces vector
        compatibility, TTL, capacity and its storage semantics. Generation validation
        belongs to QueryService; this method is not a substitute for that boundary.

        Args:
            prompt: Original application prompt retained as entry text and key input.
            response: Response text; blank/whitespace-only content is ignored.
            embedding: Optional vector from a preceding lookup, reused without embedding.
            namespace: Already-authorized partition for the write.
            ttl_seconds: Optional TTL passed to backend enforcement/default resolution.

        Returns:
            False for blank text; True after backend put returns successfully. This is
            not a guarantee of durable persistence or indefinite retention.
        """
        if not response.strip():
            return False

        resolved_embedding = (
            await self._embedding_service.embed(self._prompt_normalizer(prompt))
            if embedding is None
            else embedding
        )
        await self._backend.put(
            CacheEntry(
                cache_key=prompt_cache_key(prompt, namespace=namespace),
                namespace=namespace,
                prompt=prompt,
                response=response,
                embedding=[float(value) for value in resolved_embedding],
                created_at=datetime.now(UTC),
            ),
            ttl_seconds=ttl_seconds,
        )
        return True

    async def clear(self, namespace: str | None = None) -> None:
        """Delegate scoped clearing; None clears all namespaces in the bound backend.

        The caller must authorize the requested scope before invoking this method.
        """
        await self._backend.clear(namespace)

    async def list_entries(
        self,
        *,
        offset: int,
        limit: int,
        namespace: str | None,
        search: str | None,
        sort: CacheEntrySort,
    ) -> CacheEntryListResponse:
        """Delegate an already-authorized observational page without confirming hits."""
        return await self._backend.list_entries(
            offset=offset,
            limit=limit,
            namespace=namespace,
            search=search,
            sort=sort,
        )

    async def get_entry(
        self,
        cache_key: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> CacheEntryMetadata:
        """Retrieve metadata within the caller-supplied authorized namespace set.

        Raises:
            CacheEntryNotFoundError: Storage returns no entry, including excluded scope.
        """
        entry = await self._backend.get_entry(
            cache_key,
            authorized_namespaces=authorized_namespaces,
        )
        if entry is None:
            raise CacheEntryNotFoundError
        return entry

    async def delete_entry(
        self,
        cache_key: str,
        *,
        authorized_namespaces: AuthorizedNamespaceScope,
    ) -> None:
        """Delegate key deletion within the caller-supplied authorized namespace set.

        Raises:
            CacheEntryNotFoundError: Storage reports no deletion, including excluded scope.
        """
        if not await self._backend.delete_entry(
            cache_key,
            authorized_namespaces=authorized_namespaces,
        ):
            raise CacheEntryNotFoundError

    async def stats(
        self,
        namespace: str | None = None,
    ) -> CacheStatsResponse:
        """Delegate scoped/global observations; these are not authoritative entry data."""
        return await self._backend.stats(namespace)
