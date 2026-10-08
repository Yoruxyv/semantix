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
        return self._similarity_threshold

    def resolve_ttl(self, requested_ttl_seconds: float | None) -> float | None:
        try:
            return resolve_ttl(requested_ttl_seconds, self._backend.default_ttl_seconds)
        except ValueError:
            raise ValueError(
                "cache_ttl_seconds is outside the supported range"
            ) from None

    def update_similarity_threshold(self, threshold: float) -> float:
        if not 0 <= threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")

        self._similarity_threshold = threshold
        return self._similarity_threshold

    async def read_similarity_threshold(self) -> float:
        if self._threshold_store is not None:
            return await self._threshold_store.read_threshold()
        return self._similarity_threshold

    async def write_similarity_threshold(self, threshold: float) -> float:
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
        if not await self._backend.delete_entry(
            cache_key,
            authorized_namespaces=authorized_namespaces,
        ):
            raise CacheEntryNotFoundError

    async def stats(
        self,
        namespace: str | None = None,
    ) -> CacheStatsResponse:
        return await self._backend.stats(namespace)
