import asyncio
from collections.abc import Sequence

import pytest

from app.cache.application.service import SemanticCache
from app.cache.domain.models import CacheCandidate
from app.cache.infrastructure.backends.memory import InMemoryCacheBackend
from app.core.limits import MAX_REQUEST_CACHE_TTL_SECONDS
from tests.support import (
    TEST_EMBEDDING_DIMENSIONS,
    memory_backend,
    unit_vector,
)


class Embeddings:
    async def embed(self, text: str) -> Sequence[float]:
        if text == "near":
            return [0.8, 0.6] + [0.0] * (TEST_EMBEDDING_DIMENSIONS - 2)

        return unit_vector() if text in {"one", "similar"} else unit_vector(1)


class RecordingEmbeddings:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def embed(self, text: str) -> Sequence[float]:
        self.prompts.append(text)
        return unit_vector()


class PausingMemoryBackend(InMemoryCacheBackend):
    def __init__(self) -> None:
        super().__init__(
            max_size=10,
            ttl_seconds=60,
            dimensions=TEST_EMBEDDING_DIMENSIONS,
        )
        self.candidate_selected = asyncio.Event()
        self.continue_lookup = asyncio.Event()
        self.pause_next_candidate = False

    async def find_nearest(
        self,
        embedding: Sequence[float],
        *,
        namespace: str,
    ) -> CacheCandidate | None:
        candidate = await super().find_nearest(
            embedding,
            namespace=namespace,
        )
        if self.pause_next_candidate and candidate is not None:
            self.pause_next_candidate = False
            self.candidate_selected.set()
            await self.continue_lookup.wait()
        return candidate


@pytest.mark.asyncio
async def test_semantic_hit() -> None:
    cache = SemanticCache(
        Embeddings(),
        memory_backend(),
        0.92,
    )
    miss = await cache.lookup("one")
    await cache.store("one", "answer", miss.embedding)
    hit = await cache.lookup("similar")

    assert hit.cache_hit
    assert hit.response == "answer"
    assert hit.similarity_threshold == pytest.approx(0.92)
    assert hit.matched_prompt == "one"
    assert hit.matched_cache_key is not None
    assert hit.cache_entry_created_at is not None


@pytest.mark.asyncio
async def test_ttl_expiry() -> None:
    cache = SemanticCache(
        Embeddings(),
        memory_backend(ttl_seconds=0.01),
        0.92,
    )
    miss = await cache.lookup("one")
    await cache.store("one", "answer", miss.embedding)
    await asyncio.sleep(0.02)
    assert not (await cache.lookup("similar")).cache_hit


def test_resolves_requested_ttl_against_the_server_default() -> None:
    finite = SemanticCache(
        Embeddings(),
        memory_backend(ttl_seconds=60),
        0.92,
    )
    unlimited = SemanticCache(
        Embeddings(),
        memory_backend(ttl_seconds=None),
        0.92,
    )

    assert finite.resolve_ttl(None) == 60
    assert finite.resolve_ttl(30) == 30
    assert finite.resolve_ttl(120) == 60
    assert unlimited.resolve_ttl(None) is None
    assert unlimited.resolve_ttl(30) == 30
    with pytest.raises(ValueError, match="supported range"):
        finite.resolve_ttl(0)
    with pytest.raises(ValueError, match="supported range"):
        finite.resolve_ttl(MAX_REQUEST_CACHE_TTL_SECONDS + 1)


@pytest.mark.asyncio
async def test_clear_resets_stats() -> None:
    cache = SemanticCache(
        Embeddings(),
        memory_backend(),
        0.92,
    )
    await cache.lookup("one")
    await cache.clear()
    assert (await cache.stats()).misses == 0


@pytest.mark.asyncio
async def test_updated_threshold_changes_lookup_rule() -> None:
    cache = SemanticCache(
        Embeddings(),
        memory_backend(),
        0.9,
    )
    initial_lookup = await cache.lookup("one")
    await cache.store("one", "answer", initial_lookup.embedding)

    miss = await cache.lookup("near")
    assert not miss.cache_hit
    assert miss.similarity_threshold == pytest.approx(0.9)
    assert miss.matched_prompt is None
    assert miss.matched_cache_key is None
    assert miss.cache_entry_created_at is None

    assert cache.update_similarity_threshold(0.75) == 0.75
    hit = await cache.lookup("near")
    assert hit.cache_hit
    assert hit.similarity_threshold == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_blank_response_is_not_stored() -> None:
    cache = SemanticCache(
        Embeddings(),
        memory_backend(),
        0.92,
    )
    miss = await cache.lookup("one")

    stored = await cache.store("one", " \n\t", miss.embedding)

    assert stored is False
    assert (await cache.stats()).size == 0


@pytest.mark.asyncio
async def test_normalizes_matching_text_but_preserves_stored_prompt() -> None:
    embeddings = RecordingEmbeddings()
    corrections = {
        "semntic caching": "semantic caching",
    }
    cache = SemanticCache(
        embeddings,
        memory_backend(),
        0.92,
        prompt_normalizer=lambda prompt: corrections.get(prompt, prompt),
    )

    miss = await cache.lookup("semntic caching")
    await cache.store("semntic caching", "answer", miss.embedding)
    hit = await cache.lookup("semantic caching")

    assert embeddings.prompts == ["semantic caching", "semantic caching"]
    assert hit.cache_hit is True
    assert hit.matched_prompt == "semntic caching"


@pytest.mark.asyncio
async def test_write_without_lookup_normalizes_embedding_prompt() -> None:
    embeddings = RecordingEmbeddings()
    cache = SemanticCache(
        embeddings,
        memory_backend(),
        0.92,
        prompt_normalizer=lambda prompt: "caching" if prompt == "cahcing" else prompt,
    )

    assert await cache.store("cahcing", "answer") is True

    assert embeddings.prompts == ["caching"]


@pytest.mark.asyncio
async def test_overwritten_candidate_is_not_returned_as_a_hit() -> None:
    backend = PausingMemoryBackend()
    cache = SemanticCache(Embeddings(), backend, 0.92)
    miss = await cache.lookup("one")
    await cache.store("one", "old answer", miss.embedding)
    backend.pause_next_candidate = True

    lookup = asyncio.create_task(cache.lookup("one"))
    await backend.candidate_selected.wait()
    await cache.store("one", "new answer", miss.embedding)
    backend.continue_lookup.set()
    result = await lookup

    assert result.cache_hit is False
    assert result.response is None
