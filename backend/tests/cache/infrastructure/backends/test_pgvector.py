import os

import pytest

from app.cache.domain.models import CacheEntry
from app.cache.domain.namespaces import DEFAULT_CACHE_NAMESPACE
from app.cache.infrastructure.factory import cache_backend_lifespan
from app.core.config import Settings
from tests.cache.infrastructure.backends.support import cache_entry
from tests.support import TEST_EMBEDDING_DIMENSIONS, unit_vector

pytestmark = pytest.mark.pgvector


def pgvector_settings(
    database_url: str,
    *,
    embedding_model: str,
) -> Settings:
    return Settings(
        cache_backend="pgvector",
        database_url=database_url,
        max_cache_size=10,
        cache_ttl_seconds=None,
        hf_api_key="test-only-placeholder",
        hf_embedding_model=embedding_model,
        hf_embedding_dimensions=TEST_EMBEDDING_DIMENSIONS,
        allowed_origins=["http://localhost:5173"],
    )


@pytest.mark.asyncio
async def test_embedding_spaces_remain_isolated_across_restarts() -> None:
    database_url = os.getenv("PGVECTOR_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL is not configured")

    first_settings = pgvector_settings(
        database_url,
        embedding_model="phase7-isolation-first",
    )
    second_settings = pgvector_settings(
        database_url,
        embedding_model="phase7-isolation-second",
    )
    stored = cache_entry(
        "shared prompt",
        "first response",
        vector_index=0,
    )

    async with cache_backend_lifespan(
        first_settings,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
        embedding_space=first_settings.embedding_space,
    ) as first:
        await first.clear(None)
        await first.put(stored)
        assert await first.record_hit(
            stored.cache_key,
            expected_created_at=stored.created_at,
        )
        await first.record_miss(DEFAULT_CACHE_NAMESPACE)

    async with cache_backend_lifespan(
        second_settings,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
        embedding_space=second_settings.embedding_space,
    ) as second:
        await second.clear(None)
        assert (await second.stats(None)).size == 0
        assert (
            await second.find_nearest(
                unit_vector(),
                namespace=DEFAULT_CACHE_NAMESPACE,
            )
            is None
        )
        await second.put(
            CacheEntry(
                **stored.model_dump(exclude={"response"}),
                response="second response",
            )
        )

    async with cache_backend_lifespan(
        first_settings,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
        embedding_space=first_settings.embedding_space,
    ) as first:
        nearest = await first.find_nearest(
            unit_vector(),
            namespace=DEFAULT_CACHE_NAMESPACE,
        )
        assert nearest is not None
        assert nearest.entry.response == "first response"
        metadata = await first.get_entry(
            stored.cache_key,
            authorized_namespaces=None,
        )
        assert metadata is not None
        assert metadata.hit_count == 1
        assert metadata.last_accessed_at is not None
        assert metadata.response == "first response"
        assert (await first.stats(None)).model_dump() == {
            "size": 1,
            "hits": 1,
            "misses": 1,
            "hit_rate": 0.5,
        }
        await first.clear(None)

    async with cache_backend_lifespan(
        second_settings,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
        embedding_space=second_settings.embedding_space,
    ) as second:
        nearest = await second.find_nearest(
            unit_vector(),
            namespace=DEFAULT_CACHE_NAMESPACE,
        )
        assert nearest is not None
        assert nearest.entry.response == "second response"
        await second.clear(None)


@pytest.mark.asyncio
async def test_custom_provider_spaces_isolate_equal_dimension_vectors() -> None:
    database_url = os.getenv("PGVECTOR_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PGVECTOR_TEST_DATABASE_URL is not configured")

    settings = pgvector_settings(
        database_url,
        embedding_model="unused-built-in-space",
    )
    first_space = "custom-provider-a:embedding-v1"
    second_space = "custom-provider-b:embedding-v1"
    stored = cache_entry(
        "same prompt and vector",
        "provider A response",
        vector_index=0,
    )

    async with cache_backend_lifespan(
        settings,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
        embedding_space=first_space,
    ) as first:
        await first.clear(None)
        await first.put(stored)

    async with cache_backend_lifespan(
        settings,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
        embedding_space=second_space,
    ) as second:
        await second.clear(None)
        assert (
            await second.find_nearest(
                unit_vector(),
                namespace=DEFAULT_CACHE_NAMESPACE,
            )
            is None
        )
        await second.put(
            CacheEntry(
                **stored.model_dump(exclude={"response"}),
                response="provider B response",
            )
        )

    async with cache_backend_lifespan(
        settings,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
        embedding_space=first_space,
    ) as first:
        nearest = await first.find_nearest(
            unit_vector(),
            namespace=DEFAULT_CACHE_NAMESPACE,
        )
        assert nearest is not None
        assert nearest.entry.response == "provider A response"
        await first.clear(None)

    async with cache_backend_lifespan(
        settings,
        dimensions=TEST_EMBEDDING_DIMENSIONS,
        embedding_space=second_space,
    ) as second:
        await second.clear(None)
