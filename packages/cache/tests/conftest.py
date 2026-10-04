import os
from collections.abc import AsyncIterator, Sequence
from datetime import datetime

import asyncpg
import pytest

from semantix_cache import (
    AsyncSemanticCache,
    CacheEntry,
    CacheMatch,
    EmbeddingSpace,
    MemoryStore,
)


class Adapter:
    """Structural adapter: deliberately does not subclass the public protocol."""

    def __init__(
        self, *, identity: str = "test-v1", vector: Sequence[float] = (1.0, 0.0)
    ) -> None:
        self.space = EmbeddingSpace(identity=identity, dimensions=2)
        self.vector = vector
        self.calls: list[str] = []

    @property
    def embedding_space(self) -> EmbeddingSpace:
        return self.space

    async def embed(self, text: str) -> Sequence[float]:
        self.calls.append(text)
        return self.vector


class SpyStore(MemoryStore):
    def __init__(self, space: EmbeddingSpace) -> None:
        super().__init__(embedding_space=space)
        self.calls: list[str] = []

    async def find_nearest(
        self, embedding: Sequence[float], *, namespace: str
    ) -> CacheMatch | None:
        self.calls.append("read")
        return await super().find_nearest(embedding, namespace=namespace)

    async def put(self, entry: CacheEntry, *, ttl_seconds: float | None = None) -> None:
        self.calls.append("write")
        await super().put(entry, ttl_seconds=ttl_seconds)

    async def record_hit(
        self,
        cache_key: str,
        *,
        namespace: str,
        expected_created_at: datetime,
    ) -> bool:
        self.calls.append("confirm")
        return await super().record_hit(
            cache_key, namespace=namespace, expected_created_at=expected_created_at
        )


@pytest.fixture
def adapter() -> Adapter:
    return Adapter()


@pytest.fixture
def store(adapter: Adapter) -> SpyStore:
    return SpyStore(adapter.embedding_space)


@pytest.fixture
def cache(adapter: Adapter, store: SpyStore) -> AsyncSemanticCache:
    return AsyncSemanticCache(embedder=adapter, store=store)


async def generate(prompt: str) -> str:
    return "answer: " + prompt


@pytest.fixture
async def pg_pool() -> AsyncIterator[asyncpg.Pool | None]:
    dsn = os.environ.get("PGVECTOR_TEST_DATABASE_URL")
    if not dsn:
        yield None
        return
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4, command_timeout=10)
    assert pool is not None
    try:
        # Operator setup for this disposable test database, not library migration.
        async with pool.acquire() as connection:
            await connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        yield pool
    finally:
        await pool.close()
