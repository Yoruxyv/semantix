"""Offline SQLite persistence using the existing deterministic integration example."""

import asyncio
import tempfile
from pathlib import Path

from semantix_cache import AsyncSemanticCache, EmbeddingSpace
from semantix_cache.stores.sqlite import SQLiteStore

from .custom_integration import CustomEmbedding, MyGenerationFlow, demo_model


async def main() -> None:
    adapter = CustomEmbedding(
        embedding_space=EmbeddingSpace(identity="custom:demo:r1:d2:raw", dimensions=2),
        embed_text=demo_model,
    )
    generate = MyGenerationFlow().generate
    with tempfile.TemporaryDirectory(prefix="semantix-sqlite-example-") as directory:
        path = Path(directory) / "cache.db"
        await SQLiteStore.initialize_schema(
            path, embedding_space=adapter.embedding_space
        )
        async with (
            await SQLiteStore.connect(
                path, embedding_space=adapter.embedding_space
            ) as store,
            AsyncSemanticCache(embedder=adapter, store=store) as cache,
        ):
            miss = await cache.resolve("weather today", generate=generate)
            hit = await cache.resolve("weather tomorrow", generate=generate)
            if not (
                miss.provider_called
                and miss.cache_written
                and hit.cache_hit
                and hit.generation_skipped
            ):
                raise RuntimeError(
                    "SQLite integration did not produce the expected miss and hit"
                )
        async with (
            await SQLiteStore.connect(
                path, embedding_space=adapter.embedding_space
            ) as store,
            AsyncSemanticCache(embedder=adapter, store=store) as cache,
        ):
            persisted = await cache.get("weather next week")
            if persisted is None:
                raise RuntimeError(
                    "SQLite integration did not retain the entry after reopen"
                )


if __name__ == "__main__":
    asyncio.run(main())
