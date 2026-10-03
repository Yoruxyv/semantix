import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from semantix_cache import (
    AsyncSemanticCache,
    CacheBusyError,
    CacheClosedError,
    CacheConfigurationError,
    CacheEntry,
    CacheMatch,
    CachePolicy,
    CacheStoreError,
    CacheTimeoutError,
    CacheValidationError,
    EmbeddingError,
    EmbeddingSpace,
    EmbeddingSpaceError,
    GenerationCallable,
    GenerationError,
    MemoryStore,
)
from semantix_cache._semantics import prompt_cache_key

from .conftest import Adapter, SpyStore, generate


async def test_resolve_evidence_and_low_level(
    cache: AsyncSemanticCache,
    adapter: Adapter,
    store: SpyStore,
) -> None:
    miss = await cache.resolve("  hello\nworld  ", generate=generate)
    assert miss.response == "answer: hello world"
    assert not miss.cache_hit
    assert miss.provider_called
    assert miss.cache_written
    assert miss.similarity_score is None
    assert miss.matched_prompt is None
    assert adapter.calls == ["hello world"]
    assert store.calls == ["read", "write"]
    hit = await cache.resolve("similar", generate=generate)
    assert hit.cache_hit
    assert hit.generation_skipped
    assert not hit.provider_called
    assert not hit.cache_written
    assert hit.similarity_score == pytest.approx(1.0)
    assert hit.matched_prompt == "hello world"
    assert hit.cache_entry_age_seconds is not None
    assert hit.cache_entry_age_seconds >= 0
    assert hit.latency_ms >= 0
    store.calls.clear()
    assert await cache.get("similar") is not None
    assert store.calls == ["read", "confirm"]
    key = await cache.set("other", "approved", namespace="x")
    assert key == prompt_cache_key("other", namespace="x")
    assert await cache.delete(key) is False
    assert await cache.delete(key, namespace="x") is True
    assert await cache.delete(key, namespace="x") is False
    assert await cache.clear(namespace="x") == 0
    assert await cache.clear() == 1
    assert await cache.get("anything") is None


@pytest.mark.parametrize(
    ("policy", "reads", "writes"),
    [
        (CachePolicy.NORMAL, 1, 1),
        (CachePolicy.READ_ONLY, 1, 0),
        (CachePolicy.REFRESH, 0, 1),
        (CachePolicy.BYPASS, 0, 0),
        (CachePolicy.PRIVATE, 0, 0),
    ],
)
@pytest.mark.parametrize("seeded", [False, True])
async def test_policy_counts(
    policy: CachePolicy,
    reads: int,
    writes: int,
    seeded: bool,
    cache: AsyncSemanticCache,
    adapter: Adapter,
    store: SpyStore,
) -> None:
    if seeded:
        await cache.set("seed", "cached")
    adapter.calls.clear()
    store.calls.clear()
    generated: list[str] = []

    async def generation(prompt: str) -> str:
        generated.append(prompt)
        return "generated"

    result = await cache.resolve("question", generate=generation, policy=policy)
    expected_hit = seeded and bool(reads)
    assert result.cache_hit is expected_hit
    assert result.cache_written is (bool(writes) and not expected_hit)
    assert len(generated) == (0 if expected_hit else 1)
    assert store.calls.count("read") == reads
    assert store.calls.count("write") == (0 if expected_hit else writes)
    assert store.calls.count("confirm") == int(expected_hit)
    assert len(adapter.calls) == (1 if reads or writes else 0)
    assert (
        result.similarity_score is None
        if not reads or not seeded
        else result.similarity_score is not None
    )


@pytest.mark.parametrize(
    "policy", [CachePolicy.READ_ONLY, CachePolicy.BYPASS, CachePolicy.PRIVATE]
)
async def test_ttl_policy_fails_before_callbacks(
    policy: CachePolicy,
    cache: AsyncSemanticCache,
    adapter: Adapter,
    store: SpyStore,
) -> None:
    with pytest.raises(CacheValidationError):
        await cache.resolve(
            "prompt", generate=generate, policy=policy, cache_ttl_seconds=1
        )
    assert adapter.calls == []
    assert store.calls == []


@pytest.mark.parametrize(
    "value", [True, 0.0, -1.0, float("nan"), float("inf"), 31_536_001.0, "1"]
)
async def test_invalid_ttl(
    value: object,
    cache: AsyncSemanticCache,
    adapter: Adapter,
    store: SpyStore,
) -> None:
    with pytest.raises(CacheValidationError):
        await cache.set("prompt", "response", cache_ttl_seconds=cast(float, value))
    assert adapter.calls == []
    assert store.calls == []


@pytest.mark.parametrize(
    ("prompt", "namespace"),
    [
        ("", "default"),
        (" \t", "default"),
        ("x" * 2001, "default"),
        ("valid", ""),
        ("valid", "*"),
        ("valid", "x" * 65),
        ("valid", "n\n"),
        (42, "default"),
        ("valid", None),
    ],
)
async def test_invalid_inputs(
    prompt: object,
    namespace: object,
    cache: AsyncSemanticCache,
    adapter: Adapter,
) -> None:
    with pytest.raises(CacheValidationError):
        await cache.get(cast(str, prompt), namespace=cast(str, namespace))
    assert adapter.calls == []


@pytest.mark.parametrize(
    "response",
    ["", " \n", "x" * 100001, None, 5],
    ids=["empty", "blank", "too-long", "null", "number"],
)
async def test_invalid_responses(
    response: object,
    cache: AsyncSemanticCache,
    adapter: Adapter,
) -> None:
    with pytest.raises(CacheValidationError):
        await cache.set("prompt", cast(str, response))

    async def bad_generation(prompt: str) -> str:
        return cast(str, response)

    with pytest.raises(GenerationError):
        await cache.resolve("prompt", generate=bad_generation)
    assert await cache.get("prompt") is None


async def test_swallowed_generation_cancellation_never_writes(
    cache: AsyncSemanticCache,
    store: SpyStore,
) -> None:
    started = asyncio.Event()

    async def swallowed(prompt: str) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return "cancelled output"
        return "unreachable"

    task = asyncio.create_task(cache.resolve("prompt", generate=swallowed))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "write" not in store.calls
    assert await cache.get("prompt") is None


async def test_swallowed_deadline_never_writes(
    adapter: Adapter, store: SpyStore
) -> None:
    cache = AsyncSemanticCache(
        embedder=adapter, store=store, operation_timeout_seconds=0.01
    )

    async def swallowed(prompt: str) -> str:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return "cancelled output"
        return "unreachable"

    with pytest.raises(CacheTimeoutError):
        await cache.resolve("prompt", generate=swallowed)
    assert "write" not in store.calls


async def test_embedding_cancellation_leaves_no_write(
    cache: AsyncSemanticCache,
    adapter: Adapter,
    store: SpyStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    async def swallowed(text: str) -> Sequence[float]:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return (1.0, 0.0)
        return (1.0, 0.0)

    monkeypatch.setattr(adapter, "embed", swallowed)
    task = asyncio.create_task(cache.set("prompt", "response"))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.calls == []


async def test_malformed_store_mutation_and_confirmation_results(
    cache: AsyncSemanticCache,
    store: SpyStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = await cache.set("seed", "response")

    async def bad_delete(cache_key: str, *, namespace: str) -> bool:
        return cast(bool, 1)

    async def bad_clear(*, namespace: str) -> int:
        return cast(int, True)

    async def bad_confirm(
        cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        return cast(bool, 1)

    monkeypatch.setattr(store, "delete_entry", bad_delete)
    monkeypatch.setattr(store, "clear", bad_clear)
    monkeypatch.setattr(store, "record_hit", bad_confirm)
    with pytest.raises(CacheStoreError):
        await cache.delete(key)
    with pytest.raises(CacheStoreError):
        await cache.clear()
    with pytest.raises(CacheStoreError):
        await cache.get("seed")
    with pytest.raises(CacheValidationError):
        await cache.delete("not-a-key")
    with pytest.raises(CacheValidationError):
        await cache.clear(namespace="*")


async def test_valid_foreign_candidate_is_rejected(
    cache: AsyncSemanticCache,
    store: SpyStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foreign = CacheEntry(
        cache_key=prompt_cache_key("foreign", namespace="foreign"),
        namespace="foreign",
        prompt="foreign",
        response="private response",
        embedding=(1.0, 0.0),
        created_at=datetime.now(UTC),
    )

    async def foreign_match(
        embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch:
        return CacheMatch(entry=foreign, similarity_score=1.0, expires_at=None)

    monkeypatch.setattr(store, "find_nearest", foreign_match)
    with pytest.raises(CacheStoreError):
        await cache.get("question")


@pytest.mark.parametrize(
    "vector",
    [
        (10**1000, 1),
    ],
)
async def test_overflowing_component_is_safe(
    vector: Sequence[float], store: SpyStore
) -> None:
    cache = AsyncSemanticCache(embedder=Adapter(vector=vector), store=store)
    with pytest.raises(EmbeddingError, match="Embedding output is invalid"):
        await cache.get("prompt")


@pytest.mark.parametrize(
    "vector",
    [
        (),
        (1.0,),
        (1.0, 0.0, 0.0),
        (0.0, 0.0),
        (1e-300, 0),
        (float("nan"), 1),
        (float("inf"), 1),
        (1e308, 1e308),
        (True, 0),
        ("1", 0),
        ((1, 0), (0, 1)),
        None,
        "12",
    ],
)
async def test_bad_embedding(vector: object, store: SpyStore) -> None:
    embedder = Adapter(vector=cast(Sequence[float], vector))
    cache = AsyncSemanticCache(embedder=embedder, store=store)
    with pytest.raises(EmbeddingError):
        await cache.resolve("prompt", generate=generate)
    assert store.calls == []


@pytest.mark.parametrize("threshold", [0.0, 1.0])
async def test_threshold_equality(threshold: float, adapter: Adapter) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space)
    cache = AsyncSemanticCache(
        embedder=adapter, store=store, similarity_threshold=threshold
    )
    await cache.set("seed", "cached")
    adapter.vector = (0.0, 1.0) if threshold == 0 else (1.0, 0.0)
    assert (await cache.resolve("question", generate=generate)).cache_hit


async def test_below_threshold_reuses_embedding(
    cache: AsyncSemanticCache,
    adapter: Adapter,
    store: SpyStore,
) -> None:
    await cache.set("seed", "cached")
    adapter.vector = (0.0, 10.0)
    adapter.calls.clear()
    result = await cache.resolve("other", generate=generate)
    assert result.similarity_score == pytest.approx(0.0)
    assert result.matched_cache_key is None
    assert result.cache_written
    assert adapter.calls == ["other"]
    match = await store.find_nearest((0.0, 1.0), namespace="default")
    assert match is not None
    assert match.entry.embedding == (0.0, 1.0)


async def test_normalizer_changes_matching_only(
    adapter: Adapter, store: SpyStore
) -> None:
    cache = AsyncSemanticCache(
        embedder=adapter, store=store, prompt_normalizer=str.lower
    )
    result = await cache.resolve(" Canonical TEXT ", generate=generate)
    assert adapter.calls == ["canonical text"]
    assert result.response == "answer: Canonical TEXT"
    hit = await cache.get("same")
    assert hit is not None
    assert hit.matched_prompt == "Canonical TEXT"
    bad = AsyncSemanticCache(
        embedder=adapter, store=store, prompt_normalizer=lambda value: ""
    )
    with pytest.raises(CacheValidationError):
        await bad.get("input")


async def test_namespaces_spaces_and_changed_metadata(
    adapter: Adapter, store: SpyStore
) -> None:
    cache = AsyncSemanticCache(embedder=adapter, store=store)
    await cache.set("seed", "cached", namespace="a")
    assert await cache.get("seed", namespace="b") is None
    other = Adapter(identity="other-v1")
    with pytest.raises(EmbeddingSpaceError):
        AsyncSemanticCache(embedder=other, store=store)
    other_store = MemoryStore(embedding_space=other.embedding_space)
    other_cache = AsyncSemanticCache(embedder=other, store=other_store)
    assert await other_cache.get("seed", namespace="a") is None
    adapter.space = other.embedding_space
    with pytest.raises(EmbeddingSpaceError):
        await cache.get("seed")
    adapter.space = EmbeddingSpace.model_construct(identity="", dimensions=0)
    with pytest.raises(EmbeddingSpaceError):
        AsyncSemanticCache(
            embedder=adapter, store=MemoryStore(embedding_space=other.embedding_space)
        )


@pytest.mark.parametrize(
    "threshold", [True, -0.01, 1.01, float("nan"), float("inf"), "0.9"]
)
def test_bad_threshold(threshold: object, adapter: Adapter, store: SpyStore) -> None:
    with pytest.raises(CacheConfigurationError):
        AsyncSemanticCache(
            embedder=adapter, store=store, similarity_threshold=cast(float, threshold)
        )


@pytest.mark.parametrize("timeout", [0, -1, True, float("inf")])
def test_bad_timeout(timeout: object, adapter: Adapter, store: SpyStore) -> None:
    with pytest.raises(CacheConfigurationError):
        AsyncSemanticCache(
            embedder=adapter,
            store=store,
            operation_timeout_seconds=cast(float, timeout),
        )


async def test_invalid_policy_and_sync_generation(
    cache: AsyncSemanticCache, adapter: Adapter
) -> None:
    with pytest.raises(CacheValidationError):
        await cache.resolve(
            "prompt", generate=generate, policy=cast(CachePolicy, "normal")
        )

    def sync(prompt: str) -> str:
        raise AssertionError("Sync function must not run")

    with pytest.raises(CacheValidationError):
        await cache.resolve("prompt", generate=cast(GenerationCallable, sync))
    assert adapter.calls == []


async def test_async_callable_object(cache: AsyncSemanticCache) -> None:
    class Generator:
        async def __call__(self, prompt: str) -> str:
            return "answer"

    assert (await cache.resolve("prompt", generate=Generator())).response == "answer"


async def test_generator_exception_is_unchanged(cache: AsyncSemanticCache) -> None:
    failure = RuntimeError("application failure")

    async def broken(prompt: str) -> str:
        raise failure

    with pytest.raises(RuntimeError) as caught:
        await cache.resolve("prompt", generate=broken)
    assert caught.value is failure
    assert await cache.get("prompt") is None


async def test_timeout_vs_callback_timeout(adapter: Adapter, store: SpyStore) -> None:
    cache = AsyncSemanticCache(
        embedder=adapter, store=store, operation_timeout_seconds=0.01
    )

    async def blocked(prompt: str) -> str:
        await asyncio.Event().wait()
        return "unreachable"

    with pytest.raises(CacheTimeoutError):
        await cache.resolve("prompt", generate=blocked)

    async def timeout(prompt: str) -> str:
        raise TimeoutError("custom timeout")

    with pytest.raises(TimeoutError, match="custom timeout"):
        await cache.resolve("prompt", generate=timeout)
    assert await cache.get("prompt") is None


async def test_active_close_cancellation_and_borrowed_dependencies(
    cache: AsyncSemanticCache,
    store: SpyStore,
) -> None:
    started = asyncio.Event()

    async def blocked(prompt: str) -> str:
        started.set()
        await asyncio.Event().wait()
        return "unreachable"

    task = asyncio.create_task(cache.resolve("prompt", generate=blocked))
    await started.wait()
    with pytest.raises(CacheBusyError):
        await cache.aclose()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await cache.get("prompt") is None
    await cache.aclose()
    await cache.aclose()
    with pytest.raises(CacheClosedError):
        await cache.get("prompt")
    with pytest.raises(CacheClosedError):
        await cache.__aenter__()
    assert await store.clear(namespace="default") == 0


async def test_context_exit_preserves_exception(adapter: Adapter) -> None:
    store = MemoryStore(embedding_space=adapter.embedding_space)

    async def fail_inside_context() -> None:
        async with AsyncSemanticCache(embedder=adapter, store=store) as cache:
            assert cache.similarity_threshold == pytest.approx(0.92)
            raise RuntimeError("app failure")

    with pytest.raises(RuntimeError, match="app failure"):
        await fail_inside_context()
    assert await store.clear(namespace="default") == 0


async def test_concurrent_same_prompt_misses_are_not_coalesced(
    cache: AsyncSemanticCache,
) -> None:
    count = 0
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def generation(prompt: str) -> str:
        nonlocal count
        count += 1
        if count == 2:
            both_started.set()
        await release.wait()
        return "response"

    tasks = [
        asyncio.create_task(cache.resolve("prompt", generate=generation))
        for _ in range(2)
    ]
    await asyncio.wait_for(both_started.wait(), timeout=2)
    release.set()
    results = await asyncio.gather(*tasks)
    assert count == 2
    assert all(not result.cache_hit for result in results)
    assert all(result.cache_written for result in results)
    hits = await asyncio.gather(
        *(cache.resolve("similar", generate=generate) for _ in range(12))
    )
    assert all(result.cache_hit for result in hits)


async def test_candidate_validation_and_failed_confirmation(
    cache: AsyncSemanticCache,
    store: SpyStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await cache.set("seed", "cached")
    match = await store.find_nearest((1.0, 0.0), namespace="default")
    assert match is not None

    async def unconfirmed(
        cache_key: str, *, namespace: str, expected_created_at: datetime
    ) -> bool:
        return False

    monkeypatch.setattr(store, "record_hit", unconfirmed)
    assert not (await cache.resolve("question", generate=generate)).cache_hit
    for invalid in [
        object(),
        match.model_copy(update={"similarity_score": float("nan")}),
        match.model_copy(
            update={"entry": match.entry.model_copy(update={"namespace": "foreign"})}
        ),
        match.model_copy(
            update={"entry": match.entry.model_copy(update={"embedding": (1.0,)})}
        ),
    ]:

        async def nearest(
            embedding: Sequence[float], *, namespace: str, invalid: object = invalid
        ) -> CacheMatch:
            return cast(CacheMatch, invalid)

        monkeypatch.setattr(store, "find_nearest", nearest)
        with pytest.raises(CacheStoreError):
            await cache.get("question")
    expired = match.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )

    async def nearest_expired(
        embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch:
        return expired

    monkeypatch.setattr(store, "find_nearest", nearest_expired)
    assert await cache.get("question") is None


async def test_strict_embedding_and_store_failure(
    cache: AsyncSemanticCache,
    adapter: Adapter,
    store: SpyStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = EmbeddingError("safe embedding failure")

    async def bad_embed(text: str) -> Sequence[float]:
        raise error

    monkeypatch.setattr(adapter, "embed", bad_embed)
    with pytest.raises(EmbeddingError) as caught:
        await cache.get("prompt")
    assert caught.value is error
    monkeypatch.undo()
    failure = CacheStoreError("safe storage failure")

    async def bad_store(
        embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        raise failure

    monkeypatch.setattr(store, "find_nearest", bad_store)
    with pytest.raises(CacheStoreError) as caught_store:
        await cache.resolve("prompt", generate=generate)
    assert caught_store.value is failure
    monkeypatch.undo()

    async def bad_write(entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        raise failure

    monkeypatch.setattr(store, "put", bad_write)
    with pytest.raises(CacheStoreError):
        await cache.resolve("prompt", generate=generate)
    assert await cache.get("prompt") is None
