"""Run the public offline recipes and demonstrate post-generation write failure."""

import pytest

from examples.context_identity import main
from examples.custom_integration import CustomEmbedding, demo_model
from semantix_cache import (
    AsyncSemanticCache,
    CacheEntry,
    CacheStoreError,
    EmbeddingSpace,
    MemoryStore,
)


async def test_context_identity_recipes() -> None:
    await main()


async def test_generation_succeeds_before_failed_write_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedder = CustomEmbedding(
        embedding_space=EmbeddingSpace(identity="demo-model:r1:raw:d2", dimensions=2),
        embed_text=demo_model,
    )
    effects: list[str] = []
    failure = CacheStoreError("Synthetic write failure")

    async def generate(prompt: str) -> str:
        effects.append("generation completed")
        return "Completed synthetic answer: " + prompt

    async def failed_write(
        entry: CacheEntry, *, ttl_seconds: float | None = None
    ) -> None:
        assert effects == ["generation completed"]
        raise failure

    async with (
        MemoryStore(embedding_space=embedder.embedding_space) as store,
        AsyncSemanticCache(embedder=embedder, store=store) as cache,
    ):
        monkeypatch.setattr(store, "put", failed_write)
        with pytest.raises(CacheStoreError) as caught:
            await cache.resolve(
                "weather today", namespace="failure-demo", generate=generate
            )
        assert caught.value is failure
        assert effects == ["generation completed"]  # No rollback or generation replay.
        assert await cache.get("weather today", namespace="failure-demo") is None
