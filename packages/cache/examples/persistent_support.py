"""Customer-support cache in your database; no Semantix server is required.

Run from packages/cache: python -m examples.persistent_support [--initialize].
Set SEMANTIX_CACHE_DATABASE_URL to an application runtime DSN. Explicit setup
also requires SEMANTIX_CACHE_MIGRATION_DATABASE_URL. Operators install vector.
The two-dimensional embedding below demonstrates wiring, not a language model.
"""

import argparse
import asyncio
import os
from collections.abc import Sequence

import asyncpg

from semantix_cache import AsyncSemanticCache, EmbeddingSpace
from semantix_cache.stores.pgvector import PgVectorStore


class SupportEmbedding:
    embedding_space = EmbeddingSpace(identity="support:demo:r1:d2:raw", dimensions=2)

    async def embed(self, text: str) -> Sequence[float]:
        return (1.0, 0.0) if "address" in text.lower() else (0.0, 1.0)


async def generate(prompt: str) -> str:
    return "Application-approved support answer for: " + prompt


async def main(*, initialize: bool = False) -> None:
    embedder = SupportEmbedding()
    async with await PgVectorStore.connect(
        dsn=os.environ["SEMANTIX_CACHE_DATABASE_URL"],
        embedding_space=embedder.embedding_space,
    ) as store:
        if initialize:
            # Deployment action only: no runtime/first-query implicit migration.
            async with asyncpg.create_pool(
                os.environ["SEMANTIX_CACHE_MIGRATION_DATABASE_URL"],
                min_size=1,
                max_size=1,
                timeout=10,
                command_timeout=30,
            ) as migration_pool:
                await store.initialize_schema(migration_pool=migration_pool)
        await store.validate_schema()
        async with AsyncSemanticCache(embedder=embedder, store=store) as cache:
            await cache.resolve(
                "How can I change my address?",
                namespace="support",
                generate=generate,
            )
            reused = await cache.resolve(
                "Please update my address",
                namespace="support",
                generate=generate,
            )
            if not reused.cache_hit or not reused.generation_skipped:
                raise RuntimeError(
                    "Persistent support example did not reuse its answer"
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", action="store_true")
    asyncio.run(main(initialize=parser.parse_args().initialize))
