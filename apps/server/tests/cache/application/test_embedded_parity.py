from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from app.cache.application.service import SemanticCache
from app.cache.domain.keys import prompt_cache_key
from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.embedding.service import EmbeddingService
from app.query.api.schemas import QueryRequest
from app.query.application.service import QueryService
from semantix_cache import (
    AsyncSemanticCache,
    CachePolicy,
    CacheValidationError,
    EmbeddingSpace,
    MemoryStore,
)
from semantix_cache._semantics import resolve_ttl


class Adapter:
    embedding_space = EmbeddingSpace(identity="parity-v1", dimensions=2)

    async def embed(self, text: str) -> Sequence[float]:
        return (3.0, 4.0)

    async def create_embedding(self, text: str) -> Sequence[float]:
        return await self.embed(text)

    async def generate(self, prompt: str) -> str:
        return "answer: " + prompt


@pytest.mark.parametrize("policy", list(CachePolicy))
@pytest.mark.parametrize("seeded", [False, True])
async def test_server_embedded_policy_evidence_parity(
    policy: CachePolicy, seeded: bool
) -> None:
    adapter = Adapter()
    backend = InMemoryCacheBackend(max_size=500, ttl_seconds=3600, dimensions=2)
    server_cache = SemanticCache(EmbeddingService(adapter, dimensions=2), backend, 0.92)
    server = QueryService(server_cache, adapter)
    embedded = AsyncSemanticCache(
        embedder=adapter, store=MemoryStore(embedding_space=adapter.embedding_space)
    )
    prompt = QueryRequest(prompt="  public\nprompt  ").prompt
    if seeded:
        await server_cache.store(prompt, "cached")
        await embedded.set(prompt, "cached")
    flags = {
        CachePolicy.NORMAL: {},
        CachePolicy.READ_ONLY: {"cache_write_enabled": False},
        CachePolicy.REFRESH: {"cache_read_enabled": False},
        CachePolicy.BYPASS: {"cache_enabled": False},
        CachePolicy.PRIVATE: {"private": True},
    }
    request = QueryRequest.model_validate({"prompt": prompt} | flags[policy])
    remote = await server.execute(request.prompt, policy=request.cache_policy)
    local = await embedded.resolve(
        "  public\nprompt  ", generate=adapter.generate, policy=policy
    )
    assert remote.response == local.response
    assert remote.cache_hit == local.cache_hit
    assert remote.provider_called == local.provider_called
    assert remote.generation_skipped == local.generation_skipped
    assert (
        remote.similarity_score == pytest.approx(local.similarity_score)
        if remote.similarity_score is not None
        else local.similarity_score is None
    )
    assert remote.similarity_threshold == pytest.approx(local.similarity_threshold)
    assert remote.matched_prompt == local.matched_prompt
    assert remote.matched_cache_key == local.matched_cache_key
    if local.cache_hit:
        assert local.matched_cache_key == prompt_cache_key(prompt)
    assert (await backend.stats(None)).size == int(
        seeded or policy in (CachePolicy.NORMAL, CachePolicy.REFRESH)
    )
    await embedded.aclose()


@pytest.mark.parametrize("namespace", ["default", "Support:v2", "a.b-c_9", "x" * 64])
async def test_namespace_key_normalization_parity(namespace: str) -> None:
    adapter = Adapter()
    embedded = AsyncSemanticCache(
        embedder=adapter, store=MemoryStore(embedding_space=adapter.embedding_space)
    )
    request = QueryRequest(prompt=" \tshared\nprompt\x7f ", namespace=namespace)
    key = await embedded.set(" \tshared\nprompt\x7f ", "response", namespace=namespace)
    assert key == prompt_cache_key(request.prompt, namespace=request.namespace)


@pytest.mark.parametrize("namespace", ["", "*", "x" * 65, "space name", "Ã©"])
async def test_namespace_rejection_parity(namespace: str) -> None:
    adapter = Adapter()
    embedded = AsyncSemanticCache(
        embedder=adapter, store=MemoryStore(embedding_space=adapter.embedding_space)
    )
    with pytest.raises(ValidationError):
        QueryRequest(prompt="prompt", namespace=namespace)
    with pytest.raises(CacheValidationError):
        await embedded.get("prompt", namespace=namespace)


@pytest.mark.parametrize("ttl", [None, 1.0, 30.0, 120.0])
def test_ttl_cap_parity(ttl: float | None) -> None:
    adapter = Adapter()
    server_cache = SemanticCache(
        adapter, InMemoryCacheBackend(max_size=500, ttl_seconds=60, dimensions=2), 0.92
    )
    assert server_cache.resolve_ttl(ttl) == resolve_ttl(ttl, 60.0)


async def test_memory_ties_stay_stable_after_access() -> None:
    adapter = Adapter()
    backend = InMemoryCacheBackend(max_size=500, ttl_seconds=3600, dimensions=2)
    server_cache = SemanticCache(EmbeddingService(adapter, dimensions=2), backend, 0.92)
    embedded = AsyncSemanticCache(
        embedder=adapter, store=MemoryStore(embedding_space=adapter.embedding_space)
    )
    for prompt in ("oldest", "newer"):
        await server_cache.store(prompt, "answer: " + prompt)
        await embedded.set(prompt, "answer: " + prompt)
    for _ in range(3):
        remote = await server_cache.lookup("question")
        local = await embedded.get("question")
        assert local is not None
        assert (
            remote.matched_cache_key
            == local.matched_cache_key
            == prompt_cache_key("oldest")
        )
