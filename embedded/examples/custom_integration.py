"""Executable, offline structural integration; substitute your own async model call."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from semantix_cache import (
    AsyncSemanticCache,
    EmbeddingAdapter,
    EmbeddingSpace,
    GenerationCallable,
    MemoryStore,
)


class CustomEmbedding:
    """No inheritance or registry: explicit metadata accompanies the callable."""

    def __init__(
        self,
        *,
        embedding_space: EmbeddingSpace,
        embed_text: Callable[[str], Awaitable[Sequence[float]]],
    ) -> None:
        self._embedding_space = embedding_space
        self._embed_text = embed_text

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self._embedding_space

    async def embed(self, text: str) -> Sequence[float]:
        return await self._embed_text(text)


async def demo_model(text: str) -> Sequence[float]:
    # Deterministic demo only; replace this with your existing async integration.
    return (1.0, 0.0) if "weather" in text else (0.0, 1.0)


class MyGenerationFlow:
    async def generate(self, prompt: str) -> str:
        # Your RAG, tool execution and moderation finish before returning final text.
        return "Application-approved final answer: " + prompt


async def main() -> None:
    adapter: EmbeddingAdapter = CustomEmbedding(
        embedding_space=EmbeddingSpace(identity="custom:demo:r1:d2:raw", dimensions=2),
        embed_text=demo_model,
    )
    generate: GenerationCallable = MyGenerationFlow().generate
    async with (
        MemoryStore(embedding_space=adapter.embedding_space) as store,
        AsyncSemanticCache(embedder=adapter, store=store) as cache,
    ):
        miss = await cache.resolve(
            "weather today", generate=generate, namespace="demo-generation-v1"
        )
        hit = await cache.resolve(
            "weather tomorrow", generate=generate, namespace="demo-generation-v1"
        )
        if not (
            miss.provider_called
            and miss.cache_written
            and hit.cache_hit
            and hit.generation_skipped
        ):
            raise RuntimeError(
                "Custom integration did not produce the expected miss and hit"
            )


if __name__ == "__main__":
    asyncio.run(main())
