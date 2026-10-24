import asyncio
import logging
from collections.abc import Sequence
from unittest.mock import patch

import pytest

from app.cache.application.service import SemanticCache
from app.cache.domain.keys import prompt_cache_key
from app.cache.domain.models import CacheLookupResult
from app.core.exceptions import (
    InvalidProviderResponseError,
    ProviderRequestError,
    ProviderRetryableError,
)
from app.core.limits import MAX_RESPONSE_LENGTH
from app.observability.metrics import RuntimeMetrics
from app.providers.protocols import GenerationProvider
from app.query.api.schemas import QueryResponse
from app.query.application.service import QueryService
from app.query.domain.policies import QueryCachePolicy
from semantix_cache import MemoryStore
from tests.support import memory_backend, unit_vector


class Embeddings:
    async def embed(self, text: str) -> Sequence[float]:
        return unit_vector()


class Provider:
    def __init__(self) -> None:
        self.call_count = 0
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        return "answer"


class ControlledProvider:
    def __init__(
        self,
        *,
        expected_calls: int = 1,
        failures_remaining: int = 0,
    ) -> None:
        self.call_count = 0
        self.prompts: list[str] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._expected_calls = expected_calls
        self._failures_remaining = failures_remaining

    async def generate(self, prompt: str) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        if self.call_count >= self._expected_calls:
            self.started.set()

        await self.release.wait()
        if self._failures_remaining:
            self._failures_remaining -= 1
            raise RuntimeError("generation failed")
        return f"answer:{prompt}"


class SequenceProvider:
    def __init__(self, outcomes: list[str | Exception]) -> None:
        self._outcomes = outcomes
        self.call_count = 0

    async def generate(self, prompt: str) -> str:
        outcome = self._outcomes[self.call_count]
        self.call_count += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class DeadlineProvider:
    def __init__(self) -> None:
        self.call_count = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, prompt: str) -> str:
        self.call_count += 1
        if self.call_count == 1:
            self.started.set()
            await self.release.wait()
            raise ProviderRetryableError("Network failure")
        return "recovered"


class JoiningMetrics(RuntimeMetrics):
    """Observe follower registration through the production metrics callback."""

    def __init__(self) -> None:
        super().__init__()
        self.joined = asyncio.Event()

    def record_coalesced_delta(self, delta: int) -> None:
        super().record_coalesced_delta(delta)
        if delta == 1:
            self.joined.set()


def query_service(provider: GenerationProvider) -> QueryService:
    return QueryService(
        SemanticCache(
            Embeddings(),
            memory_backend(),
            0.92,
        ),
        provider,
    )


@pytest.mark.asyncio
async def test_explains_cache_miss_and_hit() -> None:
    provider = Provider()
    service = query_service(provider)

    miss = await service.execute("one")
    assert miss.cache_hit is False
    assert miss.similarity_score is None
    assert miss.similarity_threshold == pytest.approx(0.92)
    assert miss.matched_prompt is None
    assert miss.matched_cache_key is None
    assert miss.cache_entry_created_at is None
    assert miss.cache_entry_age_seconds is None
    assert miss.generation_skipped is False
    assert miss.provider_called is True
    assert provider.call_count == 1

    provider.call_count = 0
    hit = await service.execute("similar")

    assert hit.cache_hit is True
    assert hit.similarity_score == pytest.approx(1.0)
    assert hit.similarity_threshold == pytest.approx(0.92)
    assert hit.matched_prompt == "one"
    assert hit.matched_cache_key == prompt_cache_key("one")
    assert hit.cache_entry_created_at is not None
    assert hit.cache_entry_created_at.utcoffset() is not None
    assert hit.cache_entry_age_seconds is not None
    assert hit.cache_entry_age_seconds >= 0
    assert hit.generation_skipped is True
    assert hit.provider_called is False
    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_typo_normalization_does_not_change_generation_prompt() -> None:
    provider = Provider()
    service = QueryService(
        SemanticCache(
            Embeddings(),
            memory_backend(),
            0.92,
            prompt_normalizer=lambda prompt: (
                "semantic caching" if prompt == "semntic caching" else prompt
            ),
        ),
        provider,
    )

    response = await service.execute("semntic caching")

    assert response.provider_called is True
    assert provider.prompts == ["semntic caching"]


@pytest.mark.asyncio
async def test_coalesces_twenty_simultaneous_identical_misses() -> None:
    provider = ControlledProvider()
    service = query_service(provider)
    requests = [asyncio.create_task(service.execute("same prompt")) for _ in range(20)]

    await asyncio.wait_for(provider.started.wait(), timeout=1)
    provider.release.set()
    responses = await asyncio.gather(*requests)

    assert provider.call_count == 1
    assert {response.response for response in responses} == {"answer:same prompt"}
    assert sum(response.provider_called for response in responses) == 1
    assert sum(response.generation_skipped for response in responses) == 19
    assert all(not response.cache_hit for response in responses)


@pytest.mark.asyncio
async def test_coalesces_requests_with_the_same_effective_ttl() -> None:
    provider = ControlledProvider()
    service = QueryService(
        SemanticCache(
            Embeddings(),
            memory_backend(ttl_seconds=3_600),
            0.92,
        ),
        provider,
    )
    requests = [
        asyncio.create_task(
            service.execute(
                "same ttl prompt",
                policy=QueryCachePolicy(cache_ttl_seconds=ttl_seconds),
            )
        )
        for ttl_seconds in (3_600, 7_200)
    ]

    await asyncio.wait_for(provider.started.wait(), timeout=1)
    provider.release.set()
    responses = await asyncio.gather(*requests)

    assert provider.call_count == 1
    assert sum(response.provider_called for response in responses) == 1


@pytest.mark.asyncio
async def test_does_not_coalesce_requests_with_different_effective_ttls() -> None:
    provider = ControlledProvider(expected_calls=2)
    backend = memory_backend()
    service = QueryService(SemanticCache(Embeddings(), backend, 0.92), provider)
    requests = [
        asyncio.create_task(
            service.execute(
                "different ttl prompt",
                policy=QueryCachePolicy(cache_ttl_seconds=ttl_seconds),
            )
        )
        for ttl_seconds in (30, 60)
    ]

    await asyncio.wait_for(provider.started.wait(), timeout=1)
    provider.release.set()
    responses = await asyncio.gather(*requests)

    assert provider.call_count == 2
    assert all(response.provider_called for response in responses)
    assert (await backend.stats(None)).size == 1


@pytest.mark.asyncio
async def test_rejects_ttl_without_cache_writes_before_provider() -> None:
    provider = Provider()
    service = query_service(provider)

    with pytest.raises(ValueError, match="permits writes"):
        await service.execute(
            "invalid ttl policy",
            policy=QueryCachePolicy(
                write_enabled=False,
                cache_ttl_seconds=60,
            ),
        )

    assert provider.call_count == 0


@pytest.mark.asyncio
async def test_failed_generation_is_removed_before_retry() -> None:
    provider = ControlledProvider(failures_remaining=1)
    service = query_service(provider)
    provider.release.set()

    with pytest.raises(RuntimeError, match="generation failed"):
        await service.execute("retry prompt")

    response = await service.execute("retry prompt")

    assert response.response == "answer:retry prompt"
    assert response.provider_called is True
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_deadline_failure_is_shared_cleaned_and_not_cached() -> None:
    provider = DeadlineProvider()
    backend = memory_backend()
    service = QueryService(SemanticCache(Embeddings(), backend, 0.92), provider)
    requests = [
        asyncio.create_task(service.execute("deadline prompt")) for _ in range(100)
    ]

    await asyncio.wait_for(provider.started.wait(), timeout=1)
    await asyncio.sleep(0)
    provider.release.set()
    failures = await asyncio.gather(*requests, return_exceptions=True)

    assert provider.call_count == 1
    assert all(isinstance(error, ProviderRetryableError) for error in failures)
    assert (await backend.stats(None)).size == 0

    recovered = await service.execute("deadline prompt")

    assert recovered.response == "recovered"
    assert recovered.provider_called is True
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_different_prompts_do_not_share_in_flight_generation() -> None:
    provider = ControlledProvider(expected_calls=2)
    service = query_service(provider)
    requests = [
        asyncio.create_task(service.execute(prompt))
        for prompt in ("first prompt", "second prompt")
    ]

    await asyncio.wait_for(provider.started.wait(), timeout=1)
    provider.release.set()
    responses = await asyncio.gather(*requests)

    assert provider.call_count == 2
    assert set(provider.prompts) == {"first prompt", "second prompt"}
    assert {response.response for response in responses} == {
        "answer:first prompt",
        "answer:second prompt",
    }
    assert all(response.provider_called for response in responses)


@pytest.mark.asyncio
async def test_same_prompt_is_isolated_by_namespace() -> None:
    provider = ControlledProvider(expected_calls=2)
    service = query_service(provider)
    requests = [
        asyncio.create_task(
            service.execute(
                "shared prompt",
                policy=QueryCachePolicy(namespace=namespace),
            )
        )
        for namespace in ("tenant-alpha", "tenant-beta")
    ]

    await asyncio.wait_for(provider.started.wait(), timeout=1)
    provider.release.set()
    responses = await asyncio.gather(*requests)

    assert provider.call_count == 2
    assert all(not response.cache_hit for response in responses)

    alpha_hit = await service.execute(
        "shared prompt",
        policy=QueryCachePolicy(namespace="tenant-alpha"),
    )
    assert alpha_hit.cache_hit
    assert alpha_hit.matched_cache_key == prompt_cache_key(
        "shared prompt",
        namespace="tenant-alpha",
    )
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_empty_provider_response_is_not_cached() -> None:
    provider = SequenceProvider(["", "valid response"])
    service = query_service(provider)

    with pytest.raises(InvalidProviderResponseError):
        await service.execute("empty response")

    retry = await service.execute("empty response")
    assert retry.response == "valid response"
    assert retry.provider_called is True
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_maximum_length_provider_response_succeeds() -> None:
    response_text = "x" * MAX_RESPONSE_LENGTH
    service = query_service(SequenceProvider([response_text]))

    response = await service.execute("maximum response")

    assert response.response == response_text


@pytest.mark.parametrize(
    ("read_enabled", "write_enabled"),
    [
        (True, True),
        (False, True),
        (True, False),
        (False, False),
    ],
)
@pytest.mark.asyncio
async def test_oversized_provider_response_is_rejected_before_storage(
    read_enabled: bool,
    write_enabled: bool,
) -> None:
    backend = memory_backend()
    cache = SemanticCache(
        Embeddings(),
        backend,
        0.92,
    )
    provider = SequenceProvider(
        [
            "x" * (MAX_RESPONSE_LENGTH + 1),
            "valid response",
        ]
    )
    service = QueryService(cache, provider)
    policy = QueryCachePolicy(
        read_enabled=read_enabled,
        write_enabled=write_enabled,
    )

    with pytest.raises(InvalidProviderResponseError):
        await service.execute("oversized response", policy=policy)

    assert (
        await backend.get_entry(
            prompt_cache_key("oversized response"),
            authorized_namespaces=None,
        )
        is None
    )

    retry = await service.execute("oversized response", policy=policy)
    assert retry.response == "valid response"
    assert retry.provider_called is True
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_provider_error_is_not_cached() -> None:
    provider = SequenceProvider(
        [
            ProviderRequestError("provider failed"),
            "valid response",
        ]
    )
    service = query_service(provider)

    with pytest.raises(ProviderRequestError):
        await service.execute("provider error")

    retry = await service.execute("provider error")
    assert retry.response == "valid response"
    assert retry.provider_called is True
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_failed_query_records_request_error_and_provider_attempt() -> None:
    metrics = RuntimeMetrics()
    provider = SequenceProvider([ProviderRequestError("provider failed")])
    cache = SemanticCache(
        Embeddings(),
        memory_backend(),
        0.92,
        events=metrics,
    )
    service = QueryService(cache, provider, metrics=metrics)

    with pytest.raises(ProviderRequestError):
        await service.execute("observed failure")

    snapshot = metrics.snapshot(cache_size=0)
    assert snapshot.request_count == 1
    assert snapshot.error_count == 1
    assert snapshot.cache_misses == 1
    assert snapshot.provider_calls == 1
    assert snapshot.latency_sample_size == 1


@pytest.mark.asyncio
async def test_private_prompt_bypasses_cache_reads_writes_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="app.query.application.service")
    provider = SequenceProvider(["cached response", "private response"])
    service = query_service(provider)
    await service.execute("sensitive prompt")

    private = await service.execute(
        "sensitive prompt",
        policy=QueryCachePolicy(
            read_enabled=False,
            write_enabled=False,
        ),
    )
    cached = await service.execute("sensitive prompt")

    assert private.response == "private response"
    assert private.cache_hit is False
    assert cached.response == "cached response"
    assert cached.cache_hit is True
    assert provider.call_count == 2
    assert "sensitive prompt" not in caplog.text
    assert "private response" not in caplog.text


@pytest.mark.asyncio
async def test_read_bypass_refreshes_cache_when_writes_remain_enabled() -> None:
    provider = SequenceProvider(["original response", "refreshed response"])
    backend = memory_backend()
    service = QueryService(SemanticCache(Embeddings(), backend, 0.92), provider)
    await service.execute("refresh prompt")

    refreshed = await service.execute(
        "refresh prompt",
        policy=QueryCachePolicy(read_enabled=False, cache_ttl_seconds=30),
    )
    cached = await service.execute("refresh prompt")

    assert refreshed.response == "refreshed response"
    assert refreshed.cache_hit is False
    assert cached.response == "refreshed response"
    assert cached.cache_hit is True
    assert provider.call_count == 2
    metadata = await backend.get_entry(
        prompt_cache_key("refresh prompt"),
        authorized_namespaces=None,
    )
    assert metadata is not None
    assert metadata.remaining_ttl_seconds == pytest.approx(30, abs=1)


@pytest.mark.asyncio
async def test_write_bypass_does_not_create_cache_entry() -> None:
    provider = SequenceProvider(["not stored", "stored response"])
    service = query_service(provider)

    bypassed = await service.execute(
        "write bypass",
        policy=QueryCachePolicy(write_enabled=False),
    )
    stored = await service.execute("write bypass")
    cached = await service.execute(
        "write bypass",
        policy=QueryCachePolicy(write_enabled=False),
    )

    assert bypassed.response == "not stored"
    assert bypassed.cache_hit is False
    assert stored.response == "stored response"
    assert stored.cache_hit is False
    assert cached.response == "stored response"
    assert cached.cache_hit is True
    assert provider.call_count == 2


@pytest.mark.asyncio
async def test_shared_lookup_keeps_threshold_snapshot_until_independent_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Share the captured threshold, then independently apply the updated value."""
    embeddings, provider, metrics = Embeddings(), Provider(), JoiningMetrics()
    backend = memory_backend()
    store = backend.store
    assert isinstance(store, MemoryStore)
    cache = SemanticCache(embeddings, backend, 0.9, events=metrics)
    service = QueryService(cache, provider, metrics=metrics)
    policy = QueryCachePolicy(namespace="threshold-snapshot", write_enabled=False)
    key = prompt_cache_key("seed", namespace=policy.namespace)
    entered, release = asyncio.Event(), asyncio.Event()
    embed = embeddings.embed
    embedding_calls = 0
    callers: list[asyncio.Task[QueryResponse]] = []

    async def held_embedding(text: str) -> Sequence[float]:
        nonlocal embedding_calls
        embedding_calls += 1
        entered.set()
        await release.wait()
        return await embed(text)

    monkeypatch.setattr(embeddings, "embed", held_embedding)
    async with store:
        try:
            async with asyncio.timeout(5):
                await cache.store(
                    "seed",
                    "stored answer",
                    [0.8, 0.6, 0.0, 0.0],
                    namespace=policy.namespace,
                )
                original = await store.inspect_entry(
                    key, namespaces=(policy.namespace,)
                )
                assert original is not None
                assert original.hit_count == 0
                with (
                    patch.object(store, "put", wraps=store.put) as put,
                    patch.object(
                        store, "record_hit", wraps=store.record_hit
                    ) as confirm,
                ):
                    callers.append(
                        asyncio.create_task(service.execute("query", policy=policy))
                    )
                    await entered.wait()  # lookup has captured 0.9 before embedding.
                    callers.append(
                        asyncio.create_task(service.execute("query", policy=policy))
                    )
                    await metrics.joined.wait()
                    assert (
                        metrics.snapshot(cache_size=1).in_flight_coalesced_requests == 1
                    )
                    assert await cache.write_similarity_threshold(
                        0.75
                    ) == pytest.approx(0.75)
                    release.set()
                    responses = await asyncio.gather(*callers)

                    assert embedding_calls == 1
                    assert [
                        (r.provider_called, r.generation_skipped) for r in responses
                    ] == [(True, False), (False, True)]
                    for response in responses:
                        assert response.cache_hit is False
                        assert response.response == "answer"
                        assert response.similarity_score == pytest.approx(0.8)
                        assert response.similarity_threshold == pytest.approx(0.9)
                        assert response.matched_prompt is None
                        assert response.matched_cache_key is None
                        assert response.cache_entry_created_at is None
                    confirm.assert_not_awaited()
                    unchanged = await store.inspect_entry(
                        key, namespaces=(policy.namespace,)
                    )
                    assert unchanged is not None
                    assert unchanged.hit_count == 0
                    assert unchanged.created_at == original.created_at
                    assert unchanged.expires_at == original.expires_at
                    assert unchanged.response == "stored answer"
                    stats = await backend.stats(policy.namespace)
                    assert (stats.size, stats.hits, stats.misses) == (1, 0, 1)

                    later = await service.execute("query", policy=policy)
                    assert later.cache_hit is True
                    assert later.provider_called is False
                    assert later.generation_skipped is True
                    assert later.response == "stored answer"
                    assert later.similarity_score == pytest.approx(0.8)
                    assert later.similarity_threshold == pytest.approx(0.75)
                    assert later.matched_cache_key == key
                    assert later.cache_entry_created_at == original.created_at
                    assert embedding_calls == 2
                    assert provider.call_count == 1
                    confirm.assert_awaited_once_with(
                        key,
                        namespace=policy.namespace,
                        expected_created_at=original.created_at,
                    )
                    put.assert_not_awaited()
                    current = await store.inspect_entry(
                        key, namespaces=(policy.namespace,)
                    )
                    assert current is not None
                    assert current.hit_count == 1
                    assert current.created_at == original.created_at
                    assert current.expires_at == original.expires_at
                    stats = await backend.stats(policy.namespace)
                    assert (stats.size, stats.hits, stats.misses) == (1, 1, 1)
        finally:
            release.set()
            await service.aclose(grace_seconds=1)
            await asyncio.gather(*callers, return_exceptions=True)
    assert all(caller.done() for caller in callers)
    assert service._active_requests == 0
    assert not service._coalescer._in_flight
    assert not service._coalescer._cleanup_tasks
    assert metrics.snapshot(cache_size=0).in_flight_coalesced_requests == 0


@pytest.mark.asyncio
async def test_shared_confirmed_hit_survives_replacement_before_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deliver the confirmed snapshot, then independently confirm its replacement."""
    provider, metrics = Provider(), JoiningMetrics()
    backend = memory_backend()
    store = backend.store
    assert isinstance(store, MemoryStore)
    cache = SemanticCache(Embeddings(), backend, 0.92, events=metrics)
    service = QueryService(cache, provider, metrics=metrics)
    policy = QueryCachePolicy(namespace="revision-snapshot")
    key = prompt_cache_key("seed", namespace=policy.namespace)
    confirmed, release = asyncio.Event(), asyncio.Event()
    lookup = cache.lookup
    lookups = 0
    callers: list[asyncio.Task[QueryResponse]] = []

    async def held_lookup(prompt: str, *, namespace: str) -> CacheLookupResult:
        nonlocal lookups
        lookups += 1
        resolved = await lookup(prompt, namespace=namespace)
        assert resolved.cache_hit is True
        confirmed.set()
        await release.wait()
        return resolved

    async with store:
        try:
            async with asyncio.timeout(5):
                await cache.store(
                    "seed", "original answer", unit_vector(), namespace=policy.namespace
                )
                candidate = await store.find_nearest(
                    unit_vector(), namespace=policy.namespace
                )
                assert candidate is not None
                original = await store.inspect_entry(
                    key, namespaces=(policy.namespace,)
                )
                assert original is not None
                assert original.hit_count == 0
                with (
                    patch.object(store, "put", wraps=store.put) as put,
                    patch.object(
                        store, "record_hit", wraps=store.record_hit
                    ) as confirm,
                ):
                    with monkeypatch.context() as scheduling:
                        scheduling.setattr(cache, "lookup", held_lookup)
                        callers.append(
                            asyncio.create_task(service.execute("seed", policy=policy))
                        )
                        await confirmed.wait()
                        counted = await store.inspect_entry(
                            key, namespaces=(policy.namespace,)
                        )
                        assert counted is not None
                        assert counted.hit_count == 1
                        assert counted.created_at == original.created_at
                        confirm.assert_awaited_once_with(
                            key,
                            namespace=policy.namespace,
                            expected_created_at=original.created_at,
                        )
                        callers.append(
                            asyncio.create_task(service.execute("seed", policy=policy))
                        )
                        await metrics.joined.wait()
                        replacement = candidate.entry.model_copy(
                            update={"response": "replacement answer"}
                        )
                        await store.put(replacement)
                        updated = await store.inspect_entry(
                            key, namespaces=(policy.namespace,)
                        )
                        assert updated is not None
                        assert updated.hit_count == 0
                        assert updated.created_at > original.created_at
                        release.set()
                        responses = await asyncio.gather(*callers)

                    assert lookups == 1
                    for response in responses:
                        assert response.cache_hit is True
                        assert response.provider_called is False
                        assert response.generation_skipped is True
                        assert response.response == "original answer"
                        assert response.similarity_threshold == pytest.approx(0.92)
                        assert response.matched_cache_key == key
                        assert response.cache_entry_created_at == original.created_at
                    assert confirm.await_count == 1
                    assert provider.call_count == 0
                    untouched = await store.inspect_entry(
                        key, namespaces=(policy.namespace,)
                    )
                    assert untouched is not None
                    assert untouched.hit_count == 0
                    assert untouched.created_at == updated.created_at
                    assert untouched.expires_at == updated.expires_at
                    stats = await backend.stats(policy.namespace)
                    assert (stats.size, stats.hits, stats.misses) == (1, 1, 0)

                    later = await service.execute("seed", policy=policy)
                    assert later.cache_hit is True
                    assert later.provider_called is False
                    assert later.generation_skipped is True
                    assert later.response == "replacement answer"
                    assert later.matched_cache_key == key
                    assert later.cache_entry_created_at == updated.created_at
                    assert confirm.await_count == 2
                    assert provider.call_count == 0
                    confirm.assert_awaited_with(
                        key,
                        namespace=policy.namespace,
                        expected_created_at=updated.created_at,
                    )
                    put.assert_awaited_once_with(replacement)
                    current = await store.inspect_entry(
                        key, namespaces=(policy.namespace,)
                    )
                    assert current is not None
                    assert current.hit_count == 1
                    assert current.created_at == updated.created_at
                    assert current.expires_at == updated.expires_at
                    stats = await backend.stats(policy.namespace)
                    assert (stats.size, stats.hits, stats.misses) == (1, 2, 0)
        finally:
            release.set()
            await service.aclose(grace_seconds=1)
            await asyncio.gather(*callers, return_exceptions=True)
    assert all(caller.done() for caller in callers)
    assert service._active_requests == 0
    assert not service._coalescer._in_flight
    assert not service._coalescer._cleanup_tasks
    assert metrics.snapshot(cache_size=0).in_flight_coalesced_requests == 0
