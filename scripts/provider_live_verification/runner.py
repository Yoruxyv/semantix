"""Observed cache verification, owned resource cleanup and task inspection."""

from __future__ import annotations

import asyncio
import platform
from collections.abc import Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from typing_extensions import override

from semantix_cache import (
    AsyncSemanticCache,
    CacheBusyError,
    CacheEntry,
    CacheStoreError,
    EmbeddingSpace,
    SemantixCacheError,
)
from semantix_cache.memory import MemoryStore

from .models import Failure, Options, Receipt, Result, Source, reject_secret_metadata
from .providers import BoundedTransport, EmbeddingResource, GenerationResource, adapters

CLEANUP_TIMEOUT = 5.0


PROMPT = "Reply with just the word OK."


NAMESPACE = "provider-verifier"


@dataclass
class Counts:
    embedding_calls: int = 0
    generation_calls: int = 0
    cache_writes: int = 0
    confirmed_hits: int = 0
    first_resolve_miss: bool = False
    second_generation_skipped: bool = False
    response_equal: bool = False
    ownership_verified: bool = False


class CountedEmbedding:
    def __init__(self, adapter: EmbeddingResource, counts: Counts) -> None:
        self.adapter, self.counts = adapter, counts

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self.adapter.embedding_space

    async def embed(self, text: str) -> Sequence[float]:
        self.counts.embedding_calls += 1
        return await self.adapter.embed(text)


class CountedStore(MemoryStore):
    def __init__(self, space: EmbeddingSpace, counts: Counts) -> None:
        super().__init__(embedding_space=space, max_size=2)
        self.counts = counts

    @override
    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        await super().put(entry, ttl_seconds=ttl_seconds)
        self.counts.cache_writes += 1

    @override
    async def record_hit(
        self,
        cache_key: str,
        *,
        namespace: str,
        expected_created_at: datetime,
    ) -> bool:
        confirmed = await super().record_hit(
            cache_key,
            namespace=namespace,
            expected_created_at=expected_created_at,
        )
        self.counts.confirmed_hits += int(confirmed)
        return confirmed


async def close_resource(
    resource: EmbeddingResource | GenerationResource | MemoryStore | AsyncSemanticCache,
) -> None:
    # Bounded cleanup-only drain; never retries HTTP or replays generation.
    for _ in range(50):
        try:
            await resource.aclose()
        except CacheBusyError:
            await asyncio.sleep(0.02)
        else:
            return
    raise CacheBusyError("Verifier resource did not drain")


async def cache_flow(
    cache: AsyncSemanticCache,
    generator: GenerationResource,
    counts: Counts,
) -> None:
    async def generate(prompt: str) -> str:
        counts.generation_calls += 1
        return await generator.generate(prompt)

    first = await cache.resolve(PROMPT, generate=generate, namespace=NAMESPACE)
    counts.first_resolve_miss = (
        not first.cache_hit
        and first.provider_called
        and not first.generation_skipped
        and first.cache_written
        and first.matched_cache_key is None
        and first.similarity_score is None
    )
    before = counts.generation_calls
    second = await cache.resolve(PROMPT, generate=generate, namespace=NAMESPACE)
    counts.second_generation_skipped = (
        second.cache_hit
        and second.generation_skipped
        and not second.provider_called
        and not second.cache_written
        and counts.generation_calls == before
        and second.matched_cache_key is not None
    )
    counts.response_equal = first.response == second.response
    if not (
        counts.first_resolve_miss
        and counts.second_generation_skipped
        and counts.response_equal
        and (
            counts.embedding_calls,
            counts.generation_calls,
            counts.cache_writes,
            counts.confirmed_hits,
        )
        == (2, 1, 1, 1)
    ):
        raise CacheStoreError("Verifier semantic assertion failed")


async def run_smoke(
    options: Options,
    key: str,
    source: Source,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Receipt:
    """Expected failures yield sanitized evidence; defects and cancellation propagate."""
    reject_secret_metadata(key, (options.model_dump_json(), source.model_dump_json()))
    deadline = asyncio.get_running_loop().time() + options.timeout
    baseline = asyncio.all_tasks()
    counts = Counts()
    request_timeout = min(15.0, (options.timeout - CLEANUP_TIMEOUT) / 3)
    bounded = BoundedTransport(
        options.provider,
        options.max_attempts,
        transport
        if transport is not None
        else httpx.AsyncHTTPTransport(
            retries=0,
            trust_env=False,
            limits=httpx.Limits(max_connections=1),
        ),
    )
    stack = AsyncExitStack()
    client = httpx.AsyncClient(
        transport=bounded,
        trust_env=False,
        follow_redirects=False,
        timeout=request_timeout,
    )
    stack.push_async_callback(client.aclose)
    result: Result = "FAIL"
    failure: Failure = "none"
    cleanup = True
    try:
        async with asyncio.timeout(
            max(0.0, deadline - CLEANUP_TIMEOUT - asyncio.get_running_loop().time())
        ):
            embedder, generator = adapters(options, client, key, request_timeout)
            stack.push_async_callback(close_resource, generator)
            stack.push_async_callback(close_resource, embedder)
            store = CountedStore(embedder.embedding_space, counts)
            stack.push_async_callback(close_resource, store)
            cache = AsyncSemanticCache(
                embedder=CountedEmbedding(embedder, counts),
                store=store,
                operation_timeout_seconds=options.timeout - CLEANUP_TIMEOUT,
            )
            stack.push_async_callback(close_resource, cache)
            await cache_flow(cache, generator, counts)
            # Closing the facade leaves its borrowed store usable.
            await cache.aclose()
            if await store.clear(namespace=NAMESPACE) != 1 or client.is_closed:
                raise CacheStoreError("Verifier ownership assertion failed")
            await embedder.aclose()
            await generator.aclose()
            counts.ownership_verified = not client.is_closed
            result = "PASS"
    except TimeoutError:
        failure = "deadline"
    except SemantixCacheError:
        result = "UNAVAILABLE" if bounded.unavailable else "FAIL"
        failure = "provider_error"
    finally:
        try:
            async with asyncio.timeout(
                max(
                    0.0,
                    min(CLEANUP_TIMEOUT, deadline - asyncio.get_running_loop().time()),
                )
            ):
                await stack.aclose()
        except (TimeoutError, SemantixCacheError, httpx.HTTPError):
            cleanup = False
    remaining = len(asyncio.all_tasks() - baseline)
    if not cleanup or not client.is_closed:
        result, failure = "FAIL", "cleanup"
    elif remaining:
        result, failure = "FAIL", "task_leak"
    receipt = Receipt(
        **source.model_dump(),
        challenge=options.challenge,
        provider=options.provider,
        api_source="local-first-party"
        if options.provider == "ollama"
        else "first-party",
        adapter_path=f"semantix_cache.adapters.{options.provider}",
        utc_timestamp=datetime.now(UTC),
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} {platform.machine()}",
        model=options.model,
        embedding_model=options.embedding_model,
        embedding_dimensions=options.embedding_dimensions,
        embedding_source="deterministic-local"
        if options.provider == "anthropic"
        else "first-party",
        model_overridden=options.model_overridden,
        embedding_overridden=options.embedding_overridden,
        max_http_attempts=options.max_attempts,
        total_timeout_seconds=options.timeout,
        request_timeout_seconds=request_timeout,
        http_attempts=bounded.attempts,
        http_status_category=bounded.status,
        **vars(counts),
        retry_count=0,
        cleanup_status="complete" if cleanup and client.is_closed else "failed",
        remaining_async_tasks=remaining,
        result=result,
        failure_category=failure,
    )
    reject_secret_metadata(key, (receipt.model_dump_json(),))
    return receipt
