import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol

from app.cache.application.service import SemanticCache
from app.cache.domain.models import CacheLookupResult
from app.providers.protocols import GenerationProvider
from app.providers.shared.responses import validate_generation_response
from app.query.api.schemas import QueryResponse
from app.query.application.coalescing import RequestCoalescer
from app.query.domain.policies import (
    DEFAULT_QUERY_CACHE_POLICY,
    QueryCachePolicy,
)

logger = logging.getLogger(__name__)


class QueryEventRecorder(Protocol):
    def record_request_started(self) -> None: ...

    def record_request_completed(
        self,
        latency_ms: float,
        *,
        failed: bool,
    ) -> None: ...

    def record_provider_call(self) -> None: ...
    def record_coalesced_delta(self, delta: int) -> None: ...


@dataclass(frozen=True, slots=True)
class _QueryResolution:
    lookup: CacheLookupResult | None
    response: str


class QueryService:
    def __init__(
        self,
        cache: SemanticCache,
        generation_provider: GenerationProvider,
        *,
        metrics: QueryEventRecorder | None = None,
    ) -> None:
        self._cache = cache
        self._generation_provider = generation_provider
        self._metrics = metrics
        self._coalescer: RequestCoalescer[_QueryResolution] = RequestCoalescer(
            None if metrics is None else metrics.record_coalesced_delta
        )

    async def execute(
        self,
        prompt: str,
        *,
        policy: QueryCachePolicy = DEFAULT_QUERY_CACHE_POLICY,
    ) -> QueryResponse:
        started_at = perf_counter()
        failed = True
        if self._metrics is not None:
            self._metrics.record_request_started()
        try:
            if policy.cache_ttl_seconds is not None and not policy.write_enabled:
                raise ValueError(
                    "cache_ttl_seconds requires a cache policy that permits writes"
                )
            effective_policy = replace(
                policy,
                cache_ttl_seconds=(
                    self._cache.resolve_ttl(policy.cache_ttl_seconds)
                    if policy.write_enabled
                    else None
                ),
            )
            coalesced = await self._coalescer.run(
                effective_policy.coalescing_key(prompt),
                lambda: self._resolve(prompt, effective_policy),
            )
            resolution = coalesced.value
            lookup = resolution.lookup
            cache_hit = lookup is not None and lookup.cache_hit
            provider_called = not cache_hit and coalesced.is_leader

            latency_ms = (perf_counter() - started_at) * 1_000
            logger.info(
                (
                    "Query completed cache_hit=%s provider_called=%s "
                    "coalesced=%s latency_ms=%.2f"
                ),
                cache_hit,
                provider_called,
                not coalesced.is_leader,
                latency_ms,
            )
            response = QueryResponse(
                response=resolution.response,
                cache_hit=cache_hit,
                similarity_score=(None if lookup is None else lookup.similarity_score),
                similarity_threshold=(
                    self._cache.similarity_threshold
                    if lookup is None
                    else lookup.similarity_threshold
                ),
                matched_prompt=None if lookup is None else lookup.matched_prompt,
                matched_cache_key=(
                    None if lookup is None else lookup.matched_cache_key
                ),
                cache_entry_created_at=(
                    None if lookup is None else lookup.cache_entry_created_at
                ),
                cache_entry_age_seconds=self._entry_age_seconds(
                    None if lookup is None else lookup.cache_entry_created_at
                ),
                generation_skipped=not provider_called,
                provider_called=provider_called,
                latency_ms=latency_ms,
            )
            failed = False
            return response
        finally:
            if self._metrics is not None:
                self._metrics.record_request_completed(
                    (perf_counter() - started_at) * 1_000,
                    failed=failed,
                )

    async def _resolve(
        self,
        prompt: str,
        policy: QueryCachePolicy,
    ) -> _QueryResolution:
        lookup = None
        if policy.read_enabled:
            lookup = await self._cache.lookup(
                prompt,
                namespace=policy.namespace,
            )

        if lookup is not None and lookup.cache_hit:
            if lookup.response is None:
                raise RuntimeError("Validated cache hit had no response")
            return _QueryResolution(lookup=lookup, response=lookup.response)

        if self._metrics is not None:
            self._metrics.record_provider_call()
        response = validate_generation_response(
            await self._generation_provider.generate(prompt)
        )

        if policy.write_enabled:
            await self._cache.store(
                prompt,
                response,
                None if lookup is None else lookup.embedding,
                namespace=policy.namespace,
                ttl_seconds=policy.cache_ttl_seconds,
            )
        return _QueryResolution(lookup=lookup, response=response)

    @staticmethod
    def _entry_age_seconds(
        created_at: datetime | None,
    ) -> float | None:
        if created_at is None:
            return None
        return max(
            0.0,
            (datetime.now(UTC) - created_at).total_seconds(),
        )
