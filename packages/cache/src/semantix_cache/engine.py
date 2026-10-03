import asyncio
import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from types import TracebackType
from typing import Self

from ._lifecycle import Lifecycle
from ._semantics import (
    cache_key_value,
    canonical_prompt,
    finite_number,
    namespace_value,
    normalized_vector,
    prompt_cache_key,
    resolve_flow,
    resolve_ttl,
    threshold_eligible,
    valid_response,
    validate_ttl_policy,
)
from .errors import (
    CacheConfigurationError,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    EmbeddingError,
    EmbeddingSpaceError,
    GenerationError,
)
from .models import CacheEntry, CacheHit, CacheMatch, CacheResult, EmbeddingSpace
from .policies import CachePolicy
from .protocols import CacheStore, EmbeddingAdapter, GenerationCallable


@dataclass(frozen=True)
class _Lookup:
    embedding: tuple[float, ...] = field(repr=False)
    score: float | None
    hit: CacheHit | None


class AsyncSemanticCache:
    def __init__(
        self,
        *,
        embedder: EmbeddingAdapter,
        store: CacheStore,
        similarity_threshold: float = 0.92,
        prompt_normalizer: Callable[[str], str] | None = None,
        operation_timeout_seconds: float = 30.0,
    ) -> None:
        try:
            self._threshold = finite_number(
                similarity_threshold, minimum=0.0, maximum=1.0
            )
            self._timeout = finite_number(
                operation_timeout_seconds, minimum=0.0, maximum=float("inf")
            )
            if self._timeout == 0:
                raise ValueError("Operation timeout must be positive")
            if prompt_normalizer is not None and not callable(prompt_normalizer):
                raise ValueError("Prompt normalizer must be callable")
            resolve_ttl(None, store.default_ttl_seconds)
        except ValueError:
            raise CacheConfigurationError("Invalid cache configuration") from None
        self._embedder = embedder
        self._store = store
        self._normalizer = prompt_normalizer
        self._space = self._checked_space()
        self._state = Lifecycle()

    @property
    def similarity_threshold(self) -> float:
        return self._threshold

    def _checked_space(self) -> EmbeddingSpace:
        embed_space, store_space = (
            self._embedder.embedding_space,
            self._store.embedding_space,
        )
        if (
            not isinstance(embed_space, EmbeddingSpace)
            or not isinstance(store_space, EmbeddingSpace)
            or embed_space != store_space
        ):
            raise EmbeddingSpaceError("Embedding and store spaces must match")
        try:
            return EmbeddingSpace.model_validate(embed_space.model_dump())
        except ValueError:
            raise EmbeddingSpaceError("Embedding space metadata is invalid") from None

    def _check_space(self) -> None:
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            # Do not accept completed output from an integration that swallowed
            # the operation's cancellation/deadline signal.
            raise asyncio.CancelledError
        if self._checked_space() != self._space:
            raise EmbeddingSpaceError("Embedding space changed after construction")

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[None]:
        with self._state.operation():
            self._check_space()
            deadline = asyncio.timeout(self._timeout)
            try:
                async with deadline:
                    yield
            except TimeoutError:
                if deadline.expired():
                    raise CacheTimeoutError("Cache operation timed out") from None
                raise

    @staticmethod
    def _inputs(prompt: str, namespace: str) -> tuple[str, str]:
        try:
            return canonical_prompt(prompt), namespace_value(namespace)
        except ValueError:
            raise CacheValidationError("Invalid prompt or namespace") from None

    def _ttl(self, ttl: float | None, *, write_enabled: bool = True) -> float | None:
        try:
            validate_ttl_policy(ttl, write_enabled=write_enabled)
            return resolve_ttl(ttl, self._store.default_ttl_seconds)
        except ValueError:
            raise CacheValidationError("Invalid TTL or cache policy") from None

    async def _embed(self, prompt: str) -> tuple[float, ...]:
        matching = prompt if self._normalizer is None else self._normalizer(prompt)
        try:
            matching = canonical_prompt(matching)
        except ValueError:
            raise CacheValidationError(
                "Normalizer returned invalid matching text"
            ) from None
        output = await self._embedder.embed(matching)
        self._check_space()
        try:
            return tuple(
                float(value)
                for value in normalized_vector(
                    output, dimensions=self._space.dimensions
                )
            )
        except ValueError:
            raise EmbeddingError("Embedding output is invalid") from None

    async def _lookup(self, prompt: str, namespace: str) -> _Lookup:
        embedding = await self._embed(prompt)
        match = await self._store.find_nearest(embedding, namespace=namespace)
        self._check_space()
        if match is None:
            return _Lookup(embedding, None, None)
        try:
            if not isinstance(match, CacheMatch):
                raise CacheStoreError("Store returned an invalid candidate")
            match = CacheMatch.model_validate(match.model_dump())
            normalized_vector(match.entry.embedding, dimensions=self._space.dimensions)
            if match.entry.namespace != namespace:
                raise ValueError("Store returned a foreign namespace")
        except ValueError:
            raise CacheStoreError("Store returned an invalid candidate") from None
        # Expiry is authoritative in the store's atomic confirmation: memory uses
        # monotonic time, while UTC expires_at is metadata, not another deadline.
        if not threshold_eligible(match.similarity_score, self._threshold):
            return _Lookup(embedding, match.similarity_score, None)
        confirmed = await self._store.record_hit(
            match.entry.cache_key,
            namespace=namespace,
            expected_created_at=match.entry.created_at,
        )
        self._check_space()
        if not isinstance(confirmed, bool):
            raise CacheStoreError("Store returned invalid hit confirmation")
        if not confirmed:
            return _Lookup(embedding, match.similarity_score, None)
        hit = CacheHit(
            response=match.entry.response,
            similarity_score=match.similarity_score,
            similarity_threshold=self._threshold,
            matched_prompt=match.entry.prompt,
            matched_cache_key=match.entry.cache_key,
            cache_entry_created_at=match.entry.created_at,
            cache_entry_age_seconds=max(
                0.0, (datetime.now(UTC) - match.entry.created_at).total_seconds()
            ),
            expires_at=match.expires_at,
        )
        return _Lookup(embedding, match.similarity_score, hit)

    async def _write(
        self,
        prompt: str,
        response: str,
        namespace: str,
        ttl: float | None,
        embedding: tuple[float, ...] | None = None,
    ) -> str:
        if embedding is None:
            embedding = await self._embed(prompt)
        self._check_space()
        key = prompt_cache_key(prompt, namespace=namespace)
        await self._store.put(
            CacheEntry(
                cache_key=key,
                namespace=namespace,
                prompt=prompt,
                response=response,
                embedding=embedding,
                created_at=datetime.now(UTC),
            ),
            ttl_seconds=ttl,
        )
        self._check_space()
        return key

    async def get(self, prompt: str, *, namespace: str = "default") -> CacheHit | None:
        async with self._operation():
            prompt, namespace = self._inputs(prompt, namespace)
            return (await self._lookup(prompt, namespace)).hit

    async def set(
        self,
        prompt: str,
        response: str,
        *,
        namespace: str = "default",
        cache_ttl_seconds: float | None = None,
    ) -> str:
        async with self._operation():
            prompt, namespace = self._inputs(prompt, namespace)
            ttl = self._ttl(cache_ttl_seconds)
            try:
                response = valid_response(response)
            except ValueError:
                raise CacheValidationError("Invalid response") from None
            return await self._write(prompt, response, namespace, ttl)

    async def resolve(
        self,
        prompt: str,
        *,
        generate: GenerationCallable,
        namespace: str = "default",
        policy: CachePolicy = CachePolicy.NORMAL,
        cache_ttl_seconds: float | None = None,
    ) -> CacheResult:
        started = perf_counter()
        async with self._operation():
            prompt, namespace = self._inputs(prompt, namespace)
            if not isinstance(policy, CachePolicy):
                raise CacheValidationError("Policy must be a CachePolicy")
            ttl = self._ttl(cache_ttl_seconds, write_enabled=policy._write_enabled)
            if not (
                inspect.iscoroutinefunction(generate)
                or (
                    callable(generate)
                    and inspect.iscoroutinefunction(type(generate).__call__)
                )
            ):
                raise CacheValidationError("Generation must be an async callable")

            async def lookup() -> _Lookup:
                return await self._lookup(prompt, namespace)

            def hit_response(found: _Lookup | None) -> str | None:
                return (
                    None if found is None or found.hit is None else found.hit.response
                )

            async def generation() -> str:
                output = await generate(prompt)
                self._check_space()
                try:
                    return valid_response(output)
                except ValueError:
                    raise GenerationError("Generated response is invalid") from None

            async def write(response: str, found: _Lookup | None) -> None:
                await self._write(
                    prompt,
                    response,
                    namespace,
                    ttl,
                    None if found is None else found.embedding,
                )

            found, response = await resolve_flow(
                read_enabled=policy._read_enabled,
                write_enabled=policy._write_enabled,
                lookup=lookup,
                hit_response=hit_response,
                generate=generation,
                write=write,
            )
            hit = None if found is None else found.hit
            return CacheResult(
                response=response,
                cache_hit=hit is not None,
                similarity_score=None if found is None else found.score,
                similarity_threshold=self._threshold,
                matched_prompt=None if hit is None else hit.matched_prompt,
                matched_cache_key=None if hit is None else hit.matched_cache_key,
                cache_entry_created_at=None
                if hit is None
                else hit.cache_entry_created_at,
                cache_entry_age_seconds=None
                if hit is None
                else hit.cache_entry_age_seconds,
                generation_skipped=hit is not None,
                provider_called=hit is None,
                latency_ms=(perf_counter() - started) * 1_000,
                cache_written=hit is None and policy._write_enabled,
            )

    async def delete(self, cache_key: str, *, namespace: str = "default") -> bool:
        async with self._operation():
            try:
                key = cache_key_value(cache_key)
                namespace = namespace_value(namespace)
            except ValueError:
                raise CacheValidationError("Invalid cache key or namespace") from None
            result = await self._store.delete_entry(key, namespace=namespace)
            self._check_space()
            if not isinstance(result, bool):
                raise CacheStoreError("Store returned invalid deletion result")
            return result

    async def clear(self, *, namespace: str = "default") -> int:
        async with self._operation():
            try:
                namespace = namespace_value(namespace)
            except ValueError:
                raise CacheValidationError("Invalid namespace") from None
            result = await self._store.clear(namespace=namespace)
            self._check_space()
            if isinstance(result, bool) or not isinstance(result, int) or result < 0:
                raise CacheStoreError("Store returned invalid clear result")
            return result

    async def aclose(self) -> None:
        self._state.close()

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
