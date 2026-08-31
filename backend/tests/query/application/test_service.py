import asyncio
import logging
from collections.abc import Sequence

import pytest

from app.cache.application.service import SemanticCache
from app.cache.domain.keys import prompt_cache_key
from app.core.exceptions import (
    InvalidProviderResponseError,
    ProviderRequestError,
)
from app.core.limits import MAX_RESPONSE_LENGTH
from app.observability.metrics import RuntimeMetrics
from app.providers.protocols import GenerationProvider
from app.query.application.service import QueryService
from app.query.domain.policies import QueryCachePolicy
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
